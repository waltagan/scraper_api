"""
Schemas Pydantic para endpoint Scrape v2.
"""
from pydantic import BaseModel, Field, ConfigDict


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


class ScrapeMainPageRequest(BaseModel):
    """Request schema para etapa 1: scrape da main page."""
    cnpj_basico: str = Field(
        ...,
        description="CNPJ básico da empresa (8 primeiros dígitos)",
        min_length=8,
        max_length=8,
    )
    website_url: str = Field(..., description="URL do site oficial para scrape da main page")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "cnpj_basico": "12345678",
                "website_url": "https://www.empresa.com.br",
            }
        }
    )


class ScrapeMainPageProcessRequest(BaseModel):
    """Request schema para etapas 2 e 3, baseadas no raw_content já salvo."""
    cnpj_basico: str = Field(
        ...,
        description="CNPJ básico da empresa (8 primeiros dígitos)",
        min_length=8,
        max_length=8,
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "cnpj_basico": "12345678",
            }
        }
    )


class ScrapeMainPageResponse(BaseModel):
    """Response padrão dos novos endpoints de scrape_main."""
    success: bool = Field(..., description="Indica se a requisição foi aceita")
    message: str = Field(..., description="Mensagem de confirmação")
    cnpj_basico: str = Field(..., description="CNPJ básico da empresa")
    status: str = Field(default="accepted", description="Status da requisição")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "message": "Requisição aceita. Processamento em background.",
                "cnpj_basico": "12345678",
                "status": "accepted",
            }
        }
    )


class ScrapeMainPageBatchRequest(BaseModel):
    """Request para processamento em lote da etapa 1."""
    total_samples: int = Field(100000, ge=1, description="Total de registros a processar")
    batch_size: int = Field(
        3000,
        ge=1,
        le=3000,
        description="Tamanho do lote concorrente (máximo recomendado 3000)",
    )
    save_every: int = Field(
        1000,
        ge=1,
        description="Mantido por compatibilidade (batch unificado salva somente no final)",
    )
    timeout_seconds: int = Field(
        30,
        ge=5,
        le=120,
        description="Timeout da etapa 1 por URL",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_samples": 100000,
                "batch_size": 3000,
                "save_every": 1000,
                "timeout_seconds": 40,
            }
        }
    )


class ScrapeMainBatchRequest(BaseModel):
    """Request para processamento em lote das etapas 2 e 3."""
    total_samples: int = Field(100000, ge=1, description="Total de registros a processar")
    batch_size: int = Field(
        3600,
        ge=1,
        le=3600,
        description="Tamanho do lote concorrente (máximo recomendado 3600)",
    )
    save_every: int = Field(
        1000,
        ge=1,
        description="Quantidade processada antes de persistir checkpoint em lote",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_samples": 100000,
                "batch_size": 3600,
                "save_every": 1000,
            }
        }
    )


class ScrapeMainBatchResponse(BaseModel):
    """Response de aceite para processamento batch das etapas de scrape_main."""
    success: bool = Field(..., description="Indica se o batch foi aceito")
    status: str = Field(default="accepted", description="Status da requisição")
    stage: str = Field(..., description="Etapa batch solicitada")
    total_samples: int = Field(..., description="Total solicitado")
    batch_size: int = Field(..., description="Lote concorrente configurado")
    save_every: int = Field(..., description="Checkpoint de persistência")
    message: str = Field(..., description="Mensagem de aceite")

