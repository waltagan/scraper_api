"""
Endpoint Scrape v2 - Scraping assincrono de site com chunking e persistencia.
Processamento em background - retorna imediatamente apos aceitar requisicao.
"""
import logging
import time
import asyncio
import json
import uuid
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Query
from app.schemas.v2.scrape import (
    ScrapeRequest,
    ScrapeResponse,
    ScrapeMainPageRequest,
    ScrapeMainPageProcessRequest,
    ScrapeMainPageResponse,
    ScrapeMainPageBatchRequest,
    ScrapeMainBatchRequest,
    ScrapeMainBatchResponse,
    ScrapeMainUnifiedRequest,
    ScrapeMainUnifiedBatchRequest,
    ScrapeMainUnifiedResponse,
    ScrapeMainUnifiedBatchResponse,
)
from app.services.scraper import (
    scrape_all_subpages,
    scrape_main_page_raw,
    extract_subpage_links_from_raw,
    extract_mainpage_text_from_raw,
    extract_text_and_links_from_raw,
)
from app.services.scraper_manager.proxy_manager import proxy_pool
from app.services.scraper_manager.raw_content_cache import raw_content_cache
from app.services.database_service import get_db_service
from app.core.chunking import process_content
from app.core.metrics import (
    observe_error,
    observe_request,
    observe_company_total,
    observe_batch_run,
    observe_batch_flush,
    observe_company_load,
    unified_inflight_requests,
    unified_queue_depth,
    unified_pending_results_depth,
    unified_parse_workers,
)

logger = logging.getLogger(__name__)

router = APIRouter()
db_service = get_db_service()


def _chunk_list(items: List[Any], size: int) -> List[List[Any]]:
    if size <= 0:
        return [items]
    return [items[i:i + size] for i in range(0, len(items), size)]


def _allocate_provider_slices(
    total_items: int,
    providers: List[str],
    per_provider_cap: int = 1200,
) -> Dict[str, int]:
    """
    Distribui empresas por provider em uma onda.
    - baixa carga: equilibrado entre providers ativos
    - alta carga: preenche 1200 por provider em ordem, com resto no próximo
    """
    if total_items <= 0 or not providers:
        return {p: 0 for p in providers}

    if total_items < (per_provider_cap * 2):
        n = len(providers)
        base = total_items // n
        remainder = total_items % n
        return {
            p: base + (1 if idx < remainder else 0)
            for idx, p in enumerate(providers)
        }

    remaining = total_items
    allocation: Dict[str, int] = {}
    for provider in providers:
        take = min(per_provider_cap, remaining)
        allocation[provider] = take
        remaining -= take
    return allocation


def _classify_error_type(err: Any) -> str:
    if isinstance(err, BaseException):
        return type(err).__name__
    if not isinstance(err, str):
        return type(err).__name__

    low = err.lower()
    if "timeout" in low:
        return "TimeoutError"
    if "connect tunnel failed, response 522" in low or "http_status_522" in low:
        return "HTTP_522"
    if "http_status_403" in low:
        return "HTTP_403"
    if "http_status_5" in low:
        return "HTTP_5xx"
    if "ssl" in low or "tls" in low:
        return "SSLError"
    if "proxy" in low:
        return "ProxyError"
    if "connection reset" in low:
        return "ConnectionReset"
    return "ErrorString"


async def _process_scrape_main_page_background(request: ScrapeMainPageRequest):
    """Etapa 1: scrape da main page e persistência de raw_content/error."""
    try:
        await db_service.upsert_scrape_main_base(
            cnpj_basico=request.cnpj_basico,
            website_url=request.website_url,
        )

        final_url, status_code, raw_content, error = await scrape_main_page_raw(request.website_url)

        if error:
            detail = f"step1:{error} | status={status_code} | final_url={final_url}"
            await db_service.save_scrape_main_error(
                cnpj_basico=request.cnpj_basico,
                error=detail,
                step=1,
                website_url=final_url or request.website_url,
            )
            logger.warning(f"[BACKGROUND] scrape_main_page erro cnpj={request.cnpj_basico} detail={detail}")
            return

        await db_service.save_scrape_main_raw_content(
            cnpj_basico=request.cnpj_basico,
            raw_content=raw_content,
            website_url=final_url or request.website_url,
        )
        logger.info(
            f"[BACKGROUND] scrape_main_page concluido: cnpj={request.cnpj_basico}, "
            f"status={status_code}, raw_len={len(raw_content)}"
        )
    except Exception as e:
        logger.error(f"[BACKGROUND] Erro etapa1 scrape_main_page: {e}", exc_info=True)
        try:
            await db_service.save_scrape_main_error(
                cnpj_basico=request.cnpj_basico,
                error=f"step1:exception:{type(e).__name__}:{str(e)[:300]}",
                step=1,
                website_url=request.website_url,
            )
        except Exception:
            logger.error("[BACKGROUND] Falha adicional ao persistir erro da etapa1", exc_info=True)


