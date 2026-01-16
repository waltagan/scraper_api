"""
Endpoint Montagem Perfil v2 - Extração assíncrona de perfil com paralelismo.
Processamento em background - retorna imediatamente após aceitar requisição.
"""
import logging
import time
import asyncio
from typing import List
from fastapi import APIRouter, HTTPException
from app.schemas.v2.profile import ProfileRequest, ProfileResponse
from app.services.database_service import DatabaseService, get_db_service
from app.services.agents.profile_extractor_agent import get_profile_extractor_agent
from app.services.profile_builder.profile_merger import merge_profiles
from app.core.phoenix_tracer import trace_llm_call
from app.schemas.profile import CompanyProfile

logger = logging.getLogger(__name__)

router = APIRouter()
db_service = get_db_service()


async def _process_profile_background(request: ProfileRequest):
    """
    Processa montagem de perfil em background.
    """
    try:
        logger.info(f"🔍 [BACKGROUND] Montagem Perfil: cnpj={request.cnpj_basico}")
        
        # 1. Buscar chunks do banco de dados
        chunks_data = await db_service.get_chunks(request.cnpj_basico)
        
        if not chunks_data:
            logger.warning(f"⚠️ [BACKGROUND] Nenhum chunk encontrado para cnpj={request.cnpj_basico}")
            return
        
        chunks_count = len(chunks_data)
        logger.info(f"✅ [BACKGROUND] {chunks_count} chunks encontrados (cnpj={request.cnpj_basico})")
        
        # 2. Processar chunks em paralelo usando ProfileExtractorAgent
        profile_extractor = get_profile_extractor_agent()
        
        async def extract_chunk(chunk_data: dict, chunk_idx: int) -> CompanyProfile:
            """Extrai perfil de um chunk com Phoenix tracing."""
            chunk_content = chunk_data.get('chunk_content', '')
            
            if not chunk_content or len(chunk_content.strip()) < 100:
                return CompanyProfile()
            
            try:
                async with trace_llm_call("profile-llm", f"extract_profile_chunk_{chunk_idx}") as span:
                    if span:
                        span.set_attribute("cnpj_basico", request.cnpj_basico)
                        span.set_attribute("chunk_index", chunk_idx)
                        span.set_attribute("chunk_tokens", chunk_data.get('token_count', 0))
                    
                    profile = await profile_extractor.extract_profile(
                        content=chunk_content,
                        ctx_label="",
                        request_id=""
                    )
                    
                    if span:
                        span.set_attribute("profile_empty", profile.is_empty() if hasattr(profile, 'is_empty') else False)
                    
                    return profile
            except Exception as e:
                logger.warning(f"⚠️ [BACKGROUND] Erro ao processar chunk {chunk_idx}: {e}")
                return CompanyProfile()
        
        # Processar todos os chunks em paralelo
        profile_tasks = [extract_chunk(chunk_data, idx) for idx, chunk_data in enumerate(chunks_data)]
        profiles_results = await asyncio.gather(*profile_tasks, return_exceptions=True)
        
        # Filtrar perfis válidos
        valid_profiles = []
        for idx, profile_result in enumerate(profiles_results):
            if isinstance(profile_result, Exception):
                logger.warning(f"⚠️ [BACKGROUND] Exceção ao processar chunk {idx}: {profile_result}")
                continue
            
            if profile_result and isinstance(profile_result, CompanyProfile):
                if hasattr(profile_result, 'is_empty') and not profile_result.is_empty():
                    valid_profiles.append(profile_result)
                elif not hasattr(profile_result, 'is_empty'):
                    profile_dict = profile_result.model_dump() if hasattr(profile_result, 'model_dump') else {}
                    if profile_dict.get('identity', {}).get('company_name') or profile_dict.get('classification', {}).get('industry'):
                        valid_profiles.append(profile_result)
        
        chunks_processed = len(valid_profiles)
        
        if chunks_processed == 0:
            logger.warning(f"⚠️ [BACKGROUND] Nenhum perfil válido extraído para cnpj={request.cnpj_basico}")
            return
        
        # 3. Mergear perfis parciais em um perfil completo
        try:
            merged_profile = merge_profiles(valid_profiles)
        except Exception as e:
            logger.error(f"❌ [BACKGROUND] Erro ao mergear perfis: {e}", exc_info=True)
            if valid_profiles:
                merged_profile = valid_profiles[0]
            else:
                merged_profile = CompanyProfile()
        
        # 4. Salvar perfil no banco de dados
        company_id = await db_service.save_profile(
            cnpj_basico=request.cnpj_basico,
            profile=merged_profile
        )
        
        logger.info(
            f"✅ [BACKGROUND] Montagem Perfil concluída: cnpj={request.cnpj_basico}, "
            f"status=success, {chunks_processed}/{chunks_count} chunks processados, "
            f"company_id={company_id}"
        )
    except Exception as e:
        logger.error(f"❌ [BACKGROUND] Erro ao processar montagem de perfil: {e}", exc_info=True)


@router.post("/montagem_perfil", response_model=ProfileResponse)
async def montar_perfil(request: ProfileRequest) -> ProfileResponse:
    """
    Monta perfil completo da empresa processando chunks em paralelo.
    
    Processamento assíncrono: retorna imediatamente após aceitar a requisição.
    O processamento (extração LLM, merge e salvamento) ocorre em background.
    
    Args:
        request: CNPJ básico da empresa
    
    Returns:
        ProfileResponse com confirmação de recebimento da requisição
    
    Raises:
        HTTPException: Em caso de erro ao aceitar requisição
    """
    try:
        logger.info(f"📥 Requisição Montagem Perfil recebida: cnpj={request.cnpj_basico}")
        
        # Iniciar processamento em background
        asyncio.create_task(_process_profile_background(request))
        
        # Retornar confirmação imediata
        return ProfileResponse(
            success=True,
            message=f"Requisição de montagem de perfil aceita para CNPJ {request.cnpj_basico}. Processamento em background.",
            cnpj_basico=request.cnpj_basico,
            status="accepted"
        )
    
    except Exception as e:
        logger.error(f"❌ Erro ao aceitar requisição Montagem Perfil: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao aceitar requisição: {str(e)}"
        )

