"""
Schemas Pydantic para endpoint Scrape v2.
"""
from pydantic import BaseModel, Field, ConfigDict, HttpUrl
from typing import Optional


class ScrapeRequest(BaseModel):
    """
    Request schema para scraping de site.
    
    Campos:
        cnpj_basico: CNPJ básico da empresa (8 primeiros dígitos) - obrigatório
        website_url: URL do site oficial para scraping - obrigatório
    """
    cnpj_basico: str = Field(..., description="CNPJ básico da empresa (8 primeiros dígitos)", min_length=8, max_length=8)
    website_url: str = Field(..., description="URL do site oficial para scraping")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "cnpj_basico": "12345678",
                "website_url": "https://www.empresa.com.br"
            }
        }
    )


class ScrapeResponse(BaseModel):
    """
    Response schema para scraping de site (processamento assíncrono).
    
    Campos:
        success: Indica se a requisição foi aceita
        message: Mensagem de confirmação
        cnpj_basico: CNPJ básico da empresa processada
        website_url: URL do site que será processado
        status: Status da requisição ('accepted', 'processing')
    """
    success: bool = Field(..., description="Indica se a requisição foi aceita")
    message: str = Field(..., description="Mensagem de confirmação")
    cnpj_basico: str = Field(..., description="CNPJ básico da empresa")
    website_url: str = Field(..., description="URL do site que será processado")
    status: str = Field(default="accepted", description="Status: 'accepted' (requisição aceita) ou 'processing' (em processamento)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "message": "Requisição de scraping aceita para CNPJ 12345678. Processamento em background.",
                "cnpj_basico": "12345678",
                "website_url": "https://www.empresa.com.br",
                "status": "accepted"
            }
        }
    )

