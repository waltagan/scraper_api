import json
import logging
from typing import List

from app.core.phoenix_tracer import trace_workflow
from app.services.database_service import get_db_service
from app.services.llm_sglang_client import get_sglang_client
from app.services.profile_pipeline.fact_models import FactBundle, FactItem, FactSource

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_A = """Você é um minerador de fatos corporativos B2B.

TAREFA:
- A PARTIR DE UM ÚNICO CHUNK de conteúdo de website, extrair SOMENTE fatos explícitos
  sobre a empresa, NUNCA montar o perfil completo, NUNCA combinar múltiplos chunks.

REGRAS CRÍTICAS:
- Proibido inventar informações não presentes no texto do chunk.
- Cada fato deve ter:
  - value: o valor textual do fato.
  - evidence_quote: um trecho literal curto (<= 160 chars) copiado do texto.
  - confidence: número entre 0.0 e 1.0.
- Limite máximo de 20 itens por lista.
- Deduplicar localmente valores repetidos.

NÃO MONTE o objeto CompanyProfile final aqui.
Retorne SOMENTE um objeto JSON FactBundle com os campos:
- source
- identity_facts
- contact_facts
- offerings_facts
- reputation_facts
"""


async def extract_facts_for_cnpj(
    cnpj_basico: str,
    *,
    ctx_label: str = "",
    request_id: str = "",
) -> List[FactBundle]:
    """
    Estágio A: extrai FactBundles para todos os scraped_chunks de um CNPJ.
    """
    db = get_db_service()
    sglang = get_sglang_client()

    chunks = await db.get_chunks(cnpj_basico)
    if not chunks:
        logger.warning(f"{ctx_label}FactExtractor: nenhum chunk encontrado para cnpj={cnpj_basico}")
        return []

    total_chunks = len(chunks)
    logger.info(f"{ctx_label}FactExtractor: extraindo fatos de {total_chunks} chunks (cnpj={cnpj_basico})")

    async def process_chunk(chunk: dict) -> FactBundle:
        chunk_index = int(chunk.get("chunk_index", 0) or 0)
        content = chunk.get("chunk_content", "") or ""
        token_count = int(chunk.get("token_count", 0) or 0)
        page_source_raw = chunk.get("page_source") or ""
        page_source = [u.strip() for u in page_source_raw.split(",") if u.strip()]

        if not content.strip():
            logger.warning(
                f"{ctx_label}FactExtractor: chunk {chunk_index}/{total_chunks} vazio para cnpj={cnpj_basico}"
            )
            bundle = FactBundle(
                source=FactSource(
                    chunk_index=chunk_index or 1,
                    total_chunks=total_chunks,
                    page_source=page_source,
                )
            )
            bundle.compute_useful_count()
            return bundle

        async with trace_workflow("profile-llm", "chunk.fact_extract") as span:
            user_prompt = (
                f"chunk_index={chunk_index} / total_chunks={total_chunks}\n"
                f"token_count={token_count}\n"
                f"page_source={page_source}\n\n"
                "CONTEÚDO DO CHUNK:\n\n"
                f"{content}"
            )

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT_A},
                {"role": "user", "content": user_prompt},
            ]

            if span:
                span.set_attribute("stage", "fact_extraction")
                span.set_attribute("chunk_index", chunk_index)
                span.set_attribute("total_chunks", total_chunks)
                span.set_attribute("token_count", token_count)
                span.set_attribute("page_source", ", ".join(page_source))

            data = await sglang.chat_completion(
                messages,
                temperature=0.0,
                top_p=1.0,
                max_tokens=900,
                response_format={"type": "json_object"},
                extra_params={"seed": 42},
                ctx_label=ctx_label,
            )

            raw_content = ""
            try:
                choices = data.get("choices", [])
                if choices:
                    raw_content = choices[0].get("message", {}).get("content", "") or ""
            except Exception:
                raw_content = ""

            if not raw_content.strip():
                logger.warning(
                    f"{ctx_label}FactExtractor: resposta vazia do LLM para chunk {chunk_index}/{total_chunks}"
                )
                bundle = FactBundle(
                    source=FactSource(
                        chunk_index=chunk_index or 1,
                        total_chunks=total_chunks,
                        page_source=page_source,
                    )
                )
                bundle.compute_useful_count()
                if span:
                    span.set_attribute("useful_facts", bundle.useful_count)
                return bundle

            # parse JSON robusto
            try:
                payload = json.loads(raw_content)
            except json.JSONDecodeError:
                try:
                    import json_repair

                    payload = json_repair.loads(raw_content)
                except Exception as e:
                    logger.error(
                        f"{ctx_label}FactExtractor: JSON inválido em chunk {chunk_index}: {e}. "
                        f"Primeiros 300 chars: {raw_content[:300]}"
                    )
                    bundle = FactBundle(
                        source=FactSource(
                            chunk_index=chunk_index or 1,
                            total_chunks=total_chunks,
                            page_source=page_source,
                        )
                    )
                    bundle.compute_useful_count()
                    if span:
                        span.set_attribute("useful_facts", bundle.useful_count)
                    return bundle

            # construir FactBundle tipado
            try:
                # garantir metadados de source
                payload["source"] = {
                    "chunk_index": chunk_index or 1,
                    "total_chunks": total_chunks,
                    "page_source": page_source,
                }
                bundle = FactBundle.model_validate(payload)
            except Exception as e:
                logger.error(
                    f"{ctx_label}FactExtractor: falha ao validar FactBundle para chunk {chunk_index}: {e}"
                )
                bundle = FactBundle(
                    source=FactSource(
                        chunk_index=chunk_index or 1,
                        total_chunks=total_chunks,
                        page_source=page_source,
                    )
                )

            useful = bundle.compute_useful_count()
            if span:
                span.set_attribute("useful_facts", useful)

            return bundle

    # processar todos em paralelo
    import asyncio

    tasks = [process_chunk(ch) for ch in chunks]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    bundles: List[FactBundle] = []
    for idx, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error(
                f"{ctx_label}FactExtractor: exceção ao processar chunk {idx+1}/{total_chunks}: {r}"
            )
        else:
            bundles.append(r)

    return bundles

