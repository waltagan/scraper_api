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
from app.services.profile_pipeline.orchestrator import run_profile_pipeline
from app.schemas.profile import CompanyProfile

logger = logging.getLogger(__name__)

router = APIRouter()
db_service = get_db_service()


async def _process_profile_background(request: ProfileRequest):
    """
    Processa montagem de perfil em background.
    """
    try:
        logger.info(f"🔍 [BACKGROUND] Montagem Perfil (pipeline A→B→C): cnpj={request.cnpj_basico}")

        profile = await run_profile_pipeline(
            cnpj_basico=request.cnpj_basico,
            ctx_label="[PROFILE_V2] ",
            request_id="",
        )

        logger.info(
            f"✅ [BACKGROUND] Montagem Perfil concluída: cnpj={request.cnpj_basico}, "
            f"status=success, empty={profile.is_empty() if hasattr(profile, 'is_empty') else False}"
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