async def _run_stage1_batch_background(request: ScrapeMainPageBatchRequest):
    """
    Batch etapa 1:
    - carrega da website_discovery somente empresas ausentes em scrape_main
    - processa em lotes concorrentes (batch_size)
    - persiste em lote a cada save_every
    """
    started_at = time.perf_counter()
    requested_total = request.total_samples
    batch_size = request.batch_size
    save_every = request.save_every
    timeout_seconds = request.timeout_seconds

    processed = 0
    after_id = 0
    pending_results: List[Dict[str, Any]] = []

    logger.info(
        "[BATCH-STEP1] Iniciado: total=%s batch_size=%s save_every=%s timeout=%ss | mode=provider_isolated",
        requested_total, batch_size, save_every, timeout_seconds,
    )

    await proxy_pool.preload()
    proxy_snapshot = proxy_pool.get_provider_proxy_snapshot()
    provider_order = ["711proxy", "decodo", "evomi"]
    provider_proxy_lists = {
        provider: proxy_snapshot.get(provider, [])
        for provider in provider_order
        if proxy_snapshot.get(provider)
    }
    active_providers = [p for p in provider_order if p in provider_proxy_lists]
    if not provider_proxy_lists:
        logger.error("[BATCH-STEP1] Nenhum proxy carregado para execução")
        return

    logger.info(
        "[BATCH-STEP1] Proxies carregados: 711=%s decodo=%s evomi=%s",
        len(provider_proxy_lists.get("711proxy", [])),
        len(provider_proxy_lists.get("decodo", [])),
        len(provider_proxy_lists.get("evomi", [])),
    )

    while processed < requested_total:
        remaining = requested_total - processed
        fetch_limit = min(5000, remaining)
        companies = await db_service.get_pending_scrape_main_step1_companies(
            limit=fetch_limit,
            after_id=after_id,
        )
        if not companies:
            break

        after_id = max(int(c["wd_id"]) for c in companies if c.get("wd_id") is not None)

        async def run_one(company: Dict[str, Any], proxy_url: str, proxy_provider: str) -> Dict[str, Any]:
            cnpj = company["cnpj_basico"]
            website_url = company["website_url"]
            final_url, status_code, raw_content, error = await scrape_main_page_raw(
                website_url,
                timeout=timeout_seconds,
                proxy=proxy_url,
            )
            if error:
                return {
                    "cnpj_basico": cnpj,
                    "website_url": final_url or website_url,
                    "raw_content": None,
                    "num_char_raw_main": 0,
                    "error_step1": (
                        f"step1:{error} | status={status_code} | final_url={final_url} "
                        f"| provider={proxy_provider}"
                    ),
                }
            return {
                "cnpj_basico": cnpj,
                "website_url": final_url or website_url,
                "raw_content": raw_content,
                "num_char_raw_main": len(raw_content or ""),
                "error_step1": None,
            }

        async def run_provider_slice(
            provider: str,
            company_slice: List[Dict[str, Any]],
            proxy_urls: List[str],
        ) -> List[Dict[str, Any]]:
            tasks = [
                run_one(company, proxy_urls[i % len(proxy_urls)], provider)
                for i, company in enumerate(company_slice)
            ]
            return await asyncio.gather(*tasks, return_exceptions=False)

        for chunk in _chunk_list(companies, batch_size):
            provider_capacity = 1200 * len(active_providers)
            for start_idx in range(0, len(chunk), provider_capacity):
                provider_window = chunk[start_idx:start_idx + provider_capacity]
                allocation = _allocate_provider_slices(
                    total_items=len(provider_window),
                    providers=active_providers,
                    per_provider_cap=1200,
                )

                cursor = 0
                provider_jobs = []
                for provider in active_providers:
                    take = allocation.get(provider, 0)
                    company_slice = provider_window[cursor:cursor + take]
                    cursor += take
                    if not company_slice:
                        continue

                    proxy_urls = provider_proxy_lists[provider]
                    provider_jobs.append(run_provider_slice(provider, company_slice, proxy_urls))

                if provider_jobs:
                    provider_results = await asyncio.gather(*provider_jobs, return_exceptions=False)
                    for results in provider_results:
                        pending_results.extend(results)

                while len(pending_results) >= save_every:
                    flush = pending_results[:save_every]
                    pending_results = pending_results[save_every:]
                    saved = await db_service.save_scrape_main_step1_batch(flush)
                    processed += saved
                    logger.info("[BATCH-STEP1] checkpoint: %s/%s", processed, requested_total)

                    if processed >= requested_total:
                        break

                if processed >= requested_total:
                    break

            if processed >= requested_total:
                break

    if pending_results and processed < requested_total:
        max_to_save = min(len(pending_results), requested_total - processed)
        saved = await db_service.save_scrape_main_step1_batch(pending_results[:max_to_save])
        processed += saved
        logger.info("[BATCH-STEP1] flush final: %s/%s", processed, requested_total)

    elapsed_s = round(time.perf_counter() - started_at, 2)
    logger.info(
        "[BATCH-STEP1] Concluído: processados=%s solicitados=%s elapsed_s=%s",
        processed,
        requested_total,
        elapsed_s,
    )


