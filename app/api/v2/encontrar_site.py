"""
Endpoint Encontrar Site v2 - Descoberta assíncrona de site oficial via LLM.
"""
import logging
from typing import Optional, List, Dict
from fastapi import APIRouter, HTTPException
from app.schemas.v2.discovery import DiscoveryRequest, DiscoveryResponse
from app.services.database_service import DatabaseService, get_db_service
from app.services.agents.discovery_agent import get_discovery_agent
from app.core.phoenix_tracer import trace_llm_call
from app.services.discovery.discovery_service import _filter_search_results, is_blacklisted_domain

logger = logging.getLogger(__name__)

router = APIRouter()
db_service = get_db_service()


@router.post("/encontrar_site", response_model=DiscoveryResponse)
async def encontrar_site(request: DiscoveryRequest) -> DiscoveryResponse:
    """
    Encontra o site oficial da empresa usando LLM para analisar resultados Serper.
    
    Fluxo:
    1. Busca resultados Serper salvos no banco de dados
    2. Extrai dados da empresa e resultados de busca
    3. Filtra resultados (remove blacklist)
    4. Usa DiscoveryAgent com Phoenix tracing para identificar site oficial
    5. Salva resultado da descoberta no banco de dados
    6. Retorna resposta com URL encontrada ou status de não encontrado
    
    Args:
        request: CNPJ básico da empresa
    
    Returns:
        DiscoveryResponse com site encontrado, status e confidence score
    
    Raises:
        HTTPException: Em caso de erro na descoberta ou persistência
    """
    try:
        logger.info(f"🔍 Discovery: cnpj={request.cnpj_basico}")
        
        # 1. Buscar resultados Serper do banco de dados
        serper_data = await db_service.get_serper_results(request.cnpj_basico)
        
        if not serper_data:
            logger.warning(f"⚠️ Nenhum resultado Serper encontrado para cnpj={request.cnpj_basico}")
            # Salvar como não encontrado
            discovery_id = await db_service.save_discovery(
                cnpj_basico=request.cnpj_basico,
                website_url=None,
                discovery_status="not_found",
                serper_id=None,
                confidence_score=None,
                llm_reasoning="Nenhum resultado Serper encontrado"
            )
            
            return DiscoveryResponse(
                success=True,
                discovery_id=discovery_id,
                website_url=None,
                discovery_status="not_found",
                confidence_score=None
            )
        
        # 2. Extrair dados da empresa e resultados de busca
        razao_social = serper_data.get('razao_social') or ""
        nome_fantasia = serper_data.get('nome_fantasia') or serper_data.get('company_name') or ""
        municipio = serper_data.get('municipio') or ""
        serper_id = serper_data.get('id')
        
        # Extrair resultados de busca do JSONB
        search_results = serper_data.get('results_json', [])
        
        if not search_results:
            logger.warning(f"⚠️ Nenhum resultado de busca para cnpj={request.cnpj_basico}")
            discovery_id = await db_service.save_discovery(
                cnpj_basico=request.cnpj_basico,
                website_url=None,
                discovery_status="not_found",
                serper_id=serper_id,
                confidence_score=None,
                llm_reasoning="Nenhum resultado de busca disponível"
            )
            
            return DiscoveryResponse(
                success=True,
                discovery_id=discovery_id,
                website_url=None,
                discovery_status="not_found",
                confidence_score=None
            )
        
        # 3. Filtrar resultados (remover blacklist)
        filtered_results = _filter_search_results(search_results, ctx_label="")
        
        if not filtered_results:
            logger.warning(f"⚠️ Todos os resultados foram filtrados (blacklist) para cnpj={request.cnpj_basico}")
            discovery_id = await db_service.save_discovery(
                cnpj_basico=request.cnpj_basico,
                website_url=None,
                discovery_status="not_found",
                serper_id=serper_id,
                confidence_score=None,
                llm_reasoning="Todos os resultados foram filtrados (blacklist)"
            )
            
            return DiscoveryResponse(
                success=True,
                discovery_id=discovery_id,
                website_url=None,
                discovery_status="not_found",
                confidence_score=None
            )
        
        # 4. Usar DiscoveryAgent com Phoenix tracing para identificar site oficial
        discovery_agent = get_discovery_agent()
        website_url = None
        confidence_score = None
        llm_reasoning = None
        
        try:
            async with trace_llm_call("discovery-llm", "find_website") as span:
                if span:
                    span.set_attribute("cnpj_basico", request.cnpj_basico)
                    span.set_attribute("nome_fantasia", nome_fantasia)
                    span.set_attribute("razao_social", razao_social)
                    span.set_attribute("results_count", len(filtered_results))
                
                website_url = await discovery_agent.find_website(
                    nome_fantasia=nome_fantasia,
                    razao_social=razao_social,
                    cnpj=request.cnpj_basico,
                    email="",
                    municipio=municipio,
                    cnaes=None,
                    search_results=filtered_results,
                    ctx_label="",
                    request_id=""
                )
                
                if span:
                    span.set_attribute("website_found", website_url is not None)
                    if website_url:
                        span.set_attribute("website_url", website_url)
        except Exception as e:
            logger.error(f"❌ Erro no DiscoveryAgent: {e}", exc_info=True)
            llm_reasoning = f"Erro no DiscoveryAgent: {str(e)}"
        
        # 5. Determinar status e confidence score
        if website_url:
            discovery_status = "found"
            # Confidence score baseado em heurística simples
            # Se encontrou, assumir alta confiança (0.9)
            confidence_score = 0.9
        else:
            discovery_status = "not_found"
            confidence_score = None
        
        # 6. Salvar resultado da descoberta no banco de dados
        discovery_id = await db_service.save_discovery(
            cnpj_basico=request.cnpj_basico,
            website_url=website_url,
            discovery_status=discovery_status,
            serper_id=serper_id,
            confidence_score=confidence_score,
            llm_reasoning=llm_reasoning
        )
        
        logger.info(
            f"✅ Discovery concluída: cnpj={request.cnpj_basico}, "
            f"status={discovery_status}, website={website_url}, discovery_id={discovery_id}"
        )
        
        # 7. Retornar resposta
        return DiscoveryResponse(
            success=True,
            discovery_id=discovery_id,
            website_url=website_url,
            discovery_status=discovery_status,
            confidence_score=confidence_score
        )
    
    except Exception as e:
        logger.error(f"❌ Erro ao encontrar site: {e}", exc_info=True)
        
        # Tentar salvar erro no banco
        try:
            discovery_id = await db_service.save_discovery(
                cnpj_basico=request.cnpj_basico,
                website_url=None,
                discovery_status="error",
                serper_id=None,
                confidence_score=None,
                llm_reasoning=f"Erro: {str(e)}"
            )
        except Exception:
            discovery_id = None
        
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao encontrar site oficial: {str(e)}"
        )

