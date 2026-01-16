"""
Schemas Pydantic para endpoint Profile v2.
"""
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class ProfileRequest(BaseModel):
    """
    Request schema para montagem de perfil da empresa.
    
    Campos:
        cnpj_basico: CNPJ básico da empresa (8 primeiros dígitos) - obrigatório
    """
    cnpj_basico: str = Field(..., description="CNPJ básico da empresa (8 primeiros dígitos)", min_length=8, max_length=8)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "cnpj_basico": "12345678"
            }
        }
    )


class ProfileResponse(BaseModel):
    """
    Response schema para montagem de perfil da empresa (processamento assíncrono).
    
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
                "message": "Requisição de montagem de perfil aceita para CNPJ 12345678. Processamento em background.",
                "cnpj_basico": "12345678",
                "status": "accepted"
            }
        }
    )

