import json
import logging
from typing import Dict, Any, Optional

from app.core.phoenix_tracer import trace_workflow
from app.schemas.profile import CompanyProfile
from app.services.llm_sglang_client import get_sglang_client
from app.services.profile_pipeline.merge_models import MergedFacts

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_C = """Você é um construtor de perfis corporativos B2B.

TAREFA:
- Montar um objeto JSON CompanyProfile COMPLETO usando EXCLUSIVAMENTE os dados fornecidos em MergedFacts.

REGRAS CRÍTICAS:
- NUNCA invente informações que não estejam em MergedFacts.
- Se um dado não existir em MergedFacts, use:
  - null para campos escalares (strings, números)
  - [] para listas
- NÃO use conhecimento externo, suposições ou \"boas práticas\".
- NÃO adicione produtos, serviços, clientes, certificações ou prêmios que não estejam claramente presentes.
- Respeite unicidade de listas (sem duplicadas) e caps de tamanho do schema.
- A saída DEVE ser apenas JSON puro, sem texto explicativo ou markdown.
"""


async def build_company_profile(
    merged_facts: MergedFacts,
    *,
    ctx_label: str = "",
    request_id: str = "",
) -> CompanyProfile:
    """
    Estágio C: monta o CompanyProfile final a partir de um MergedFacts.
    """
    client = get_sglang_client()

    user_content = (
        "A seguir está o objeto MergedFacts em JSON.\n"
        "Use SOMENTE esses dados para preencher o CompanyProfile.\n\n"
        f"{merged_facts.model_dump_json(by_alias=False, exclude_none=True, ensure_ascii=False)}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_C},
        {"role": "user", "content": user_content},
    ]

    # Structured output via json_schema (compatível com OpenAI)
    schema = CompanyProfile.model_json_schema()
    response_format: Dict[str, Any] = {
        "type": "json_schema",
        "json_schema": {
            "name": "company_profile_extraction",
            "schema": schema,
            "strict": True,
        },
    }

    logger.info(f"{ctx_label}ProfileBuilder: chamando SGLang para build do CompanyProfile")

    async with trace_workflow("profile-llm", "profile.build") as span:
        data = await client.chat_completion(
            messages,
            temperature=0.0,
            top_p=1.0,
            max_tokens=2200,
            response_format=response_format,
            extra_params={"seed": 42},
            ctx_label=ctx_label,
        )

        content: Optional[str] = None
        try:
            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
        except Exception:
            content = None

        if not content:
            logger.error(f"{ctx_label}ProfileBuilder: resposta vazia do LLM, retornando perfil vazio")
            return CompanyProfile()

        # Parsing robusto
        raw = content.strip()
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            # tentar json_repair se disponível
            try:
                import json_repair

                obj = json_repair.loads(raw)
            except Exception as e:
                logger.error(
                    f"{ctx_label}ProfileBuilder: JSON inválido mesmo após repair: {e}. "
                    f"Primeiros 500 chars: {raw[:500]}"
                )
                return CompanyProfile()

        # Validar contra CompanyProfile
        try:
            profile = CompanyProfile.model_validate(obj)
        except Exception as e:
            logger.error(
                f"{ctx_label}ProfileBuilder: falha na validação Pydantic do CompanyProfile: {e}"
            )
            # Fallback mínimo: tentar pelo construtor direto
            try:
                profile = CompanyProfile(**obj)
            except Exception:
                logger.error(f"{ctx_label}ProfileBuilder: falha crítica ao construir CompanyProfile")
                return CompanyProfile()

        # Métricas de preenchimento e caps
        if span:
            # identity
            identity_fields = [
                profile.identity.company_name,
                profile.identity.cnpj,
                profile.identity.tagline,
                profile.identity.description,
                profile.identity.founding_year,
                profile.identity.employee_count_range,
            ]
            filled_identity = sum(1 for v in identity_fields if v)
            span.set_attribute("fill_rate.identity", filled_identity / len(identity_fields))

            # contact
            contact_lists = [
                profile.contact.emails,
                profile.contact.phones,
                profile.contact.locations,
            ]
            contact_scalars = [
                profile.contact.linkedin_url,
                profile.contact.website_url,
                profile.contact.headquarters_address,
            ]
            total_contact_slots = len(contact_lists) + len(contact_scalars)
            filled_contact = sum(1 for lst in contact_lists if lst) + sum(
                1 for v in contact_scalars if v
            )
            span.set_attribute(
                "fill_rate.contact",
                filled_contact / total_contact_slots if total_contact_slots else 0.0,
            )

            # offerings
            offerings_lists = [
                profile.offerings.products,
                profile.offerings.services,
                profile.offerings.product_categories,
                profile.offerings.engagement_models,
                profile.offerings.key_differentiators,
            ]
            total_offerings_slots = len(offerings_lists)
            filled_offerings = sum(1 for lst in offerings_lists if lst)
            span.set_attribute(
                "fill_rate.offerings",
                filled_offerings / total_offerings_slots if total_offerings_slots else 0.0,
            )

            # reputation
            reputation_lists = [
                profile.reputation.certifications,
                profile.reputation.awards,
                profile.reputation.partnerships,
                profile.reputation.client_list,
                profile.reputation.case_studies,
            ]
            total_rep_slots = len(reputation_lists)
            filled_rep = sum(1 for lst in reputation_lists if lst)
            span.set_attribute(
                "fill_rate.reputation",
                filled_rep / total_rep_slots if total_rep_slots else 0.0,
            )

            # cap_hit_rate aproximado com base nos caps do schema
            cap_hits = 0
            cap_total = 0

            # contact caps
            cap_total += 3
            if len(profile.contact.emails) >= 10:
                cap_hits += 1
            if len(profile.contact.phones) >= 10:
                cap_hits += 1
            if len(profile.contact.locations) >= 25:
                cap_hits += 1

            # offerings caps
            cap_total += 3
            if len(profile.offerings.products) >= 60:
                cap_hits += 1
            if len(profile.offerings.services) >= 60:
                cap_hits += 1
            if len(profile.offerings.product_categories) >= 40:
                cap_hits += 1

            # reputation caps
            cap_total += 4
            if len(profile.reputation.certifications) >= 30:
                cap_hits += 1
            if len(profile.reputation.awards) >= 20:
                cap_hits += 1
            if len(profile.reputation.partnerships) >= 50:
                cap_hits += 1
            if len(profile.reputation.client_list) >= 80:
                cap_hits += 1

            cap_hit_rate = (cap_hits / cap_total) if cap_total else 0.0
            span.set_attribute("cap_hit_rate", cap_hit_rate)

        return profile

