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
    """
    Processa scraping em background.
    """
    try:
        logger.info(f"🔍 [BACKGROUND] Scrape: cnpj={request.cnpj_basico}, url={request.website_url}")
        
        # 1. Fazer scraping de todas as subpáginas
        pages = await scrape_all_subpages(
            url=request.website_url,
            max_subpages=100,
            ctx_label="",
            request_id=""
        )
        
        if not pages:
            logger.warning(f"⚠️ [BACKGROUND] Nenhuma página scraped para cnpj={request.cnpj_basico}")
            return
        
        # Filtrar apenas páginas com sucesso
        successful_pages = [page for page in pages if page.success]
        pages_scraped = len(successful_pages)
        
        if pages_scraped == 0:
            logger.warning(f"⚠️ [BACKGROUND] Nenhuma página com conteúdo válido para cnpj={request.cnpj_basico}")
            return
        
        # 2. Agregar conteúdo de todas as páginas
        aggregated_content_parts = []
        visited_urls = []
        
        for page in successful_pages:
            aggregated_content_parts.append(
                f"--- PAGE START: {page.url} ---\n{page.content}\n--- PAGE END ---"
            )
            visited_urls.append(page.url)
        
        aggregated_content = "\n\n".join(aggregated_content_parts)
        
        if not aggregated_content or len(aggregated_content.strip()) < 100:
            logger.warning(f"⚠️ [BACKGROUND] Conteúdo agregado insuficiente para cnpj={request.cnpj_basico}")
            return
        
        # 3. Processar conteúdo em chunks
        chunks = process_content(aggregated_content)
        
        if not chunks:
            logger.warning(f"⚠️ [BACKGROUND] Nenhum chunk gerado para cnpj={request.cnpj_basico}")
            return
        
        # Adicionar informações de páginas aos chunks
        for chunk in chunks:
            if not hasattr(chunk, 'pages_included') or not chunk.pages_included:
                chunk.pages_included = visited_urls[:5]
        
        # 4. Buscar discovery_id do banco (opcional)
        discovery_id = None
        try:
            discovery = await db_service.get_discovery(request.cnpj_basico)
            if discovery:
                discovery_id = discovery.get('id')
        except Exception as e:
            logger.warning(f"⚠️ [BACKGROUND] Erro ao buscar discovery: {e}")
        
        # 5. Salvar chunks no banco
        chunks_saved = await db_service.save_chunks_batch(
            cnpj_basico=request.cnpj_basico,
            chunks=chunks,
            website_url=request.website_url,
            discovery_id=discovery_id
        )
        
        total_tokens = sum(chunk.tokens for chunk in chunks)
        
        logger.info(
            f"✅ [BACKGROUND] Scrape concluído: cnpj={request.cnpj_basico}, "
            f"{chunks_saved} chunks, {total_tokens:,} tokens, {pages_scraped} páginas"
        )
    except Exception as e:
        logger.error(f"❌ [BACKGROUND] Erro ao processar scrape: {e}", exc_info=True)


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_website(request: ScrapeRequest) -> ScrapeResponse:
    """
    Faz scraping do site oficial da empresa e salva chunks no banco de dados.
    
    Processamento assíncrono: retorna imediatamente após aceitar a requisição.
    O processamento (scraping, chunking e salvamento) ocorre em background.
    
    Args:
        request: CNPJ básico e URL do site
    
    Returns:
        ScrapeResponse com confirmação de recebimento da requisição
    
    Raises:
        HTTPException: Em caso de erro ao aceitar requisição
    """
    try:
        logger.info(f"📥 Requisição Scrape recebida: cnpj={request.cnpj_basico}, url={request.website_url}")
        
        # Iniciar processamento em background
        asyncio.create_task(_process_scrape_background(request))
        
        # Retornar confirmação imediata
        return ScrapeResponse(
            success=True,
            message=f"Requisição de scraping aceita para CNPJ {request.cnpj_basico}. Processamento em background.",
            cnpj_basico=request.cnpj_basico,
            website_url=request.website_url,
            status="accepted"
        )
    
    except Exception as e:
        logger.error(f"❌ Erro ao aceitar requisição Scrape: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao aceitar requisição: {str(e)}"
        )


