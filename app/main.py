import asyncio
import os
import logging
import time
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl
from app.schemas.profile import CompanyProfile
from app.services.scraper import scrape_url
from app.services.llm import analyze_content
from app.services.discovery import find_company_website
from app.core.security import get_api_key
from app.core.logging_utils import setup_logging
from app.services.llm import start_health_monitor
from app.services.learning import adaptive_config

# Configurar Logging (JSON Structured)
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="B2B Flash Profiler")

# Iniciar monitor de saúde dos providers LLM no startup
@app.on_event("startup")
async def startup_event():
    """Executado quando a aplicação inicia"""
    start_health_monitor()
    logger.info("🚀 Aplicação inicializada com sucesso")

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
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.post("/analyze", response_model=CompanyProfile, dependencies=[Depends(get_api_key)])
async def analyze_company(request: CompanyRequest):
    """
    Analyzes a company. Accepts URL directly OR company details (razao_social, nome_fantasia, cnpj) to find the website automatically.
    Enforces a 240-second hard timeout.
    """
    start_ts = time.perf_counter()
    url_str = str(request.url) if request.url else None

    try:
        # Discovery Phase
        if not url_str:
            if not any([request.razao_social, request.nome_fantasia, request.cnpj]):
                raise HTTPException(
                    status_code=400, 
                    detail="Deve fornecer URL ou dados da empresa (razao_social, nome_fantasia, cnpj)"
                )
            
            logger.info(f"[DISCOVERY] Iniciando busca para: {request.nome_fantasia} / {request.razao_social}")
            found_url = await find_company_website(
                request.razao_social or "",
                request.nome_fantasia or "",
                request.cnpj or "",
                email=request.email,
                municipio=request.municipio,
                cnaes=request.cnaes
            )
            
            if not found_url:
                raise HTTPException(
                    status_code=404, 
                    detail="Site oficial não encontrado com os dados fornecidos."
                )
            
            url_str = found_url
            logger.info(f"[DISCOVERY] Site identificado: {url_str}")

        # Wrap the orchestration in a task to enforce timeout
        logger.info(f"[PERF] analyze_company start url={url_str}")
        result = await asyncio.wait_for(process_analysis(url_str), timeout=240.0)
        
        # Add discovery source metadata if discovered
        if not request.url and url_str:
            if not result.sources:
                result.sources = []
            result.sources.insert(0, f"Discovered via Google Search: {url_str}")
            
        total = time.perf_counter() - start_ts
        logger.info(f"[PERF] analyze_company end url={url_str} total={total:.3f}s")
        return result
    except asyncio.TimeoutError:
        total = time.perf_counter() - start_ts
        logger.error(f"[PERF] analyze_company timeout url={url_str} total={total:.3f}s")
        raise HTTPException(status_code=504, detail="Analysis timed out (exceeded 240s)")
    except Exception as e:
        # Errors raised inside process_analysis (like LLM failure after retries) will be caught here
        total = time.perf_counter() - start_ts
        
        # If it's already an HTTPException, handle accordingly
        if isinstance(e, HTTPException):
            if e.status_code < 500:
                logger.warning(f"[PERF] analyze_company finished with expected error url={url_str} total={total:.3f}s code={e.status_code} detail={e.detail}")
            else:
                logger.error(f"[PERF] analyze_company failed with HTTP error url={url_str} total={total:.3f}s code={e.status_code} detail={e.detail}")
            raise e
            
        logger.error(f"[PERF] analyze_company failed url={url_str} total={total:.3f}s error={e}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_analysis(url: str) -> CompanyProfile:
    """
    Orquestra o fluxo principal de análise.
    Registra métricas de tempo por etapa para facilitar profiling.
    
    v2.0: Módulo de documentos (PDF/DOC) removido para simplificar fluxo.
    """
    overall_start = time.perf_counter()

    # 1. Scrape the main website AND subpages
    step_start = time.perf_counter()
    markdown, _, scraped_urls = await scrape_url(url, max_subpages=100)
    scrape_duration = time.perf_counter() - step_start
    logger.info(
        f"[PERF] process_analysis step=scrape_url url={url} "
        f"duration={scrape_duration:.3f}s pages={len(scraped_urls)}"
    )
    
    if not markdown:
        raise Exception("Failed to scrape content from the URL")

    # 2. Prepare content for LLM
    combined_text = f"--- WEB CRAWL START ({url}) ---\n{markdown}\n--- WEB CRAWL END ---\n\n"

    # 3. LLM Analysis
    llm_start = time.perf_counter()
    profile = await analyze_content(combined_text)
    llm_duration = time.perf_counter() - llm_start
    logger.info(
        f"[PERF] process_analysis step=llm_analysis url={url} "
        f"duration={llm_duration:.3f}s"
    )
    
    # 4. Add Sources
    profile.sources = list(set(scraped_urls))
    
    total_duration = time.perf_counter() - overall_start
    logger.info(
        f"[PERF] process_analysis step=total url={url} "
        f"duration={total_duration:.3f}s"
    )
    
    # 5. Atualizar aprendizado adaptativo após cada análise
    adaptive_config.optimize_after_batch(batch_size=1)
    
    return profile


@app.get("/")
async def root():
    return {"status": "ok", "service": "B2B Flash Profiler"}


@app.get("/learning/status")
async def learning_status():
    """
    Retorna o status do sistema de aprendizado adaptativo.
    Mostra configurações atuais e estatísticas de otimização.
    """
    return adaptive_config.get_status()


@app.post("/learning/optimize")
async def trigger_optimization():
    """
    Força uma otimização manual baseada nos padrões atuais.
    Útil após processar um lote grande de empresas.
    """
    adaptive_config.optimize_after_batch(batch_size=0)
    return {
        "message": "Otimização executada",
        "status": adaptive_config.get_status()
    }
