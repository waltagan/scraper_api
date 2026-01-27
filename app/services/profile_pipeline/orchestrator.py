import logging
from typing import List

from app.core.phoenix_tracer import trace_workflow
from app.schemas.profile import CompanyProfile
from app.services.database_service import get_db_service
from app.services.profile_pipeline.fact_extractor import extract_facts_for_cnpj
from app.services.profile_pipeline.merge_service import merge_fact_bundles
from app.services.profile_pipeline.profile_builder import build_company_profile

logger = logging.getLogger(__name__)


async def run_profile_pipeline(
    cnpj_basico: str,
    *,
    ctx_label: str = "",
    request_id: str = "",
) -> CompanyProfile:
    """
    Orquestra o pipeline completo de perfil para um CNPJ:
    1) Busca scraped_chunks no banco.
    2) Estágio A: Fact Extraction por chunk.
    3) Estágio B: Merge determinístico dos FactBundles.
    4) Estágio C: Build final do CompanyProfile via LLM.
    5) Salva o perfil consolidado no banco.
    """
    db = get_db_service()

    # 1. Garantir que há chunks
    chunks = await db.get_chunks(cnpj_basico)
    if not chunks:
        logger.warning(f"{ctx_label}ProfilePipeline: nenhum scraped_chunk encontrado para cnpj={cnpj_basico}")
        return CompanyProfile()

    total_chunks = len(chunks)
    website_url = chunks[0].get("website_url") if chunks else None

    async with trace_workflow("profile-llm", "profile_pipeline.run") as span:
        if span:
            span.set_attribute("cnpj_basico", cnpj_basico)
            span.set_attribute("total_chunks", total_chunks)
            if website_url:
                span.set_attribute("website_url", website_url)
            span.set_attribute("pipeline_version", "v3.0")

        # 2. Estágio A – Fact Extraction
        fact_bundles = await extract_facts_for_cnpj(
            cnpj_basico,
            ctx_label=f"{ctx_label}[FactA] ",
            request_id=request_id,
        )

        if not fact_bundles:
            logger.warning(f"{ctx_label}ProfilePipeline: nenhum FactBundle gerado para cnpj={cnpj_basico}")
            return CompanyProfile()

        total_bundles = len(fact_bundles)
        empty_bundles = sum(1 for b in fact_bundles if getattr(b, "useful_count", 0) == 0)
        useful_bundles = total_bundles - empty_bundles
        empty_rate = (empty_bundles / total_bundles) if total_bundles > 0 else 0.0

        if span:
            span.set_attribute("fact_bundles.total", total_bundles)
            span.set_attribute("fact_bundles.empty", empty_bundles)
            span.set_attribute("fact_bundles.useful", useful_bundles)
            span.set_attribute("empty_fact_chunk_rate", empty_rate)

        # 3. Estágio B – Merge determinístico
        # Métricas de entrada para o merge
        total_input_facts = 0
        for b in fact_bundles:
            total_input_facts += (
                len(b.identity_facts)
                + len(b.contact_facts)
                + len(b.offerings_facts)
                + len(b.reputation_facts)
            )

        async with trace_workflow("profile-llm", "facts.merge") as merge_span:
            merged_facts = merge_fact_bundles(fact_bundles)

            if merge_span:
                merged_json = merged_facts.model_dump_json(exclude_none=True, ensure_ascii=False)
                merged_size = len(merged_json)
                merged_items = (
                    len(merged_facts.contact.emails)
                    + len(merged_facts.contact.phones)
                    + len(merged_facts.contact.locations)
                    + len(merged_facts.offerings.products)
                    + len(merged_facts.offerings.services)
                    + len(merged_facts.reputation.client_list)
                    + len(merged_facts.reputation.certifications)
                    + len(merged_facts.reputation.awards)
                    + len(merged_facts.reputation.partnerships)
                )
                dedupe_delta = max(0, total_input_facts - merged_items)

                merge_span.set_attribute("input_fact_bundles", total_bundles)
                merge_span.set_attribute("input_fact_items", total_input_facts)
                merge_span.set_attribute("merged_items", merged_items)
                merge_span.set_attribute("dedupe_delta", dedupe_delta)
                merge_span.set_attribute("routing_errors", 0)
                merge_span.set_attribute("merged_facts_size", merged_size)

        # 4. Estágio C – Build final do CompanyProfile
        profile = await build_company_profile(
            merged_facts,
            ctx_label=f"{ctx_label}[BuildC] ",
            request_id=request_id,
        )

        # 5. Persistir perfil
        await db.save_profile(cnpj_basico, profile)

        return profile

