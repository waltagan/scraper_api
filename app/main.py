import asyncio
import logging
import time
import uuid
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl

# Configurar encoding UTF-8 para Windows
import sys
if sys.platform == 'win32':
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass  # Se já estiver configurado, ignora

# Carregar variáveis de ambiente do arquivo .env
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[OK] Arquivo .env carregado")
except ImportError:
    print("[WARN] python-dotenv nao instalado - usando variaveis de ambiente do sistema")

from app.schemas.profile import CompanyProfile
from app.services.scraper import scrape_url
from app.services.discovery import find_company_website
from app.core.security import get_api_key
from app.core.logging_utils import setup_logging
from app.services.llm_manager import start_health_monitor
from app.core.database import get_pool, close_pool, test_connection
from app.core.vllm_client import check_vllm_health
from app.api.v2.router import router as v2_router

# Configurar Logging (JSON Structured)
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="B2B Flash Profiler")

# Registrar router v2
app.include_router(v2_router, prefix="/v2")

# Iniciar monitor de saúde dos providers LLM no startup
@app.on_event("startup")
async def startup_event():
    """Executado quando a aplicação inicia"""
    # Inicializar pool de conexões do banco de dados
    try:
        await get_pool()
        # Testar conexão
        if await test_connection():
            logger.info("✅ Conexão com banco de dados estabelecida")
        else:
            logger.warning("⚠️ Falha ao testar conexão com banco de dados")
    except Exception as e:
        logger.error(f"❌ Erro ao inicializar banco de dados: {e}")
    
    # Health check do SGLang
    try:
        vllm_health = await check_vllm_health()  # Nome mantido por compatibilidade
        logger.info(f"🔍 SGLang Health: {vllm_health}")
    except Exception as e:
        logger.warning(f"⚠️ Erro ao verificar saúde do SGLang: {e}")
    
    start_health_monitor()

    logger.info("🚀 Aplicação inicializada com sucesso")


@app.on_event("shutdown")
async def shutdown_event():
    """Executado quando a aplicação encerra"""
    await close_pool()
    logger.info("🔌 Aplicação encerrada")


class CompanyRequest(BaseModel):
    url: Optional[HttpUrl] = None
    razao_social: Optional[str] = None
    nome_fantasia: Optional[str] = None
    cnpj: Optional[str] = None
    # Novos campos para discovery aprimorado
    email: Optional[str] = None
    municipio: Optional[str] = None
    cnaes: Optional[List[str]] = None

# --- Global Exception Handlers ---

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global Error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error": str(exc)}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handler para exceções HTTP com informações adicionais"""
    response_content = {
        "detail": exc.detail,
        "status_code": exc.status_code,
        "path": str(request.url.path),
        "method": request.method
    }
    
    # Adicionar sugestão para erro "Method Not Allowed"
    if exc.status_code == 405:
        response_content["suggestion"] = "Verifique se está usando o método HTTP correto. Endpoints v2 requerem POST."
        response_content["available_endpoints"] = {
            "GET": ["/", "/health", "/v2", "/docs", "/redoc"],
            "POST": ["/v2/serper", "/v2/encontrar_site", "/v2/scrape", "/v2/montagem_perfil"]
        }
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response_content
    )




# --- Main Analysis Endpoint ---