@router.get("/scrape/diagnose")
async def diagnose_scrape(url: str = Query(..., description="URL do site para diagnosticar")):
    """
    Diagnóstico do pipeline de scraping para um site.
    Retorna cada fase com detalhes para identificar gargalos.
    """
    from app.services.scraper.site_analyzer import site_analyzer
    from app.services.scraper.url_prober import url_prober, URLNotReachable
    from app.services.scraper.strategy_selector import strategy_selector
    from app.services.scraper.html_parser import parse_html, extract_links
    from app.services.scraper.link_selector import filter_non_html_links, prioritize_links
    from app.services.scraper.constants import scraper_config, HIGH_PRIORITY_KEYWORDS, LOW_PRIORITY_KEYWORDS

    diag = {"url_original": url, "phases": {}}

    try:
        t0 = time.perf_counter()
        site_profile = await site_analyzer.analyze(url, ctx_label="[DIAG] ")
        diag["phases"]["analyze"] = {
            "duration_ms": round((time.perf_counter() - t0) * 1000),
            "status_code": site_profile.status_code,
            "protection": site_profile.protection_type.value if site_profile.protection_type else "none",
            "site_type": site_profile.site_type if hasattr(site_profile, "site_type") else "unknown",
            "response_time_ms": site_profile.response_time_ms,
            "has_raw_html": bool(site_profile.raw_html),
            "raw_html_length": len(site_profile.raw_html) if site_profile.raw_html else 0,
        }
    except Exception as e:
        diag["phases"]["analyze"] = {"error": str(e)}
        return diag

    if site_profile.raw_html:
        text, docs, links = parse_html(site_profile.raw_html, url)
        diag["phases"]["parse_html"] = {
            "text_length": len(text) if text else 0,
            "document_links": len(docs),
            "internal_links_raw": len(links),
            "sample_links": sorted(list(links))[:20],
        }
    else:
        used_probe = False
        try:
            best_url, probe_time = await url_prober.probe(url)
            diag["phases"]["probe_fallback"] = {
                "best_url": best_url, "probe_time_ms": probe_time
            }
            if best_url != url:
                url = best_url
                site_profile = await site_analyzer.analyze(url, ctx_label="[DIAG] ")
            if site_profile.raw_html:
                text, docs, links = parse_html(site_profile.raw_html, url)
                diag["phases"]["parse_html"] = {
                    "text_length": len(text) if text else 0,
                    "internal_links_raw": len(links),
                    "sample_links": sorted(list(links))[:20],
                }
                used_probe = True
        except Exception as e:
            diag["phases"]["probe_fallback"] = {"error": str(e)}

        if not used_probe:
            diag["conclusion"] = "Sem HTML obtido - site inacessível ou protegido"
            return diag

    filtered = filter_non_html_links(links)
    removed_by_filter = links - filtered
    diag["phases"]["filter_non_html"] = {
        "before": len(links),
        "after": len(filtered),
        "removed": len(removed_by_filter),
        "removed_sample": sorted(list(removed_by_filter))[:10],
    }

    base_domain = urlparse(url).netloc
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
    rejected = [s for s in scored if s["score"] <= -80]

    diag["phases"]["prioritize_links"] = {
        "total_scored": len(scored),
        "accepted": len(accepted),
        "rejected_by_score": len(rejected),
        "top_10_accepted": accepted[:10],
        "rejected_sample": rejected[:5],
    }

    strategies = strategy_selector.select(site_profile)
    diag["phases"]["strategy"] = {
        "selected": [s.value for s in strategies],
    }

    site_ms = site_profile.response_time_ms or 0
    slow = site_ms > scraper_config.slow_probe_threshold_ms
    cap = scraper_config.slow_subpage_cap if slow else 100
    diag["phases"]["performance"] = {
        "site_response_ms": site_ms,
        "slow_mode": slow,
        "subpage_cap": cap,
    }

    if accepted:
        target_urls = [s["url"] for s in accepted[:5]]
        subpage_results = []
        from app.services.scraper.scraper_service import _scrape_main_page
        for sub_url in target_urls:
            t0 = time.perf_counter()
            try:
                page = await _scrape_main_page(sub_url, strategies, site_profile, "[DIAG] ", "diag")
                dur = round((time.perf_counter() - t0) * 1000)
                subpage_results.append({
                    "url": sub_url,
                    "success": page.success if page else False,
                    "status_code": page.status_code if page else None,
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

    total_links_raw = diag["phases"].get("parse_html", {}).get("internal_links_raw", 0)
    accepted_count = len(accepted)
    if total_links_raw == 0:
        diag["conclusion"] = (
            "ZERO links internos no HTML estático. "
            "Provável site JS-rendered (Wix, React SPA, etc). "
            "curl_cffi não executa JavaScript."
        )
    elif accepted_count == 0:
        diag["conclusion"] = (
            f"{total_links_raw} links encontrados mas todos eliminados por filtro/score. "
            "Links são de baixa prioridade (blog, login, cart, policy)."
        )
    elif accepted_count > 0:
        ok_sub = sum(1 for s in diag.get("phases", {}).get("subpage_test", []) if s.get("success"))
        diag["conclusion"] = (
            f"{total_links_raw} links encontrados, {accepted_count} aceitos. "
            f"Teste de subpages: {ok_sub}/{min(5, accepted_count)} sucesso."
        )

    return diag

