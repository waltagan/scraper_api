"""
Endpoint Scrape v2 - Scraping assíncrono de site com chunking e persistência.
Processamento em background - retorna imediatamente após aceitar requisição.
"""
import logging
import time
import asyncio
from typing import List
from fastapi import APIRouter, HTTPException
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

