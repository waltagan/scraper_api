"""
Endpoint Scrape v2 - Scraping assíncrono de site com chunking e persistência.
Processamento em background - retorna imediatamente após aceitar requisição.
"""
import logging
import time
import asyncio
from typing import List
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Query
from app.schemas.v2.scrape import ScrapeRequest, ScrapeResponse
from app.services.scraper import scrape_all_subpages
from app.services.scraper.models import ScrapedPage
from app.services.database_service import DatabaseService, get_db_service
from app.core.chunking import process_content

logger = logging.getLogger(__name__)

router = APIRouter()
db_service = get_db_service()


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
            logger.warning(f"[BACKGROUND] Nenhuma página scraped para cnpj={request.cnpj_basico}")
            return

        successful_pages = [page for page in pages if page.success]
        if not successful_pages:
            logger.warning(f"[BACKGROUND] Nenhuma página com conteúdo para cnpj={request.cnpj_basico}")
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
            logger.warning(f"[BACKGROUND] Conteúdo insuficiente para cnpj={request.cnpj_basico}")
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
            f"[BACKGROUND] Scrape concluído: cnpj={request.cnpj_basico}, "
            f"{chunks_saved} chunks, {total_tokens:,} tokens, {len(successful_pages)} páginas"
        )
    except Exception as e:
        logger.error(f"[BACKGROUND] Erro ao processar scrape: {e}", exc_info=True)


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_website(request: ScrapeRequest) -> ScrapeResponse:
    """
    Faz scraping do site oficial da empresa e salva chunks no banco de dados.
    Processamento assíncrono: retorna imediatamente.
    """
    try:
        logger.info(f"Requisição Scrape recebida: cnpj={request.cnpj_basico}, url={request.website_url}")
        asyncio.create_task(_process_scrape_background(request))
        return ScrapeResponse(
            success=True,
            message=f"Requisição de scraping aceita para CNPJ {request.cnpj_basico}.",
            cnpj_basico=request.cnpj_basico,
            website_url=request.website_url,
            status="accepted",
        )
    except Exception as e:
        logger.error(f"Erro ao aceitar requisição Scrape: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao aceitar requisição: {str(e)}")


@router.get("/scrape/diagnose")
async def diagnose_scrape(url: str = Query(..., description="URL do site para diagnosticar")):
    """
    Diagnóstico do pipeline de scraping para um site.
    Retorna cada fase com detalhes para identificar gargalos.
    """
    from app.services.scraper.url_prober import url_prober, URLNotReachable
    from app.services.scraper.html_parser import parse_html, extract_links
    from app.services.scraper.link_selector import filter_non_html_links, prioritize_links
    from app.services.scraper.constants import HIGH_PRIORITY_KEYWORDS, LOW_PRIORITY_KEYWORDS
    from app.services.scraper.scraper_service import _scrape_page_with_retry

    diag = {"url_original": url, "phases": {}}

    # 1. PROBE
    try:
        t0 = time.perf_counter()
        best_url, probe_time = await url_prober.probe(url)
        diag["phases"]["probe"] = {
            "duration_ms": round((time.perf_counter() - t0) * 1000),
            "best_url": best_url,
            "probe_time_ms": probe_time,
        }
        url = best_url
    except URLNotReachable as e:
        diag["phases"]["probe"] = {"error": e.get_log_message()}
        diag["conclusion"] = "URL inacessível"
        return diag
    except Exception as e:
        diag["phases"]["probe"] = {"error": str(e)}

    # 2. SCRAPE MAIN PAGE
    t0 = time.perf_counter()
    main_page = await _scrape_page_with_retry(url, "[DIAG] ")
    diag["phases"]["main_page"] = {
        "duration_ms": round((time.perf_counter() - t0) * 1000),
        "success": main_page.success if main_page else False,
        "status_code": main_page.status_code if main_page else None,
        "content_length": len(main_page.content) if main_page and main_page.content else 0,
        "error": main_page.error if main_page and not main_page.success else None,
        "links_found": len(main_page.links) if main_page else 0,
    }

    if not main_page or not main_page.success:
        diag["conclusion"] = "Falha ao obter main page"
        return diag

    # 3. PARSE + FILTER + PRIORITIZE
    links = set(main_page.links)
    filtered = filter_non_html_links(links)
    diag["phases"]["filter_non_html"] = {
        "before": len(links), "after": len(filtered),
        "removed": len(links - filtered),
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

    # 4. TEST SUBPAGES
    if accepted:
        target_urls = [s["url"] for s in accepted[:5]]
        subpage_results = []
        for sub_url in target_urls:
            t0 = time.perf_counter()
            try:
                page = await _scrape_page_with_retry(sub_url, "[DIAG] ")
                dur = round((time.perf_counter() - t0) * 1000)
                subpage_results.append({
                    "url": sub_url,
                    "success": page.success if page else False,
                    "content_length": len(page.content) if page and page.content else 0,
                    "error": page.error if page and not page.success else None,
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
        diag["conclusion"] = "ZERO links internos. Provável site JS-rendered (Wix, React SPA)."
    elif len(accepted) == 0:
        diag["conclusion"] = f"{total_links} links encontrados mas todos de baixa prioridade."
    else:
        ok_sub = sum(1 for s in diag.get("phases", {}).get("subpage_test", []) if s.get("success"))
        diag["conclusion"] = f"{total_links} links, {len(accepted)} aceitos. Subpages: {ok_sub}/{min(5, len(accepted))} ok."

    return diag
