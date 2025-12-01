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
from app.services.pdf import download_and_extract
from app.services.llm import analyze_content
from app.services.discovery import find_company_website
from app.core.security import get_api_key

# Configurar Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="B2B Flash Profiler")

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
    Enforces a 300-second hard timeout.
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
        result = await asyncio.wait_for(process_analysis(url_str), timeout=300.0)
        
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
        raise HTTPException(status_code=504, detail="Analysis timed out (exceeded 300s)")
    except Exception as e:
        # Errors raised inside process_analysis (like LLM failure after retries) will be caught here
        total = time.perf_counter() - start_ts
        logger.error(f"[PERF] analyze_company failed url={url_str} total={total:.3f}s error={e}")
        # If it's already an HTTPException, re-raise it
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

async def process_analysis(url: str) -> CompanyProfile:
    """
    Orquestra o fluxo principal de análise.
    Registra métricas de tempo por etapa para facilitar profiling.
    """
    overall_start = time.perf_counter()

    # 1. Scrape the main website AND subpages (Increased to 100 for max coverage)
    # Nota: pdf_links agora inclui PDFs, Word (.doc, .docx) e PowerPoint (.ppt, .pptx)
    step_start = time.perf_counter()
    markdown, pdf_links, scraped_urls = await scrape_url(url, max_subpages=100)
    scrape_duration = time.perf_counter() - step_start
    logger.info(
        f"[PERF] process_analysis step=scrape_url url={url} "
        f"duration={scrape_duration:.3f}s pages={len(scraped_urls)} docs={len(pdf_links)}"
    )
    
    if not markdown:
        raise Exception("Failed to scrape content from the URL")

    # 2. Process Documents (PDFs, Word, PowerPoint) - Max 5 in parallel
    docs_start = time.perf_counter()
    document_texts = []
    target_documents = []
    if pdf_links:
        # Limit to top 5 unique documents (aumentado de 3 para incluir mais tipos)
        target_documents = pdf_links[:5]
        results = await asyncio.gather(*[download_and_extract(doc) for doc in target_documents])
        document_texts = [res for res in results if res]
    docs_duration = time.perf_counter() - docs_start
    logger.info(
        f"[PERF] process_analysis step=documents url={url} "
        f"duration={docs_duration:.3f}s docs_requested={len(target_documents)} docs_ok={len(document_texts)}"
    )

    # 3. Combine content
    combine_start = time.perf_counter()
    combined_text = f"--- WEB CRAWL START ({url}) ---\n{markdown}\n--- WEB CRAWL END ---\n\n"
    if document_texts:
        combined_text += "\n".join(document_texts)
    combine_duration = time.perf_counter() - combine_start
    logger.info(
        f"[PERF] process_analysis step=combine_content url={url} "
        f"duration={combine_duration:.3f}s combined_chars={len(combined_text)}"
    )

    # 4. LLM Analysis
    # Note: Exceptions from analyze_content (after retries exhausted) will propagate up
    llm_start = time.perf_counter()
    profile = await analyze_content(combined_text)
    llm_duration = time.perf_counter() - llm_start
    logger.info(
        f"[PERF] process_analysis step=llm_analysis url={url} "
        f"duration={llm_duration:.3f}s"
    )
    
    # 5. Add Sources (Scraped URLs + Documents)
    all_sources = scraped_urls + target_documents
    profile.sources = list(set(all_sources)) # Remove duplicates if any
    
    # 6. Return Result (No longer saving to file)
    total_duration = time.perf_counter() - overall_start
    logger.info(
        f"[PERF] process_analysis step=total url={url} "
        f"duration={total_duration:.3f}s"
    )
    return profile

@app.get("/")
async def root():
    return {"status": "ok", "service": "B2B Flash Profiler"}
