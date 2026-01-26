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

v9.1: Caps reduzidos + espaço de degeneração menor
      - maxItems alinhados com realidade (menos runaway generation)
      - Reduz latência e melhora estabilidade
      - Menos tokens de output permitido = menos loops

v10.0: Guided Decoding - Schema como "guarda-rail"
      - maxItems explícitos no schema (SGLang Guided Decoding respeita)
      - Literal types para reduzir alucinações (business_model)
      - Descrições claras para guiar geração (SGLang usa descrições)
"""
from typing import List, Optional, Literal
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
    """Classificação e posicionamento de mercado.
    
    v10.0: business_model com Literal type para reduzir alucinações
          - SGLang Guided Decoding força escolha apenas entre opções válidas
    """
    industry: Optional[str] = Field(
        None, 
        description="Setor/indústria de atuação da empresa (ex: Tecnologia, Construção, Saúde)"
    )
    business_model: Optional[Literal[
        "B2B", "B2C", "B2B2C", 
        "Distribuidor", "Fabricante", "Revendedor",
        "Prestador de Serviços", "Marketplace", "SaaS"
    ]] = Field(
        None, 
        description="Modelo de negócio: B2B (empresa para empresa), B2C (empresa para consumidor), Distribuidor, Fabricante, etc."
    )
    target_audience: Optional[str] = Field(
        None, 
        description="Público-alvo ou segmento atendido (ex: Pequenas empresas, Grandes corporações, Consumidores finais)"
    )
    geographic_coverage: Optional[str] = Field(
        None, 
        description="Abrangência geográfica: Nacional, Regional, Internacional, ou estados/cidades específicos"
    )


class TeamProfile(BaseModel):
    """Informações sobre a equipe."""
    size_range: Optional[str] = Field(None, description="Tamanho da equipe")
    key_roles: List[str] = Field(
        default_factory=list, 
        max_length=30,  # v10.0: Alinhado com Guided Decoding
        description="Principais funções/cargos ÚNICOS na equipe. Máximo 30 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 30}  # v10.0: maxItems explícito para Guided Decoding
    )
    team_certifications: List[str] = Field(
        default_factory=list, 
        max_length=20,  # v10.0: Alinhado com Guided Decoding
        description="Certificações ÚNICAS da equipe. Máximo 20 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 20}  # v10.0: maxItems explícito para Guided Decoding
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
    
    v9.0: name é obrigatório (não-null) para evitar objetos vazios em service_details.
    v9.1: deliverables reduzido para 20 itens
    """
    name: str = Field(..., description="Nome do serviço (obrigatório para evitar objetos vazios)")
    description: Optional[str] = Field(None, description="Descrição do serviço")
    methodology: Optional[str] = Field(None, description="Metodologia utilizada")
    deliverables: List[str] = Field(
        default_factory=list, 
        max_length=20,  # v9.1: Reduzido de 30 → 20
        description="Entregáveis ÚNICOS do serviço (sem duplicatas, máx. 20)",
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
        max_length=80,  # v10.0: Alinhado com Guided Decoding (hard cap)
        description=(
            "PRODUTOS ESPECÍFICOS ÚNICOS: nomes, modelos, códigos, versões, medidas. "
            "Máximo 80 itens por categoria. Cada item deve aparecer APENAS UMA VEZ. "
            "Não repita variações do mesmo padrão."
        ),
        json_schema_extra={"uniqueItems": True, "maxItems": 80, "minItems": 0}  # v10.0: maxItems explícito para Guided Decoding
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
    """Produtos e serviços oferecidos pela empresa.
    
    v9.1: Caps reduzidos para reduzir espaço de degeneração e melhorar latência
    """
    products: List[str] = Field(
        default_factory=list, 
        max_length=60,  # v10.0: Alinhado com Guided Decoding
        description="Lista ÚNICA de produtos gerais. Máximo 60 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 60}  # v10.0: maxItems explícito
    )
    product_categories: List[ProductCategory] = Field(
        default_factory=list, 
        max_length=40,  # v10.0: Alinhado com Guided Decoding
        description="Categorias de produtos com itens específicos. Máximo 40 categorias.",
        json_schema_extra={"maxItems": 40}  # v10.0: maxItems explícito
    )
    services: List[str] = Field(
        default_factory=list, 
        max_length=60,  # v10.0: Alinhado com Guided Decoding
        description="Lista ÚNICA de serviços. Máximo 60 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 60}  # v10.0: maxItems explícito
    )
    service_details: List[ServiceDetail] = Field(
        default_factory=list, 
        max_length=20,  # v10.0: Alinhado com Guided Decoding
        description="Detalhes dos principais serviços. Máximo 20 serviços detalhados.",
        json_schema_extra={"maxItems": 20}  # v10.0: maxItems explícito
    )
    engagement_models: List[str] = Field(
        default_factory=list, 
        max_length=15,  # v10.0: Alinhado com Guided Decoding
        description="Modelos ÚNICOS de contratação. Máximo 15 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 15}  # v10.0: maxItems explícito
    )
    key_differentiators: List[str] = Field(
        default_factory=list, 
        max_length=20,  # v10.0: Alinhado com Guided Decoding
        description="Diferenciais ÚNICOS. Máximo 20 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 20}  # v10.0: maxItems explícito
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
    """Reputação e prova social da empresa.
    
    v9.1: Caps reduzidos para reduzir runaway generation
    """
    certifications: List[str] = Field(
        default_factory=list, 
        max_length=30,  # v10.0: Alinhado com Guided Decoding
        description="Certificações ÚNICAS (ISO, ANVISA, etc.). Máximo 30 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 30}  # v10.0: maxItems explícito
    )
    awards: List[str] = Field(
        default_factory=list, 
        max_length=20,  # v10.0: Alinhado com Guided Decoding
        description="Prêmios ÚNICOS. Máximo 20 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 20}  # v10.0: maxItems explícito
    )
    partnerships: List[str] = Field(
        default_factory=list, 
        max_length=50,  # v10.0: Alinhado com Guided Decoding
        description="Parcerias ÚNICAS. Máximo 50 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 50}  # v10.0: maxItems explícito
    )
    client_list: List[str] = Field(
        default_factory=list, 
        max_length=80,  # v10.0: Alinhado com Guided Decoding
        description="Clientes ÚNICOS de referência. Máximo 80 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 80}  # v10.0: maxItems explícito
    )
    case_studies: List[CaseStudy] = Field(
        default_factory=list, 
        max_length=15,  # v10.0: Alinhado com Guided Decoding
        description="Casos de sucesso detalhados. Máximo 15 casos.",
        json_schema_extra={"maxItems": 15}  # v10.0: maxItems explícito
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
    """Informações de contato.
    
    v9.1: Caps reduzidos para otimização
    """
    emails: List[str] = Field(
        default_factory=list, 
        max_length=10,  # v10.0: Alinhado com Guided Decoding
        description="Emails ÚNICOS de contato. Máximo 10 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 10}  # v10.0: maxItems explícito
    )
    phones: List[str] = Field(
        default_factory=list, 
        max_length=10,  # v10.0: Alinhado com Guided Decoding
        description="Telefones ÚNICOS. Máximo 10 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 10}  # v10.0: maxItems explícito
    )
    linkedin_url: Optional[str] = Field(None, description="URL completa do perfil LinkedIn da empresa")
    website_url: Optional[str] = Field(None, description="URL completa do site oficial da empresa")
    headquarters_address: Optional[str] = Field(None, description="Endereço completo da sede principal")
    locations: List[str] = Field(
        default_factory=list, 
        max_length=25,  # v10.0: Alinhado com Guided Decoding
        description="Localizações ÚNICAS (cidades, estados, unidades). Máximo 25 itens. Cada item deve aparecer apenas uma vez.",
        json_schema_extra={"uniqueItems": True, "maxItems": 25}  # v10.0: maxItems explícito
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