@app.post("/monta_perfil", response_model=CompanyProfile, dependencies=[Depends(get_api_key)])
async def monta_perfil(request: CompanyRequest):
    """
    Monta o perfil completo de uma empresa. 
    Aceita URL diretamente OU dados da empresa (razao_social, nome_fantasia, cnpj) para buscar o site automaticamente.
    Aplica timeout de 300 segundos.
    """
    start_ts = time.perf_counter()
    url_str = str(request.url) if request.url else None
    
    # Gerar ID único para rastreamento
    request_id = str(uuid.uuid4())[:8]
    
    # Identificador de contexto para logs
    ctx_label = f"[{request_id}][CNPJ: {request.cnpj or 'N/A'} - {request.nome_fantasia or request.razao_social or 'Unknown'}]"
    

    try:
        # Discovery Phase
        if not url_str:
            if not any([request.razao_social, request.nome_fantasia, request.cnpj]):
                raise HTTPException(
                    status_code=400,
                    detail="Deve fornecer URL ou dados da empresa (razao_social, nome_fantasia, cnpj)"
                )
            
            
            try:
                # Aplicar timeout do Discovery (70s da config)
                from app.services.discovery.discovery_service import DISCOVERY_TIMEOUT
                try:
                    found_url = await asyncio.wait_for(
                        find_company_website(
                    request.razao_social or "",
                    request.nome_fantasia or "",
                    request.cnpj or "",
                    email=request.email,
                    municipio=request.municipio,
                    cnaes=request.cnaes,
                    ctx_label=ctx_label,
                    request_id=request_id
                        ),
                        timeout=DISCOVERY_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    error_msg = f"Timeout após {DISCOVERY_TIMEOUT}s"
                    logger.error(f"{ctx_label}[DISCOVERY] {error_msg}")
                    raise HTTPException(status_code=504, detail=f"Discovery timeout após {DISCOVERY_TIMEOUT}s")
            except HTTPException:
                raise
            except Exception as e:
                raise

            if not found_url:
                raise HTTPException(
                    status_code=404,
                    detail="Site oficial não encontrado com os dados fornecidos."
                )

            url_str = found_url

        # Wrap the orchestration in a task to enforce timeout
        result = await asyncio.wait_for(
            process_analysis(url_str, ctx_label, request_id), 
            timeout=300.0
        )
        
        # Add discovery source metadata if discovered
        if not request.url and url_str:
            if not result.sources:
                result.sources = []
            result.sources.insert(0, f"Discovered via Google Search: {url_str}")
            
        # Track completion (assíncrono, não bloqueante)
        total = time.perf_counter() - start_ts
        
        logger.info(f"{ctx_label} [PERF] monta_perfil end url={url_str} total={total:.3f}s")
        return result
        
    except asyncio.TimeoutError:
        total = time.perf_counter() - start_ts
        logger.error(f"{ctx_label} [PERF] monta_perfil timeout url={url_str} total={total:.3f}s")
        raise HTTPException(status_code=504, detail="Analysis timed out (exceeded 300s)")
        
    except Exception as e:
        total = time.perf_counter() - start_ts
        
        # If it's already an HTTPException, handle accordingly
        if isinstance(e, HTTPException):
            if e.status_code < 500:
                logger.warning(f"{ctx_label} [PERF] monta_perfil finished with expected error url={url_str} total={total:.3f}s code={e.status_code} detail={e.detail}")
            else:
                logger.error(f"{ctx_label} [PERF] monta_perfil failed with HTTP error url={url_str} total={total:.3f}s code={e.status_code} detail={e.detail}")
            raise e
            
        logger.error(f"{ctx_label} [PERF] monta_perfil failed url={url_str} total={total:.3f}s error={e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_analysis(url: str, ctx_label: str = "", request_id: str = "") -> CompanyProfile:
    """
    Orquestra o fluxo principal de análise.
    
    v2.0: Módulo de documentos (PDF/DOC) removido para simplificar fluxo.
    """
    # 1. Scrape the main website AND subpages
    markdown, _, scraped_urls = await scrape_url(url, max_subpages=50, ctx_label=ctx_label, request_id=request_id)
    if not markdown:
        raise Exception("Failed to scrape content from the URL")
    
    # 2. Construir perfil básico **sem uso de LLM**
    #    Neste estágio, apenas registramos as fontes coletadas.
    profile = CompanyProfile()
    profile.sources = list(set(scraped_urls))

    return profile


@app.get("/")
async def root():
    """Endpoint raiz - informações básicas da API"""
    return {
        "status": "ok",
        "service": "B2B Flash Profiler",
        "version": "2.0",
        "endpoints": {
            "v2": "/v2",
            "docs": "/docs",
            "redoc": "/redoc"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Testar conexão com banco
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "status": "ok",
        "database": db_status,
        "service": "B2B Flash Profiler"
    }
