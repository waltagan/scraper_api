"""
Router principal para API v2.
Agrupa todos os endpoints v2 em um único router.
"""
from fastapi import APIRouter
from app.api.v2 import serper, encontrar_site, scrape, scrape_batch, montagem_perfil

# Criar router principal
router = APIRouter()

# Endpoint de health check e documentação
@router.get("/")
async def v2_root():
    """Endpoint raiz da API v2 - lista endpoints disponíveis"""
    return {
        "version": "v2",
        "status": "ok",
        "endpoints": {
            "serper": "POST /v2/serper",
            "encontrar_site": "POST /v2/encontrar_site",
            "scrape": "POST /v2/scrape",
            "scrape_batch": "POST /v2/scrape/batch",
            "scrape_batch_status": "GET /v2/scrape/batch/status",
            "scrape_batch_cancel": "POST /v2/scrape/batch/cancel",
            "montagem_perfil": "POST /v2/montagem_perfil"
        },
        "docs": "/docs"
    }

# Incluir todos os routers v2
router.include_router(serper.router, tags=["v2-serper"])
router.include_router(encontrar_site.router, tags=["v2-discovery"])
router.include_router(scrape.router, tags=["v2-scrape"])
router.include_router(scrape_batch.router, tags=["v2-scrape-batch"])
router.include_router(montagem_perfil.router, tags=["v2-profile"])

__all__ = ["router"]

