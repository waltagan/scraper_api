"""
Schema do Perfil de Empresa para extração B2B.

v8.0: Deduplicação robusta via pós-processamento
      - uniqueItems/maxItems/minLength são HINTS para o modelo (podem ser ignorados por XGrammar)
      - Validadores Pydantic garantem deduplicação básica
      - Pós-processamento no agente garante deduplicação robusta + anti-template
      - Hard caps numéricos no PROMPT v8.2 (80 itens por categoria)

v9.0: Constraints estruturais para qualidade
      - ProductCategory.category_name: obrigatório (não-null) → elimina categorias sem nome
      - ServiceDetail.name: obrigatório (não-null) → elimina objetos vazios em service_details
      - Melhora qualidade sem aumentar latência
"""
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class Identity(BaseModel):
    """Informações básicas de identificação da empresa."""
    company_name: Optional[str] = Field(None, description="Nome oficial da empresa")
    cnpj: Optional[str] = Field(None, description="CNPJ brasileiro se disponível")
    tagline: Optional[str] = Field(None, description="Slogan ou frase de efeito da empresa")
    description: Optional[str] = Field(None, description="Descrição resumida do que a empresa faz")
    founding_year: Optional[str] = Field(None, description="Ano de fundação")
    employee_count_range: Optional[str] = Field(None, description="Faixa de funcionários (ex: 10-50, 100-500)")


class Classification(BaseModel):
    """Classificação e posicionamento de mercado."""
    industry: Optional[str] = Field(None, description="Setor/indústria de atuação")
    business_model: Optional[str] = Field(None, description="Modelo: B2B, B2C, Distribuidor, Fabricante, etc.")
    target_audience: Optional[str] = Field(None, description="Público-alvo ou segmento atendido")
    geographic_coverage: Optional[str] = Field(None, description="Abrangência: Nacional, Regional, São Paulo, etc.")


class TeamProfile(BaseModel):
    """Informações sobre a equipe."""
    size_range: Optional[str] = Field(None, description="Tamanho da equipe")
    key_roles: List[str] = Field(
        default_factory=list, 
        max_length=50,
        description="Principais funções/cargos ÚNICOS na equipe (sem duplicatas)",
        json_schema_extra={"uniqueItems": True}  # Hint para o modelo (não garantido por XGrammar)
    )
    team_certifications: List[str] = Field(
        default_factory=list, 
        max_length=30,
        description="Certificações ÚNICAS da equipe (sem duplicatas)",
        json_schema_extra={"uniqueItems": True}  # Hint para o modelo (não garantido por XGrammar)
    )
    
    @field_validator('key_roles', 'team_certifications')
    @classmethod
    def deduplicate_list(cls, v: List[str]) -> List[str]:
        """Remove duplicatas mantendo ordem da primeira ocorrência."""
        if not v:
            return v
        seen = set()
        unique = []
        for item in v:
            item_stripped = item.strip()
            if item_stripped and item_stripped not in seen:
                seen.add(item_stripped)
                unique.append(item_stripped)
        return unique


class ServiceDetail(BaseModel):
    """Detalhes de um serviço oferecido.
    
    v9: name é obrigatório (não-null) para evitar objetos vazios em service_details.
    """
    name: str = Field(..., description="Nome do serviço (obrigatório para evitar objetos vazios)")
    description: Optional[str] = Field(None, description="Descrição do serviço")
    methodology: Optional[str] = Field(None, description="Metodologia utilizada")
    deliverables: List[str] = Field(
        default_factory=list, 
        max_length=30,
        description="Entregáveis ÚNICOS do serviço (sem duplicatas)",
        json_schema_extra={"uniqueItems": True}
    )
    ideal_client_profile: Optional[str] = Field(None, description="Perfil ideal de cliente")
    
    @field_validator('deliverables')
    @classmethod
    def deduplicate_deliverables(cls, v: List[str]) -> List[str]:
        """Remove duplicatas mantendo ordem da primeira ocorrência."""
        if not v:
            return v
        seen = set()
        unique = []
        for item in v:
            item_stripped = item.strip()
            if item_stripped and item_stripped not in seen:
                seen.add(item_stripped)
                unique.append(item_stripped)
        return unique


