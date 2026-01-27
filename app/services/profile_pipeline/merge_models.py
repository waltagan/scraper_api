from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class MergedIdentity(BaseModel):
    company_name: Optional[str] = None
    cnpj: Optional[str] = None
    tagline: Optional[str] = None
    description: Optional[str] = None
    founding_year: Optional[str] = None
    employee_count_range: Optional[str] = None


class MergedClassification(BaseModel):
    industry: Optional[str] = None
    business_model: Optional[str] = None
    target_audience: Optional[str] = None
    geographic_coverage: Optional[str] = None


class MergedContact(BaseModel):
    emails: List[str] = Field(default_factory=list)
    phones: List[str] = Field(default_factory=list)
    linkedin_url: Optional[str] = None
    website_url: Optional[str] = None
    headquarters_address: Optional[str] = None
    locations: List[str] = Field(default_factory=list)


class MergedOfferings(BaseModel):
    products: List[str] = Field(default_factory=list)
    services: List[str] = Field(default_factory=list)
    # Mantemos nomes compatíveis com CompanyProfile, mas aqui já consolidados.
    product_categories: List[str] = Field(default_factory=list)
    engagement_models: List[str] = Field(default_factory=list)
    key_differentiators: List[str] = Field(default_factory=list)


class MergedReputation(BaseModel):
    certifications: List[str] = Field(default_factory=list)
    awards: List[str] = Field(default_factory=list)
    partnerships: List[str] = Field(default_factory=list)
    client_list: List[str] = Field(default_factory=list)
    case_studies: List[str] = Field(default_factory=list)


class EvidenceEntry(BaseModel):
    url: str
    quote: str


class MergedFacts(BaseModel):
    """
    Objeto compacto resultado do merge determinístico dos FactBundles.

    Este é o único input permitido para o LLM do Estágio C.
    """

    identity: MergedIdentity = MergedIdentity()
    classification: MergedClassification = MergedClassification()
    contact: MergedContact = MergedContact()
    offerings: MergedOfferings = MergedOfferings()
    reputation: MergedReputation = MergedReputation()

    # Mapa de evidências: chave de campo → lista de {url, quote}
    evidence_map: Dict[str, List[EvidenceEntry]] = Field(default_factory=dict)

