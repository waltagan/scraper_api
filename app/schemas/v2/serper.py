"""
Schemas Pydantic para endpoint Serper v2.
"""
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class SerperRequest(BaseModel):
    """
    Request schema para busca Serper.
    
    Campos:
        cnpj_basico: CNPJ básico da empresa (8 primeiros dígitos) - obrigatório
        razao_social: Razão social da empresa - opcional
        nome_fantasia: Nome fantasia da empresa - opcional
        municipio: Município da empresa - opcional
    """
    cnpj_basico: str = Field(..., description="CNPJ básico da empresa (8 primeiros dígitos)", min_length=8, max_length=8)
    razao_social: Optional[str] = Field(None, description="Razão social da empresa")
    nome_fantasia: Optional[str] = Field(None, description="Nome fantasia da empresa")
    municipio: Optional[str] = Field(None, description="Município da empresa")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "cnpj_basico": "12345678",
                "razao_social": "Empresa Exemplo LTDA",
                "nome_fantasia": "Exemplo",
                "municipio": "São Paulo"
            }
        }
    )


class SerperResponse(BaseModel):
    """
    Response schema para busca Serper (processamento assíncrono).
    
    Campos:
        success: Indica se a requisição foi aceita
        message: Mensagem de confirmação
        cnpj_basico: CNPJ básico da empresa processada
        status: Status da requisição ('accepted', 'processing')
    """
    success: bool = Field(..., description="Indica se a requisição foi aceita")
    message: str = Field(..., description="Mensagem de confirmação")
    cnpj_basico: str = Field(..., description="CNPJ básico da empresa")
    status: str = Field(default="accepted", description="Status: 'accepted' (requisição aceita) ou 'processing' (em processamento)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "message": "Requisição de busca Serper aceita para CNPJ 12345678. Processamento em background.",
                "cnpj_basico": "12345678",
                "status": "accepted"
            }
        }
    )

