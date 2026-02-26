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
        description="Tamanho do lote de salvamento por worker na persistência final",
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


class ScrapeMainUnifiedRequest(BaseModel):
    """Request para endpoint unificado (etapas 1->2->3 em sequência)."""
    cnpj_basico: str = Field(
        ...,
        description="CNPJ básico da empresa (8 primeiros dígitos)",
        min_length=8,
        max_length=8,
    )
    website_url: str = Field(..., description="URL do site oficial para processamento unificado")
    timeout_seconds: int = Field(
        30,
        ge=5,
        le=120,
        description="Timeout por URL na microetapa de captura da main page",
    )
    redis_ttl_seconds: int = Field(
        600,
        ge=60,
        le=3600,
        description="TTL do raw_content temporário em Redis",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "cnpj_basico": "12345678",
                "website_url": "https://www.empresa.com.br",
                "timeout_seconds": 30,
                "redis_ttl_seconds": 600,
            }
        }
    )


class ScrapeMainUnifiedBatchRequest(BaseModel):
    """Request para endpoint unificado em lote."""
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
    save_mode: str = Field(
        "checkpoint",
        description="Modo de persistência: 'checkpoint' (usa save_every) ou 'final_only' (salva só ao final)",
    )
    save_in_batches: int = Field(
        500,
        ge=1,
        description="Tamanho do lote de persistência no flush final (especialmente no modo final_only)",
    )
    timeout_seconds: int = Field(
        30,
        ge=5,
        le=120,
        description="Timeout da microetapa de captura por URL",
    )
    redis_ttl_seconds: int = Field(
        600,
        ge=60,
        le=3600,
        description="TTL do raw_content temporário em Redis",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_samples": 3200,
                "batch_size": 3200,
                "save_every": 50,
                "save_mode": "final_only",
                "save_in_batches": 500,
                "timeout_seconds": 30,
                "redis_ttl_seconds": 600,
            }
        }
    )


class ScrapeMainUnifiedResponse(BaseModel):
    """Response de aceite para endpoint unificado."""
    success: bool = Field(..., description="Indica se a requisição foi aceita")
    status: str = Field(default="accepted", description="Status da requisição")
    stage: str = Field(default="unified", description="Etapa solicitada")
    message: str = Field(..., description="Mensagem de aceite")
    run_id: str = Field(..., description="ID da execução para rastreio")
    cnpj_basico: str = Field(..., description="CNPJ básico da empresa")


class ScrapeMainUnifiedBatchResponse(BaseModel):
    """Response de aceite para processamento batch unificado."""
    success: bool = Field(..., description="Indica se o batch foi aceito")
    status: str = Field(default="accepted", description="Status da requisição")
    stage: str = Field(default="unified", description="Etapa batch solicitada")
    total_samples: int = Field(..., description="Total solicitado")
    batch_size: int = Field(..., description="Lote concorrente configurado")
    save_every: int = Field(..., description="Checkpoint de persistência")
    run_id: str = Field(..., description="ID da execução para rastreio")
    message: str = Field(..., description="Mensagem de aceite")


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