async def _run_unified_pipeline_for_company(
    run_id: str,
    company: Dict[str, Any],
    proxy_url: str,
    proxy_provider: str,
    timeout_seconds: int,
    redis_ttl_seconds: int,
    parse_executor: Optional[ProcessPoolExecutor] = None,
) -> Dict[str, Any]:
    pipeline_started = time.perf_counter()
    cnpj = company["cnpj_basico"]
    website_url = company["website_url"]
    base_result: Dict[str, Any] = {
        "cnpj_basico": cnpj,
        "website_url": website_url,
        "subpage_links": "",
        "num_subpages": 0,
        "mainpage_processada": "",
        "error_step1": None,
        "error_step2": None,
        "error_step3": None,
    }

    # step1: fetch main page
    stage = "step1"
    unified_inflight_requests.labels(provider=proxy_provider, stage=stage, run=run_id).inc()
    t0 = time.perf_counter()
    try:
        final_url, status_code, raw_content, error = await scrape_main_page_raw(
            website_url,
            timeout=timeout_seconds,
            proxy=proxy_url,
        )
        elapsed = time.perf_counter() - t0
        if error:
            base_result["website_url"] = final_url or website_url
            base_result["error_step1"] = (
                f"step1:{error} | status={status_code} | final_url={final_url} | provider={proxy_provider}"
            )
            observe_request(proxy_provider, stage, "error", elapsed, run=run_id)
            observe_error(proxy_provider, stage, _classify_error_type(error), run=run_id)
            observe_company_total(proxy_provider, "error_step1", time.perf_counter() - pipeline_started, run=run_id)
            return base_result

        await raw_content_cache.set_raw_content(
            run_id=run_id,
            cnpj_basico=cnpj,
            website_url=final_url or website_url,
            raw_content=raw_content,
            ttl_seconds=redis_ttl_seconds,
        )
        base_result["website_url"] = final_url or website_url
        observe_request(proxy_provider, stage, "success", elapsed, run=run_id)
    except Exception as e:
        elapsed = time.perf_counter() - t0
        base_result["error_step1"] = f"step1:exception:{type(e).__name__}:{str(e)[:300]} | provider={proxy_provider}"
        observe_request(proxy_provider, stage, "error", elapsed, run=run_id)
        observe_error(proxy_provider, stage, _classify_error_type(e), run=run_id)
        observe_company_total(proxy_provider, "error_step1", time.perf_counter() - pipeline_started, run=run_id)
        return base_result
    finally:
        unified_inflight_requests.labels(provider=proxy_provider, stage=stage, run=run_id).dec()

    # step2 + step3: single-pass parse de dados in-memory (sem Redis reads)
    base_url = base_result["website_url"]
    processed_text = ""
    links: list = []

    stage = "step2"
    unified_inflight_requests.labels(provider=proxy_provider, stage=stage, run=run_id).inc()
    t1 = time.perf_counter()
    try:
        loop = asyncio.get_running_loop()
        processed_text, links = await loop.run_in_executor(
            parse_executor, extract_text_and_links_from_raw, raw_content, base_url,
        )
        base_result["subpage_links"] = json.dumps(links, ensure_ascii=False)
        base_result["num_subpages"] = len(links)
        observe_request(proxy_provider, stage, "success", time.perf_counter() - t1, run=run_id)
    except Exception as e:
        base_result["error_step2"] = f"step2:exception:{type(e).__name__}:{str(e)[:300]}"
        observe_request(proxy_provider, stage, "error", time.perf_counter() - t1, run=run_id)
        observe_error(proxy_provider, stage, _classify_error_type(e), run=run_id)
    finally:
        unified_inflight_requests.labels(provider=proxy_provider, stage=stage, run=run_id).dec()

    stage = "step3"
    unified_inflight_requests.labels(provider=proxy_provider, stage=stage, run=run_id).inc()
    t2 = time.perf_counter()
    try:
        if not processed_text.strip():
            raise ValueError("não foi possível extrair texto útil")
        base_result["mainpage_processada"] = processed_text
        observe_request(proxy_provider, stage, "success", time.perf_counter() - t2, run=run_id)
    except Exception as e:
        base_result["error_step3"] = f"step3:exception:{type(e).__name__}:{str(e)[:300]}"
        observe_request(proxy_provider, stage, "error", time.perf_counter() - t2, run=run_id)
        observe_error(proxy_provider, stage, _classify_error_type(e), run=run_id)
    finally:
        unified_inflight_requests.labels(provider=proxy_provider, stage=stage, run=run_id).dec()
        try:
            await raw_content_cache.delete_raw_content(run_id=run_id, cnpj_basico=cnpj)
        except Exception:
            pass

    if base_result["error_step3"]:
        final_status = "error_step3"
    elif base_result["error_step2"]:
        final_status = "error_step2"
    else:
        final_status = "success"
    observe_company_total(proxy_provider, final_status, time.perf_counter() - pipeline_started, run=run_id)
    return base_result


