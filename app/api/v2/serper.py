"""
Endpoint Serper v2 - Busca assíncrona no Google via Serper API.
Processamento em background - retorna imediatamente após aceitar requisição.
"""
import logging
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException
from app.schemas.v2.serper import SerperRequest, SerperResponse
from app.services.discovery_manager.serper_manager import serper_manager
from app.services.database_service import DatabaseService, get_db_service

logger = logging.getLogger(__name__)

router = APIRouter()
db_service = get_db_service()


def _build_search_query(
    razao_social: Optional[str],
    nome_fantasia: Optional[str],
    municipio: Optional[str]
) -> str:
    """
    Constrói query de busca otimizada.
    
    Prioridade:
    1. Nome Fantasia + Municipio
    2. Razão Social + Municipio (se nome fantasia não existir)
    
    Args:
        razao_social: Razão social da empresa
        nome_fantasia: Nome fantasia da empresa
        municipio: Município da empresa
    
    Returns:
        Query formatada para busca
    """
    nf = nome_fantasia.strip() if nome_fantasia else ""
    rs = razao_social.strip() if razao_social else ""
    city = municipio.strip() if municipio else ""
    
    # Prioridade 1: Nome Fantasia + Municipio
    if nf:
        query = f'{nf} {city} site oficial'.strip()
        return query
    
    # Prioridade 2: Razão Social + Municipio
    if rs:
        # Limpar sufixos comuns
        clean_rs = rs.replace(" LTDA", "").replace(" S.A.", "").replace(" EIRELI", "")
        clean_rs = clean_rs.replace(" ME", "").replace(" EPP", "").replace(" S/A", "").strip()
        if clean_rs:
            query = f'{clean_rs} {city} site oficial'.strip()
            return query
    
    # Fallback: apenas municipio (se existir)
    if city:
        return f'site oficial {city}'.strip()
    
    # Último fallback
    return "site oficial"


async def _process_serper_background(request: SerperRequest):
    """
    Processa busca Serper em background.
    """
    try:
        # 1. Construir query de busca
        query = _build_search_query(
            razao_social=request.razao_social,
            nome_fantasia=request.nome_fantasia,
            municipio=request.municipio
        )
        
        logger.info(f"🔍 [BACKGROUND] Serper busca: cnpj={request.cnpj_basico}, query='{query}'")
        
        # 2. Executar busca assíncrona via Serper
        results, retries = await serper_manager.search(
            query=query,
            num_results=10,
            country="br",
            language="pt-br",
            request_id=""
        )
        
        # 3. Salvar resultados no banco de dados
        serper_id = await db_service.save_serper_results(
            cnpj_basico=request.cnpj_basico,
            results=results or [],
            query_used=query,
            company_name=request.nome_fantasia or request.razao_social,
            razao_social=request.razao_social,
            nome_fantasia=request.nome_fantasia,
            municipio=request.municipio
        )
        
        logger.info(
            f"✅ [BACKGROUND] Serper busca concluída: cnpj={request.cnpj_basico}, "
            f"results={len(results) if results else 0}, serper_id={serper_id}"
        )
    except Exception as e:
        logger.error(f"❌ [BACKGROUND] Erro ao processar Serper: {e}", exc_info=True)


@router.post("/serper", response_model=SerperResponse)
async def buscar_serper(request: SerperRequest) -> SerperResponse:
    """
    Busca informações da empresa no Google via Serper API.
    
    Processamento assíncrono: retorna imediatamente após aceitar a requisição.
    O processamento (busca Serper e salvamento) ocorre em background.
    
    Args:
        request: Dados da empresa para busca (cnpj_basico, razao_social, nome_fantasia, municipio)
    
    Returns:
        SerperResponse com confirmação de recebimento da requisição
    
    Raises:
        HTTPException: Em caso de erro ao aceitar requisição
    """
    try:
        logger.info(f"📥 Requisição Serper recebida: cnpj={request.cnpj_basico}")
        
        # Iniciar processamento em background
        asyncio.create_task(_process_serper_background(request))
        
        # Retornar confirmação imediata
        return SerperResponse(
            success=True,
            message=f"Requisição de busca Serper aceita para CNPJ {request.cnpj_basico}. Processamento em background.",
            cnpj_basico=request.cnpj_basico,
            status="accepted"
        )
    
    except Exception as e:
        logger.error(f"❌ Erro ao aceitar requisição Serper: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao aceitar requisição: {str(e)}"
        )