class ProductCategory(BaseModel):
    """Categoria de produtos com itens específicos.
    
    v9: category_name é obrigatório (não-null) para evitar categorias sem nome.
    """
    category_name: str = Field(..., description="Nome da categoria de produtos (obrigatório)")
    items: List[str] = Field(
        default_factory=list, 
        max_length=200,  # Hint (não garantido por XGrammar), pós-processamento usa hard cap 80
        description=(
            "PRODUTOS ESPECÍFICOS ÚNICOS: nomes, modelos, códigos, versões, medidas. "
            "DEDUPLICAÇÃO OBRIGATÓRIA: cada item deve aparecer APENAS UMA VEZ. "
            "ANTI-LOOP: não repita variações do mesmo padrão. "
            "Se detectar repetição, interrompa imediatamente. "
            "HARD CAP: máximo 80 itens por categoria (PROMPT v8.2)."
        ),
        json_schema_extra={"uniqueItems": True, "minLength": 2}  # Hints (não garantidos)
    )
    
    @field_validator('items')
    @classmethod
    def deduplicate_items(cls, v: List[str]) -> List[str]:
        """Remove duplicatas mantendo ordem da primeira ocorrência."""
        if not v:
            return v
        seen = set()
        unique = []
        for item in v:
            item_stripped = item.strip()
            if item_stripped and item_stripped not in seen:
                seen.add(item_stripped)
                unique.append(item_stripped)
        return unique


class Offerings(BaseModel):
    """Produtos e serviços oferecidos pela empresa."""
    products: List[str] = Field(
        default_factory=list, 
        max_length=200,
        description="Lista ÚNICA de produtos gerais (sem duplicatas, máx. 200)",
        json_schema_extra={"uniqueItems": True}
    )
    product_categories: List[ProductCategory] = Field(
        default_factory=list, 
        max_length=80,
        description="Categorias de produtos com itens específicos ÚNICOS (máx. 80)"
    )
    services: List[str] = Field(
        default_factory=list, 
        max_length=100,
        description="Lista ÚNICA de serviços (sem duplicatas, máx. 100)",
        json_schema_extra={"uniqueItems": True}
    )
    service_details: List[ServiceDetail] = Field(
        default_factory=list, 
        max_length=30,
        description="Detalhes dos principais serviços (máx. 30)"
    )
    engagement_models: List[str] = Field(
        default_factory=list, 
        max_length=20,
        description="Modelos ÚNICOS de contratação (sem duplicatas, máx. 20)",
        json_schema_extra={"uniqueItems": True}
    )
    key_differentiators: List[str] = Field(
        default_factory=list, 
        max_length=30,
        description="Diferenciais ÚNICOS (sem duplicatas, máx. 30)",
        json_schema_extra={"uniqueItems": True}
    )
    
    @field_validator('products', 'services', 'engagement_models', 'key_differentiators')
    @classmethod
    def deduplicate_list(cls, v: List[str]) -> List[str]:
        """Remove duplicatas mantendo ordem da primeira ocorrência."""
        if not v:
            return v
        seen = set()
        unique = []
        for item in v:
            item_stripped = item.strip()
            if item_stripped and item_stripped not in seen:
                seen.add(item_stripped)
                unique.append(item_stripped)
        return unique


class CaseStudy(BaseModel):
    """Estudo de caso ou projeto de referência."""
    title: Optional[str] = Field(None, description="Título do caso de sucesso")
    client_name: Optional[str] = Field(None, description="Nome do cliente")
    industry: Optional[str] = Field(None, description="Setor do cliente")
    challenge: Optional[str] = Field(None, description="Desafio enfrentado")
    solution: Optional[str] = Field(None, description="Solução implementada")
    outcome: Optional[str] = Field(None, description="Resultado obtido")