async def _run_unified_batch_background(request: ScrapeMainUnifiedBatchRequest, run_id: str):
    requested_total = request.total_samples
    batch_size = request.batch_size
    save_every = request.save_every
    save_mode = (request.save_mode or "checkpoint").strip().lower()
    save_in_batches = request.save_in_batches
    timeout_seconds = request.timeout_seconds
    redis_ttl_seconds = request.redis_ttl_seconds
    parse_workers = request.parse_workers

    completed = 0
    persisted = 0
    after_id = 0
    pending_results: List[Dict[str, Any]] = []
    started_at = time.perf_counter()

    if save_mode not in {"checkpoint", "final_only"}:
        logger.warning(
            "[BATCH-UNIFIED] run_id=%s save_mode inválido '%s', usando 'checkpoint'",
            run_id,
            save_mode,
        )
        save_mode = "checkpoint"

    unified_parse_workers.labels(run=run_id).set(parse_workers)
    logger.info(
        "[BATCH-UNIFIED] Iniciado run_id=%s total=%s batch_size=%s save_mode=%s save_every=%s save_in_batches=%s timeout=%ss redis_ttl=%ss parse_workers=%s",
        run_id, requested_total, batch_size, save_mode, save_every, save_in_batches, timeout_seconds, redis_ttl_seconds, parse_workers,
    )

    await proxy_pool.preload()
    proxy_snapshot = proxy_pool.get_provider_proxy_snapshot()
    provider_order = ["711proxy", "decodo", "evomi"]
    provider_proxy_lists = {
        provider: proxy_snapshot.get(provider, [])
        for provider in provider_order
        if proxy_snapshot.get(provider)
    }
    active_providers = [p for p in provider_order if p in provider_proxy_lists]
    if not active_providers:
        logger.error("[BATCH-UNIFIED] run_id=%s nenhum proxy carregado", run_id)
        observe_batch_run(
            save_mode=save_mode,
            status="no_providers",
            elapsed_s=time.perf_counter() - started_at,
            run=run_id,
        )
        return

    batch_status = "success"
    parse_executor = ProcessPoolExecutor(max_workers=parse_workers)
    try:
        while completed < requested_total:
            remaining = requested_total - completed
            fetch_limit = min(5000, remaining)
            load_t0 = time.perf_counter()
            companies = await db_service.get_pending_scrape_main_unified_companies(
                limit=fetch_limit,
                after_id=after_id,
            )
            observe_company_load(
                time.perf_counter() - load_t0,
                len(companies) if companies else 0,
                run=run_id,
            )
            if not companies:
                break

            after_id = max(int(c["wd_id"]) for c in companies if c.get("wd_id") is not None)
            unified_queue_depth.labels(stage="unified_batch", run=run_id).set(len(companies))

            for chunk in _chunk_list(companies, batch_size):
                provider_capacity = 1200 * len(active_providers)
                for start_idx in range(0, len(chunk), provider_capacity):
                    provider_window = chunk[start_idx:start_idx + provider_capacity]
                    allocation = _allocate_provider_slices(
                        total_items=len(provider_window),
                        providers=active_providers,
                        per_provider_cap=1200,
                    )

                    cursor = 0
                    provider_jobs = []
                    for provider in active_providers:
                        take = allocation.get(provider, 0)
                        company_slice = provider_window[cursor:cursor + take]
                        cursor += take
                        if not company_slice:
                            continue
                        proxy_urls = provider_proxy_lists[provider]
                        tasks = [
                            _run_unified_pipeline_for_company(
                                run_id=run_id,
                                company=company,
                                proxy_url=proxy_urls[i % len(proxy_urls)],
                                proxy_provider=provider,
                                timeout_seconds=timeout_seconds,
                                redis_ttl_seconds=redis_ttl_seconds,
                                parse_executor=parse_executor,
                            )
                            for i, company in enumerate(company_slice)
                        ]
                        provider_jobs.append(asyncio.gather(*tasks, return_exceptions=False))

                    if provider_jobs:
                        provider_results = await asyncio.gather(*provider_jobs, return_exceptions=False)
                        for result_list in provider_results:
                            pending_results.extend(result_list)
                            completed += len(result_list)
                        unified_pending_results_depth.labels(mode=save_mode, run=run_id).set(len(pending_results))

                    if save_mode == "checkpoint":
                        while len(pending_results) >= save_every:
                            flush = pending_results[:save_every]
                            pending_results = pending_results[save_every:]
                            flush_started = time.perf_counter()
                            saved = await db_service.save_scrape_main_unified_batch(flush)
                            observe_batch_flush(
                                save_mode=save_mode,
                                records=saved,
                                elapsed_s=time.perf_counter() - flush_started,
                                run=run_id,
                            )
                            persisted += saved
                            unified_pending_results_depth.labels(mode=save_mode, run=run_id).set(len(pending_results))
                            logger.info(
                                "[BATCH-UNIFIED] run_id=%s checkpoint: persisted=%s completed=%s/%s",
                                run_id,
                                persisted,
                                completed,
                                requested_total,
                            )

                    if completed >= requested_total:
                        break
                if completed >= requested_total:
                    break

        if pending_results:
            flush_size = save_in_batches if save_mode == "final_only" else save_every
            while pending_results:
                flush = pending_results[:flush_size]
                pending_results = pending_results[flush_size:]
                flush_started = time.perf_counter()
                saved = await db_service.save_scrape_main_unified_batch(flush)
                observe_batch_flush(
                    save_mode=save_mode,
                    records=saved,
                    elapsed_s=time.perf_counter() - flush_started,
                    run=run_id,
                )
                persisted += saved
                unified_pending_results_depth.labels(mode=save_mode, run=run_id).set(len(pending_results))
                logger.info(
                    "[BATCH-UNIFIED] run_id=%s flush final: persisted=%s completed=%s/%s",
                    run_id,
                    persisted,
                    completed,
                    requested_total,
                )
    except Exception as e:
        batch_status = "error"
        logger.error("[BATCH-UNIFIED] run_id=%s erro fatal: %s", run_id, e, exc_info=True)
    finally:
        parse_executor.shutdown(wait=False)
        unified_queue_depth.labels(stage="unified_batch", run=run_id).set(0)
        unified_pending_results_depth.labels(mode=save_mode, run=run_id).set(0)
        elapsed_s = round(time.perf_counter() - started_at, 2)
        observe_batch_run(save_mode=save_mode, status=batch_status, elapsed_s=elapsed_s, run=run_id)
        logger.info(
            "[BATCH-UNIFIED] run_id=%s concluído completed=%s persisted=%s/%s elapsed_s=%s parse_workers=%s",
            run_id,
            completed,
            persisted,
            requested_total,
            elapsed_s,
            parse_workers,
        )


async def _process_unified_single_background(request: ScrapeMainUnifiedRequest, run_id: str):
    company = {"cnpj_basico": request.cnpj_basico, "website_url": request.website_url}
    await proxy_pool.preload()
    snapshot = proxy_pool.get_provider_proxy_snapshot()
    provider_order = ["711proxy", "decodo", "evomi"]
    active = [p for p in provider_order if snapshot.get(p)]
    if not active:
        await db_service.save_scrape_main_unified_batch(
            [{
                "cnpj_basico": request.cnpj_basico,
                "website_url": request.website_url,
                "subpage_links": "",
                "num_subpages": 0,
                "mainpage_processada": "",
                "error_step1": "step1:exception:RuntimeError:nenhum provider carregado",
                "error_step2": None,
                "error_step3": None,
            }]
        )
        return

    provider = active[0]
    proxy_url = snapshot[provider][0]
    result = await _run_unified_pipeline_for_company(
        run_id=run_id,
        company=company,
        proxy_url=proxy_url,
        proxy_provider=provider,
        timeout_seconds=request.timeout_seconds,
        redis_ttl_seconds=request.redis_ttl_seconds,
    )
    await db_service.save_scrape_main_unified_batch([result])


async def _process_extract_subpage_links_background(request: ScrapeMainPageProcessRequest):
    """Etapa 2: lê raw_content e salva links de subpágina."""
    try:
        record = await db_service.get_scrape_main(request.cnpj_basico)
        if not record:
            raise ValueError("registro scrape_main não encontrado para o CNPJ informado")

        raw_content = (record.get("raw_content") or "").strip()
        website_url = (record.get("website_url") or "").strip()
        if not raw_content:
            raise ValueError("raw_content vazio; execute a etapa 1 antes da etapa 2")
        if not website_url:
            raise ValueError("website_url ausente no registro scrape_main")

        links = extract_subpage_links_from_raw(raw_content, website_url)
        serialized_links = json.dumps(links, ensure_ascii=False)
        num_subpages = len(links)
        await db_service.save_scrape_main_subpage_links(
            request.cnpj_basico,
            serialized_links,
            num_subpages,
        )
        logger.info(
            f"[BACKGROUND] extrair_subpage_links concluido: cnpj={request.cnpj_basico}, "
            f"links={num_subpages}"
        )
    except Exception as e:
        logger.error(f"[BACKGROUND] Erro etapa2 extrair_subpage_links: {e}", exc_info=True)
        await db_service.save_scrape_main_error(
            cnpj_basico=request.cnpj_basico,
            error=f"step2:exception:{type(e).__name__}:{str(e)[:300]}",
            step=2,
        )


