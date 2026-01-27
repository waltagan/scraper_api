import logging
import re
from typing import Iterable, List, Tuple

from app.services.profile_pipeline.fact_models import FactBundle, FactItem
from app.services.profile_pipeline.merge_models import (
    EvidenceEntry,
    MergedContact,
    MergedFacts,
    MergedIdentity,
    MergedOfferings,
    MergedReputation,
)

logger = logging.getLogger(__name__)


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _normalize_url(value: str) -> str:
    v = value.strip()
    if not v:
        return v
    # remover tracking básico
    v = re.sub(r"[?#].*$", "", v)
    # normalizar trailing slash (exceto raiz)
    if v.endswith("/") and len(v) > len("https://a"):
        v = v[:-1]
    return v


def _normalize_phone(value: str) -> str:
    # manter apenas dígitos e + no começo
    v = value.strip()
    digits = re.sub(r"[^\d+]", "", v)
    return digits


def _normalize_generic(value: str) -> str:
    # trim + normalizar múltiplos espaços
    v = " ".join((value or "").split())
    return v


def _normalize_service_label(value: str) -> str:
    """
    Normalização semântica leve para serviços.

    - lowercase
    - remoção de plurais simples
    - remoção de artigos/preposições comuns
    """
    v = _normalize_generic(value).lower()
    # remover artigos/preposições muito comuns
    stopwords = {"de", "da", "do", "das", "dos"}
    tokens = [t for t in v.split() if t not in stopwords]
    v = " ".join(tokens)
    # remover plural simples (heurística ingênua)
    v = re.sub(r"\bsistemas\b", "sistema", v)
    v = re.sub(r"\bserviços\b", "serviço", v)
    v = re.sub(r"\bsoluções\b", "solução", v)
    return v.strip()


def _is_likely_product(text: str) -> bool:
    """
    Heurística determinística para decidir se um texto parece produto.

    Critérios (qualquer um verdadeiro → produto):
    - contém dígitos + letras em padrão de modelo/código (ex.: X100, 5000X, AB-123).
    - contém unidade típica (mm, cm, kg, gb, v, ml, l, hz).
    - contém palavras chave de SKU/código/modelo.
    """
    t = text.strip()
    if not t:
        return False

    # padrão simples: letras + dígitos misturados
    if re.search(r"[A-Za-z].*\d|\d.*[A-Za-z]", t):
        return True

    # unidades frequentes
    if re.search(r"\b(\d+)\s?(mm|cm|m|kg|g|gb|tb|v|hz|w|l|ml)\b", t, flags=re.IGNORECASE):
        return True

    # palavras que sugerem código/modelo
    if re.search(r"\b(modelo|código|sku|ref\.?|reference)\b", t, flags=re.IGNORECASE):
        return True

    return False


def _add_evidence(
    evidence_map: dict,
    key: str,
    url: str,
    quote: str,
) -> None:
    lst = evidence_map.setdefault(key, [])
    if len(lst) >= 20:
        return
    lst.append(EvidenceEntry(url=url, quote=quote))


