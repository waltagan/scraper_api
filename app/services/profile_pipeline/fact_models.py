from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class FactItem(BaseModel):
    """
    Fato atômico extraído de um chunk.

    - value: valor textual do fato (nome, email, produto, cliente, etc.).
    - evidence_quote: trecho literal curto que suporta o fato (máx ~160 chars).
    - confidence: confiança de 0.0 a 1.0 (o LLM estima, mas validamos range).
    """

    value: str = Field(..., description="Valor textual do fato extraído")
    evidence_quote: str = Field(
        ...,
        description="Trecho literal curto extraído do chunk que suporta o fato",
        max_length=320,
    )
    confidence: float = Field(
        0.7,
        ge=0.0,
        le=1.0,
        description="Confiança estimada pelo modelo (0.0 a 1.0)",
    )

    @field_validator("value")
    @classmethod
    def _strip_value(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("value não pode ser vazio")
        return v

    @field_validator("evidence_quote")
    @classmethod
    def _normalize_quote(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("evidence_quote não pode ser vazio")
        # Limitar tamanho de forma hard para evitar estouro em logs
        if len(v) > 320:
            return v[:320]
        return v


class FactSource(BaseModel):
    """Metadados de origem de um FactBundle."""

    chunk_index: int = Field(..., ge=1, description="Índice 1-based do chunk")
    total_chunks: Optional[int] = Field(
        None, ge=1, description="Total de chunks existentes para este CNPJ"
    )
    page_source: List[str] = Field(
        default_factory=list,
        description="URLs de página associadas a este chunk (derivadas de page_source)",
        max_length=5,
    )


class FactBundle(BaseModel):
    """
    Pacote de fatos extraídos de UM chunk (Estágio A).

    Importante:
    - Não representa o perfil final.
    - Não combina múltiplos chunks.
    - Cada fato deve ter evidência literal curta.
    """

    source: FactSource

    identity_facts: List[FactItem] = Field(
        default_factory=list,
        max_length=20,
        description="Fatos sobre identidade (nome, CNPJ, descrição curta, etc.)",
    )
    contact_facts: List[FactItem] = Field(
        default_factory=list,
        max_length=20,
        description="Fatos de contato (emails, telefones, URLs, endereços, etc.)",
    )
    offerings_facts: List[FactItem] = Field(
        default_factory=list,
        max_length=20,
        description="Fatos sobre produtos/serviços/ofertas",
    )
    reputation_facts: List[FactItem] = Field(
        default_factory=list,
        max_length=20,
        description="Fatos de reputação (clientes, certificações, prêmios, cases, etc.)",
    )

    # Métrica local de utilidade do chunk (preenchida no Estágio A).
    useful_count: int = Field(
        0,
        ge=0,
        description=(
            "Número total de fatos úteis neste FactBundle. "
            "Usado para descartar chunks vazios no merge."
        ),
    )

    @field_validator(
        "identity_facts", "contact_facts", "offerings_facts", "reputation_facts"
    )
    @classmethod
    def _dedupe_list(cls, v: List[FactItem]) -> List[FactItem]:
        """
        Deduplicação leve por `value` normalizado.

        Mantém a primeira ocorrência de cada `value` (case-insensitive, trim),
        mesmo que quotes/confidence variem.
        """
        if not v:
            return v

        seen = set()
        unique: List[FactItem] = []
        for item in v:
            key = item.value.strip().lower()
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        # Respeitar hard cap de 20 itens
        return unique[:20]

    def compute_useful_count(self) -> int:
        """
        Calcula quantos fatos \"úteis\" existem neste bundle.

        Hoje usamos uma heurística simples: soma bruta das listas.
        Isso é suficiente para distinguir páginas vazias/rodapé/legais
        de páginas que realmente carregam informação de perfil.
        """
        count = (
            len(self.identity_facts)
            + len(self.contact_facts)
            + len(self.offerings_facts)
            + len(self.reputation_facts)
        )
        self.useful_count = count
        return count