async def _run_step2_batch_background(request: ScrapeMainBatchRequest):
    """
    Batch etapa 2:
    - lê scrape_main com raw_content
    - extrai links em lotes concorrentes (batch_size)
    - salva sucessos/erros no banco a cada save_every
    """
    requested_total = request.total_samples
    batch_size = request.batch_size
    save_every = request.save_every

    processed = 0
    after_id = 0
    success_buffer: List[Dict[str, Any]] = []
    error_buffer: List[Dict[str, Any]] = []

    logger.info(
        "[BATCH-STEP2] Iniciado: total=%s batch_size=%s save_every=%s",
        requested_total, batch_size, save_every,
    )

    while processed < requested_total:
        remaining = requested_total - processed
        fetch_limit = min(5000, remaining)
        rows = await db_service.get_pending_scrape_main_step2(limit=fetch_limit, after_id=after_id)
        if not rows:
            break

        after_id = max(int(r["id"]) for r in rows if r.get("id") is not None)

        async def run_one(row: Dict[str, Any]) -> Dict[str, Any]:
            cnpj = row["cnpj_basico"]
            raw_content = (row.get("raw_content") or "").strip()
            website_url = (row.get("website_url") or "").strip()
            try:
                if not raw_content:
                    raise ValueError("raw_content vazio na etapa 2")
                if not website_url:
                    raise ValueError("website_url vazio na etapa 2")

                links = extract_subpage_links_from_raw(raw_content, website_url)
                return {
                    "ok": True,
                    "cnpj_basico": cnpj,
                    "subpage_links": json.dumps(links, ensure_ascii=False),
                    "num_subpages": len(links),
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "cnpj_basico": cnpj,
                    "error_step2": f"step2:exception:{type(exc).__name__}:{str(exc)[:300]}",
                }

        for chunk in _chunk_list(rows, batch_size):
            results = await asyncio.gather(*[run_one(r) for r in chunk], return_exceptions=False)
            for result in results:
                if result["ok"]:
                    success_buffer.append(result)
                else:
                    error_buffer.append(result)

            while (len(success_buffer) + len(error_buffer)) >= save_every:
                take_n = save_every
                flush_ok: List[Dict[str, Any]] = []
                flush_err: List[Dict[str, Any]] = []

                while take_n > 0 and success_buffer:
                    flush_ok.append(success_buffer.pop(0))
                    take_n -= 1
                while take_n > 0 and error_buffer:
                    flush_err.append(error_buffer.pop(0))
                    take_n -= 1

                saved = await db_service.save_scrape_main_step2_batch(flush_ok, flush_err)
                processed += saved
                logger.info("[BATCH-STEP2] checkpoint: %s/%s", processed, requested_total)
                if processed >= requested_total:
                    break

            if processed >= requested_total:
                break

    if processed < requested_total and (success_buffer or error_buffer):
        max_to_save = requested_total - processed
        flush_ok: List[Dict[str, Any]] = []
        flush_err: List[Dict[str, Any]] = []
        for item in success_buffer:
            if len(flush_ok) + len(flush_err) >= max_to_save:
                break
            flush_ok.append(item)
        for item in error_buffer:
            if len(flush_ok) + len(flush_err) >= max_to_save:
                break
            flush_err.append(item)
        saved = await db_service.save_scrape_main_step2_batch(flush_ok, flush_err)
        processed += saved
        logger.info("[BATCH-STEP2] flush final: %s/%s", processed, requested_total)

    logger.info("[BATCH-STEP2] Concluído: processados=%s solicitados=%s", processed, requested_total)


async def _process_mainpage_text_background(request: ScrapeMainPageProcessRequest):
    """Etapa 3: lê raw_content e salva texto processado da main page."""
    try:
        record = await db_service.get_scrape_main(request.cnpj_basico)
        if not record:
            raise ValueError("registro scrape_main não encontrado para o CNPJ informado")

        raw_content = (record.get("raw_content") or "").strip()
        website_url = (record.get("website_url") or "").strip()
        if not raw_content:
            raise ValueError("raw_content vazio; execute a etapa 1 antes da etapa 3")
        if not website_url:
            raise ValueError("website_url ausente no registro scrape_main")

        processed_text = extract_mainpage_text_from_raw(raw_content, website_url)
        if not processed_text.strip():
            raise ValueError("não foi possível extrair texto útil de raw_content")

        await db_service.save_scrape_main_processed_text(request.cnpj_basico, processed_text)
        logger.info(
            f"[BACKGROUND] processar_mainpage_texto concluido: cnpj={request.cnpj_basico}, "
            f"text_len={len(processed_text)}"
        )
    except Exception as e:
        logger.error(f"[BACKGROUND] Erro etapa3 processar_mainpage_texto: {e}", exc_info=True)
        await db_service.save_scrape_main_error(
            cnpj_basico=request.cnpj_basico,
            error=f"step3:exception:{type(e).__name__}:{str(e)[:300]}",
            step=3,
        )