class Reputation(BaseModel):
    """Reputação e prova social da empresa."""
    certifications: List[str] = Field(
        default_factory=list, 
        max_length=50,
        description="Certificações ÚNICAS (ISO, ANVISA, etc.) - sem duplicatas (máx. 50)",
        json_schema_extra={"uniqueItems": True}
    )
    awards: List[str] = Field(
        default_factory=list, 
        max_length=50,
        description="Prêmios ÚNICOS - sem duplicatas (máx. 50)",
        json_schema_extra={"uniqueItems": True}
    )
    partnerships: List[str] = Field(
        default_factory=list, 
        max_length=100,
        description="Parcerias ÚNICAS - sem duplicatas (máx. 100)",
        json_schema_extra={"uniqueItems": True}
    )
    client_list: List[str] = Field(
        default_factory=list, 
        max_length=200,
        description="Clientes ÚNICOS de referência (deduplicados, sem locais/sufixos, máx. 200)",
        json_schema_extra={"uniqueItems": True}
    )
    case_studies: List[CaseStudy] = Field(
        default_factory=list, 
        max_length=30,
        description="Casos de sucesso detalhados (máx. 30)"
    )
    
    @field_validator('certifications', 'awards', 'partnerships', 'client_list')
    @classmethod
    def deduplicate_list(cls, v: List[str]) -> List[str]:
        """Remove duplicatas mantendo ordem da primeira ocorrência."""
        if not v:
            return v
        seen = set()
        unique = []
        for item in v:
            item_stripped = item.strip()
            if item_stripped and item_stripped not in seen:
                seen.add(item_stripped)
                unique.append(item_stripped)
        return unique


class Contact(BaseModel):
    """Informações de contato."""
    emails: List[str] = Field(
        default_factory=list, 
        max_length=20,
        description="Emails ÚNICOS de contato (sem duplicatas, máx. 20)",
        json_schema_extra={"uniqueItems": True}
    )
    phones: List[str] = Field(
        default_factory=list, 
        max_length=20,
        description="Telefones ÚNICOS (sem duplicatas, máx. 20)",
        json_schema_extra={"uniqueItems": True}
    )
    linkedin_url: Optional[str] = Field(None, description="URL do LinkedIn")
    website_url: Optional[str] = Field(None, description="URL do site")
    headquarters_address: Optional[str] = Field(None, description="Endereço da sede")
    locations: List[str] = Field(
        default_factory=list, 
        max_length=50,
        description="Localizações ÚNICAS (sem duplicatas, máx. 50)",
        json_schema_extra={"uniqueItems": True}
    )
    
    @field_validator('emails', 'phones', 'locations')
    @classmethod
    def deduplicate_list(cls, v: List[str]) -> List[str]:
        """Remove duplicatas mantendo ordem da primeira ocorrência."""
        if not v:
            return v
        seen = set()
        unique = []
        for item in v:
            item_stripped = item.strip()
            if item_stripped and item_stripped not in seen:
                seen.add(item_stripped)
                unique.append(item_stripped)
        return unique

class CompanyProfile(BaseModel):
    identity: Identity = Identity()
    classification: Classification = Classification()
    team: TeamProfile = TeamProfile()
    offerings: Offerings = Offerings()
    reputation: Reputation = Reputation()
    contact: Contact = Contact()
    sources: List[str] = []

    def is_empty(self) -> bool:
        """
        Verifica se o perfil da empresa está vazio (sem dados preenchidos).
        Retorna True se nenhum campo relevante foi preenchido.
        """
        # Verifica se identity tem dados básicos
        identity_empty = (
            not self.identity.company_name and
            not self.identity.cnpj and
            not self.identity.tagline and
            not self.identity.description
        )

        # Verifica se classification tem dados
        classification_empty = (
            not self.classification.industry and
            not self.classification.business_model and
            not self.classification.target_audience
        )

        # Verifica se offerings tem dados
        offerings_empty = (
            not self.offerings.products and
            not self.offerings.services and
            not self.offerings.product_categories
        )

        # Verifica se contact tem dados
        contact_empty = (
            not self.contact.website_url and
            not self.contact.emails and
            not self.contact.phones
        )

        # Se pelo menos um campo principal tem dados, não está vazio
        return identity_empty and classification_empty and offerings_empty and contact_empty