def merge_fact_bundles(bundles: Iterable[FactBundle]) -> MergedFacts:
    """
    Estágio B: merge determinístico de múltiplos FactBundle em um MergedFacts.
    Ignora FactBundles marcados como vazios (useful_count == 0).
    """
    all_bundles = list(bundles)
    # Filtrar explicitamente bundles inúteis
    active_bundles = [b for b in all_bundles if getattr(b, "useful_count", 0) > 0]

    merged = MergedFacts()

    if not active_bundles:
        logger.info(
            f"MergeFacts: todos os {len(all_bundles)} FactBundles são vazios; "
            f"retornando MergedFacts em branco."
        )
        return merged

    evidence_map = merged.evidence_map

    # --- Identity (nome, cnpj, descrição, tagline, etc.) ---
    name_candidates: List[Tuple[str, str]] = []  # (valor, url)
    desc_candidates: List[Tuple[str, str]] = []

    for b in active_bundles:
        urls = b.source.page_source or []
        main_url = urls[0] if urls else ""

        for item in b.identity_facts:
            norm = _normalize_generic(item.value)
            if not norm:
                continue

            lower = norm.lower()
            if "cnpj" in lower or re.search(r"\d{11,14}", lower):
                # heurística simples: assume valor inteiro como cnpj
                merged.identity.cnpj = merged.identity.cnpj or norm
                _add_evidence(evidence_map, "identity.cnpj", main_url, item.evidence_quote)
            elif any(word in lower for word in ["ltda", "s.a", "sa ", "me ", "eireli"]):
                name_candidates.append((norm, main_url))
                _add_evidence(
                    evidence_map, "identity.company_name", main_url, item.evidence_quote
                )
            elif "fundada" in lower or "desde" in lower:
                merged.identity.founding_year = (
                    merged.identity.founding_year or norm
                )
                _add_evidence(
                    evidence_map, "identity.founding_year", main_url, item.evidence_quote
                )
            else:
                desc_candidates.append((norm, main_url))
                _add_evidence(
                    evidence_map, "identity.description", main_url, item.evidence_quote
                )

    # escolher melhor company_name (se houver)
    if name_candidates and not merged.identity.company_name:
        merged.identity.company_name = name_candidates[0][0]

    # descrição: preferir uma curta e informativa
    if desc_candidates and not merged.identity.description:
        # pegar a menor descrição que ainda tenha tamanho razoável
        desc_candidates_sorted = sorted(desc_candidates, key=lambda x: len(x[0]))
        merged.identity.description = desc_candidates_sorted[0][0]

    # --- Contact (emails, phones, urls, locations) ---
    email_set = set()
    phone_set = set()
    url_set = set()
    locations_set = set()

    for b in active_bundles:
        urls = b.source.page_source or []
        main_url = urls[0] if urls else ""

        for item in b.contact_facts:
            raw = item.value
            v = _normalize_generic(raw)
            if not v:
                continue

            if "@" in v:
                email = _normalize_email(v)
                if email and email not in email_set:
                    email_set.add(email)
                    merged.contact.emails.append(email)
                    _add_evidence(evidence_map, "contact.emails", main_url, item.evidence_quote)
            elif re.search(r"\d{8,}", v):
                phone = _normalize_phone(v)
                if phone and phone not in phone_set:
                    phone_set.add(phone)
                    merged.contact.phones.append(phone)
                    _add_evidence(evidence_map, "contact.phones", main_url, item.evidence_quote)
            elif v.startswith("http://") or v.startswith("https://"):
                url = _normalize_url(v)
                if url and url not in url_set:
                    url_set.add(url)
                    # heurística: primeira URL é website principal
                    if not merged.contact.website_url:
                        merged.contact.website_url = url
                    _add_evidence(
                        evidence_map, "contact.website_url", main_url or url, item.evidence_quote
                    )
            else:
                # tratar como possível localização/endereço
                loc = _normalize_generic(v)
                if len(loc) >= 5 and loc.lower() not in locations_set:
                    locations_set.add(loc.lower())
                    merged.contact.locations.append(loc)
                    _add_evidence(
                        evidence_map, "contact.locations", main_url, item.evidence_quote
                    )

    # --- Offerings (products vs services) ---
    prod_set = set()
    serv_set = set()

    for b in active_bundles:
        urls = b.source.page_source or []
        main_url = urls[0] if urls else ""

        for item in b.offerings_facts:
            raw = item.value
            v = _normalize_generic(raw)
            if not v:
                continue

            if _is_likely_product(v):
                key = v.lower()
                if key not in prod_set:
                    prod_set.add(key)
                    merged.offerings.products.append(v)
                    _add_evidence(
                        evidence_map, "offerings.products", main_url, item.evidence_quote
                    )
            else:
                norm_service = _normalize_service_label(v)
                if not norm_service:
                    continue
                key = norm_service.lower()
                if key not in serv_set:
                    serv_set.add(key)
                    merged.offerings.services.append(norm_service)
                    _add_evidence(
                        evidence_map, "offerings.services", main_url, item.evidence_quote
                    )

    # caps globais de segurança
    merged.contact.emails = merged.contact.emails[:80]
    merged.contact.phones = merged.contact.phones[:80]
    merged.contact.locations = merged.contact.locations[:80]
    merged.offerings.products = merged.offerings.products[:80]
    merged.offerings.services = merged.offerings.services[:80]

    # --- Reputation (clientes, certificações, etc.) ---
    client_set = set()
    cert_set = set()
    awards_set = set()
    partners_set = set()

    client_keywords = ("cliente", "clientes", "quem confia", "cases", "nossos clientes")
    cert_keywords = ("certificação", "iso", "anvisa", "inmetro")
    award_keywords = ("prêmio", "premiação", "award")
    partner_keywords = ("parceria", "parceiro", "partner")

    for b in active_bundles:
        urls = b.source.page_source or []
        main_url = urls[0] if urls else ""

        for item in b.reputation_facts:
            quote_lower = item.evidence_quote.lower()
            v = _normalize_generic(item.value)
            if not v:
                continue

            if any(k in quote_lower for k in client_keywords):
                key = v.lower()
                if key not in client_set:
                    client_set.add(key)
                    merged.reputation.client_list.append(v)
                    _add_evidence(
                        evidence_map, "reputation.client_list", main_url, item.evidence_quote
                    )
            elif any(k in quote_lower for k in cert_keywords):
                key = v.lower()
                if key not in cert_set:
                    cert_set.add(key)
                    merged.reputation.certifications.append(v)
                    _add_evidence(
                        evidence_map, "reputation.certifications", main_url, item.evidence_quote
                    )
            elif any(k in quote_lower for k in award_keywords):
                key = v.lower()
                if key not in awards_set:
                    awards_set.add(key)
                    merged.reputation.awards.append(v)
                    _add_evidence(
                        evidence_map, "reputation.awards", main_url, item.evidence_quote
                    )
            elif any(k in quote_lower for k in partner_keywords):
                key = v.lower()
                if key not in partners_set:
                    partners_set.add(key)
                    merged.reputation.partnerships.append(v)
                    _add_evidence(
                        evidence_map, "reputation.partnerships", main_url, item.evidence_quote
                    )

    # caps globais
    merged.reputation.client_list = merged.reputation.client_list[:80]
    merged.reputation.certifications = merged.reputation.certifications[:50]
    merged.reputation.awards = merged.reputation.awards[:50]
    merged.reputation.partnerships = merged.reputation.partnerships[:50]

    return merged