async def _run_step3_batch_background(request: ScrapeMainBatchRequest):
    """
    Batch etapa 3:
    - lê scrape_main com raw_content
    - processa texto em lotes concorrentes (batch_size)
    - salva sucessos/erros no banco a cada save_every
    """
    requested_total = request.total_samples
    batch_size = request.batch_size
    save_every = request.save_every

    processed = 0
    after_id = 0
    success_buffer: List[Dict[str, Any]] = []
    error_buffer: List[Dict[str, Any]] = []

    logger.info(
        "[BATCH-STEP3] Iniciado: total=%s batch_size=%s save_every=%s",
        requested_total, batch_size, save_every,
    )

    while processed < requested_total:
        remaining = requested_total - processed
        fetch_limit = min(5000, remaining)
        rows = await db_service.get_pending_scrape_main_step3(limit=fetch_limit, after_id=after_id)
        if not rows:
            break

        after_id = max(int(r["id"]) for r in rows if r.get("id") is not None)

        async def run_one(row: Dict[str, Any]) -> Dict[str, Any]:
            cnpj = row["cnpj_basico"]
            raw_content = (row.get("raw_content") or "").strip()
            website_url = (row.get("website_url") or "").strip()
            try:
                if not raw_content:
                    raise ValueError("raw_content vazio na etapa 3")
                if not website_url:
                    raise ValueError("website_url vazio na etapa 3")

                processed_text = extract_mainpage_text_from_raw(raw_content, website_url)
                if not processed_text.strip():
                    raise ValueError("não foi possível extrair texto útil")

                return {
                    "ok": True,
                    "cnpj_basico": cnpj,
                    "mainpage_processada": processed_text,
                    "num_char_main_processada": len(processed_text),
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "cnpj_basico": cnpj,
                    "error_step3": f"step3:exception:{type(exc).__name__}:{str(exc)[:300]}",
                }

        for chunk in _chunk_list(rows, batch_size):
            results = await asyncio.gather(*[run_one(r) for r in chunk], return_exceptions=False)
            for result in results:
                if result["ok"]:
                    success_buffer.append(result)
                else:
                    error_buffer.append(result)

            while (len(success_buffer) + len(error_buffer)) >= save_every:
                take_n = save_every
                flush_ok: List[Dict[str, Any]] = []
                flush_err: List[Dict[str, Any]] = []

                while take_n > 0 and success_buffer:
                    flush_ok.append(success_buffer.pop(0))
                    take_n -= 1
                while take_n > 0 and error_buffer:
                    flush_err.append(error_buffer.pop(0))
                    take_n -= 1

                saved = await db_service.save_scrape_main_step3_batch(flush_ok, flush_err)
                processed += saved
                logger.info("[BATCH-STEP3] checkpoint: %s/%s", processed, requested_total)
                if processed >= requested_total:
                    break

            if processed >= requested_total:
                break

    if processed < requested_total and (success_buffer or error_buffer):
        max_to_save = requested_total - processed
        flush_ok: List[Dict[str, Any]] = []
        flush_err: List[Dict[str, Any]] = []
        for item in success_buffer:
            if len(flush_ok) + len(flush_err) >= max_to_save:
                break
            flush_ok.append(item)
        for item in error_buffer:
            if len(flush_ok) + len(flush_err) >= max_to_save:
                break
            flush_err.append(item)
        saved = await db_service.save_scrape_main_step3_batch(flush_ok, flush_err)
        processed += saved
        logger.info("[BATCH-STEP3] flush final: %s/%s", processed, requested_total)

    logger.info("[BATCH-STEP3] Concluído: processados=%s solicitados=%s", processed, requested_total)


async def _process_scrape_background(request: ScrapeRequest):
    """Processa scraping em background."""
    try:
        logger.info(f"[BACKGROUND] Scrape: cnpj={request.cnpj_basico}, url={request.website_url}")

        result = await scrape_all_subpages(
            url=request.website_url, max_subpages=5,
            ctx_label="", request_id="",
        )
        pages = result.pages

        if not pages:
            logger.warning(f"[BACKGROUND] Nenhuma pagina scraped para cnpj={request.cnpj_basico}")
            return

        successful_pages = [page for page in pages if page.success]
        if not successful_pages:
            logger.warning(f"[BACKGROUND] Nenhuma pagina com conteudo para cnpj={request.cnpj_basico}")
            return

        aggregated_content_parts = []
        visited_urls = []
        for page in successful_pages:
            aggregated_content_parts.append(
                f"--- PAGE START: {page.url} ---\n{page.content}\n--- PAGE END ---"
            )
            visited_urls.append(page.url)

        aggregated_content = "\n\n".join(aggregated_content_parts)
        if not aggregated_content or len(aggregated_content.strip()) < 100:
            logger.warning(f"[BACKGROUND] Conteudo insuficiente para cnpj={request.cnpj_basico}")
            return

        chunks = process_content(aggregated_content)
        if not chunks:
            logger.warning(f"[BACKGROUND] Nenhum chunk gerado para cnpj={request.cnpj_basico}")
            return

        for chunk in chunks:
            if not hasattr(chunk, 'pages_included') or not chunk.pages_included:
                chunk.pages_included = visited_urls[:5]

        discovery_id = None
        try:
            discovery = await db_service.get_discovery(request.cnpj_basico)
            if discovery:
                discovery_id = discovery.get('id')
        except Exception as e:
            logger.warning(f"[BACKGROUND] Erro ao buscar discovery: {e}")

        chunks_saved = await db_service.save_chunks_batch(
            cnpj_basico=request.cnpj_basico, chunks=chunks,
            website_url=request.website_url, discovery_id=discovery_id,
        )

        total_tokens = sum(chunk.tokens for chunk in chunks)
        logger.info(
            f"[BACKGROUND] Scrape concluido: cnpj={request.cnpj_basico}, "
            f"{chunks_saved} chunks, {total_tokens:,} tokens, {len(successful_pages)} paginas"
        )
    except Exception as e:
        logger.error(f"[BACKGROUND] Erro ao processar scrape: {e}", exc_info=True)


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_website(request: ScrapeRequest) -> ScrapeResponse:
    """
    Faz scraping do site oficial da empresa e salva chunks no banco de dados.
    Processamento assincrono: retorna imediatamente.
    """
    try:
        logger.info(f"Requisicao Scrape recebida: cnpj={request.cnpj_basico}, url={request.website_url}")
        asyncio.create_task(_process_scrape_background(request))
        return ScrapeResponse(
            success=True,
            message=f"Requisicao de scraping aceita para CNPJ {request.cnpj_basico}.",
            cnpj_basico=request.cnpj_basico,
            website_url=request.website_url,
            status="accepted",
        )
    except Exception as e:
        logger.error(f"Erro ao aceitar requisicao Scrape: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao aceitar requisicao: {str(e)}")


@router.post("/scrape/main-page", response_model=ScrapeMainPageResponse)
async def scrape_main_page(request: ScrapeMainPageRequest) -> ScrapeMainPageResponse:
    """
    Etapa 1: faz scrape da main page e salva raw_content/error em scrape_main.
    """
    try:
        logger.info(
            f"Requisicao scrape_main_page recebida: cnpj={request.cnpj_basico}, url={request.website_url}"
        )
        asyncio.create_task(_process_scrape_main_page_background(request))
        return ScrapeMainPageResponse(
            success=True,
            message=f"Etapa 1 aceita para CNPJ {request.cnpj_basico}.",
            cnpj_basico=request.cnpj_basico,
            status="accepted",
        )
    except Exception as e:
        logger.error(f"Erro ao aceitar requisicao da etapa 1: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao aceitar requisicao: {str(e)}")


@router.post("/scrape/main-page/unified", response_model=ScrapeMainUnifiedResponse)
async def scrape_main_page_unified(request: ScrapeMainUnifiedRequest) -> ScrapeMainUnifiedResponse:
    """
    Endpoint unificado single:
    step1 (fetch) -> step2 (links) -> step3 (texto), com raw temporário no Redis.
    """
    try:
        run_id = str(uuid.uuid4())
        asyncio.create_task(_process_unified_single_background(request, run_id=run_id))
        return ScrapeMainUnifiedResponse(
            success=True,
            status="accepted",
            stage="unified",
            message=f"Execução unificada aceita para CNPJ {request.cnpj_basico}.",
            run_id=run_id,
            cnpj_basico=request.cnpj_basico,
        )
    except Exception as e:
        logger.error("Erro ao aceitar requisição unificada single: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao aceitar requisição unificada: {str(e)}")


@router.post("/scrape/main-page/subpage-links", response_model=ScrapeMainPageResponse)
async def extract_subpage_links(request: ScrapeMainPageProcessRequest) -> ScrapeMainPageResponse:
    """
    Etapa 2: lê raw_content e salva subpage_links em scrape_main.
    """
    try:
        logger.info(f"Requisicao etapa 2 recebida: cnpj={request.cnpj_basico}")
        asyncio.create_task(_process_extract_subpage_links_background(request))
        return ScrapeMainPageResponse(
            success=True,
            message=f"Etapa 2 aceita para CNPJ {request.cnpj_basico}.",
            cnpj_basico=request.cnpj_basico,
            status="accepted",
        )
    except Exception as e:
        logger.error(f"Erro ao aceitar requisicao da etapa 2: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao aceitar requisicao: {str(e)}")


@router.post("/scrape/main-page/process-text", response_model=ScrapeMainPageResponse)
async def process_mainpage_text(request: ScrapeMainPageProcessRequest) -> ScrapeMainPageResponse:
    """
    Etapa 3: lê raw_content e salva mainpage_processada em scrape_main.
    """
    try:
        logger.info(f"Requisicao etapa 3 recebida: cnpj={request.cnpj_basico}")
        asyncio.create_task(_process_mainpage_text_background(request))
        return ScrapeMainPageResponse(
            success=True,
            message=f"Etapa 3 aceita para CNPJ {request.cnpj_basico}.",
            cnpj_basico=request.cnpj_basico,
            status="accepted",
        )
    except Exception as e:
        logger.error(f"Erro ao aceitar requisicao da etapa 3: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao aceitar requisicao: {str(e)}")


@router.post("/scrape/main-page/batch", response_model=ScrapeMainBatchResponse)
async def scrape_main_page_batch(request: ScrapeMainPageBatchRequest) -> ScrapeMainBatchResponse:
    """
    Etapa 1 batch:
    - source: website_discovery ausente em scrape_main
    - concorrência por lote: batch_size
    - checkpoint de persistência: save_every
    """
    try:
        asyncio.create_task(_run_stage1_batch_background(request))
        return ScrapeMainBatchResponse(
            success=True,
            status="accepted",
            stage="step1",
            total_samples=request.total_samples,
            batch_size=request.batch_size,
            save_every=request.save_every,
            message="Batch etapa 1 aceito para processamento em background.",
        )
    except Exception as e:
        logger.error(f"Erro ao aceitar batch da etapa 1: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao aceitar batch: {str(e)}")


@router.post("/scrape/main-page/unified/batch", response_model=ScrapeMainUnifiedBatchResponse)
async def scrape_main_page_unified_batch(
    request: ScrapeMainUnifiedBatchRequest,
) -> ScrapeMainUnifiedBatchResponse:
    """
    Endpoint unificado batch:
    source: website_discovery ausente em scrape_main.
    """
    try:
        run_id = str(uuid.uuid4())
        asyncio.create_task(_run_unified_batch_background(request=request, run_id=run_id))
        return ScrapeMainUnifiedBatchResponse(
            success=True,
            status="accepted",
            stage="unified",
            total_samples=request.total_samples,
            batch_size=request.batch_size,
            save_every=request.save_every,
            run_id=run_id,
            message="Batch unificado aceito para processamento em background.",
        )
    except Exception as e:
        logger.error("Erro ao aceitar batch unificado: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao aceitar batch unificado: {str(e)}")


@router.post("/scrape/main-page/subpage-links/batch", response_model=ScrapeMainBatchResponse)
async def scrape_step2_batch(request: ScrapeMainBatchRequest) -> ScrapeMainBatchResponse:
    """
    Etapa 2 batch:
    - source: scrape_main com raw_content disponível e subpage_links vazio
    """
    try:
        asyncio.create_task(_run_step2_batch_background(request))
        return ScrapeMainBatchResponse(
            success=True,
            status="accepted",
            stage="step2",
            total_samples=request.total_samples,
            batch_size=request.batch_size,
            save_every=request.save_every,
            message="Batch etapa 2 aceito para processamento em background.",
        )
    except Exception as e:
        logger.error(f"Erro ao aceitar batch da etapa 2: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao aceitar batch: {str(e)}")


@router.post("/scrape/main-page/process-text/batch", response_model=ScrapeMainBatchResponse)
async def scrape_step3_batch(request: ScrapeMainBatchRequest) -> ScrapeMainBatchResponse:
    """
    Etapa 3 batch:
    - source: scrape_main com raw_content disponível e mainpage_processada vazio
    """
    try:
        asyncio.create_task(_run_step3_batch_background(request))
        return ScrapeMainBatchResponse(
            success=True,
            status="accepted",
            stage="step3",
            total_samples=request.total_samples,
            batch_size=request.batch_size,
            save_every=request.save_every,
            message="Batch etapa 3 aceito para processamento em background.",
        )
    except Exception as e:
        logger.error(f"Erro ao aceitar batch da etapa 3: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao aceitar batch: {str(e)}")


@router.get("/scrape/diagnose")
async def diagnose_scrape(url: str = Query(..., description="URL do site para diagnosticar")):
    """
    Diagnostico do pipeline de scraping para um site.
    Retorna cada fase com detalhes para identificar gargalos.
    """
    from app.services.scraper.url_prober import fast_probe_and_scrape, URLNotReachable
    from app.services.scraper.html_parser import is_cloudflare_challenge, is_soft_404
    from app.services.scraper.link_selector import filter_non_html_links, prioritize_links
    from app.services.scraper.constants import HIGH_PRIORITY_KEYWORDS, LOW_PRIORITY_KEYWORDS
    from app.services.scraper.http_client import cffi_scrape_safe

    diag = {"url_original": url, "phases": {}}

    # 1. PROBE + MAIN PAGE (fundidos)
    try:
        t0 = time.perf_counter()
        best_url, text, docs, links, probe_time = await fast_probe_and_scrape(url)
        duration = round((time.perf_counter() - t0) * 1000)

        content_ok = bool(text) and len(text) >= 100
        is_cf = is_cloudflare_challenge(text) if text else False
        is_404 = is_soft_404(text) if text else False

        diag["phases"]["probe_and_main"] = {
            "duration_ms": duration,
            "best_url": best_url,
            "content_length": len(text) if text else 0,
            "content_ok": content_ok and not is_cf and not is_404,
            "cloudflare": is_cf,
            "soft_404": is_404,
            "links_found": len(links),
        }
        url = best_url
    except URLNotReachable as e:
        diag["phases"]["probe_and_main"] = {"error": e.get_log_message()}
        diag["conclusion"] = "URL inacessivel"
        return diag
    except Exception as e:
        diag["phases"]["probe_and_main"] = {"error": str(e)}
        diag["conclusion"] = "Erro inesperado"
        return diag

    if not content_ok or is_cf or is_404:
        diag["conclusion"] = "Main page sem conteudo util"
        return diag

    # 2. FILTER + PRIORITIZE LINKS
    filtered = filter_non_html_links(links)
    diag["phases"]["filter_non_html"] = {
        "before": len(links), "after": len(filtered),
        "removed": len(links) - len(filtered),
    }

    scored = []
    for link in filtered:
        link_clean = link.strip().rstrip(',')
        if not link_clean or link_clean.rstrip('/') == url.rstrip('/'):
            continue
        score = 0
        lower = link_clean.lower()
        if any(k in lower for k in LOW_PRIORITY_KEYWORDS):
            score -= 100
        if any(k in lower for k in HIGH_PRIORITY_KEYWORDS):
            score += 50
        score -= len(urlparse(link_clean).path.split('/'))
        scored.append({"url": link_clean, "score": score})

    scored.sort(key=lambda x: -x["score"])
    accepted = [s for s in scored if s["score"] > -80]

    diag["phases"]["prioritize_links"] = {
        "total_scored": len(scored),
        "accepted": len(accepted),
        "top_10": accepted[:10],
    }

    # 3. TEST SUBPAGES
    if accepted:
        target_urls = [s["url"] for s in accepted[:5]]
        subpage_results = []
        for sub_url in target_urls:
            t0 = time.perf_counter()
            try:
                sub_text, sub_docs, _ = await cffi_scrape_safe(sub_url)
                dur = round((time.perf_counter() - t0) * 1000)
                last_err = cffi_scrape_safe.last_error
                subpage_results.append({
                    "url": sub_url,
                    "success": bool(sub_text) and len(sub_text) >= 100,
                    "content_length": len(sub_text) if sub_text else 0,
                    "error": last_err,
                    "duration_ms": dur,
                })
            except Exception as e:
                subpage_results.append({
                    "url": sub_url, "success": False, "error": str(e),
                    "duration_ms": round((time.perf_counter() - t0) * 1000),
                })
        diag["phases"]["subpage_test"] = subpage_results

    total_links = len(links)
    if total_links == 0:
        diag["conclusion"] = "ZERO links internos. Provavel site JS-rendered (Wix, React SPA)."
    elif len(accepted) == 0:
        diag["conclusion"] = f"{total_links} links encontrados mas todos de baixa prioridade."
    else:
        ok_sub = sum(1 for s in diag.get("phases", {}).get("subpage_test", []) if s.get("success"))
        diag["conclusion"] = f"{total_links} links, {len(accepted)} aceitos. Subpages: {ok_sub}/{min(5, len(accepted))} ok."

    return diag
