from typing import List, Optional
from pydantic import BaseModel, Field

class Identity(BaseModel):
    company_name: Optional[str] = None
    cnpj: Optional[str] = Field(None, description="Brazilian tax ID if available")
    tagline: Optional[str] = None
    description: Optional[str] = None
    founding_year: Optional[str] = None
    employee_count_range: Optional[str] = None # e.g., "10-50", "100-500"

class Classification(BaseModel):
    industry: Optional[str] = None
    business_model: Optional[str] = None  # e.g., B2B, B2C, Service Provider, Distributor
    target_audience: Optional[str] = None
    geographic_coverage: Optional[str] = None # e.g., "National", "São Paulo Only"

class TeamProfile(BaseModel):
    size_range: Optional[str] = None 
    key_roles: List[str] = [] # e.g., "Engenheiros Civis", "Consultores SAP"
    team_certifications: List[str] = [] # e.g., "PMP Certified", "AWS Certified"

class ServiceDetail(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    methodology: Optional[str] = None # e.g., "Agile", "Design Thinking"
    deliverables: List[str] = [] # e.g., "Relatórios", "Blueprints"
    ideal_client_profile: Optional[str] = None 

class ProductCategory(BaseModel):
    category_name: Optional[str] = None
    items: List[str] = []

class Offerings(BaseModel):
    products: List[str] = [] 
    product_categories: List[ProductCategory] = []
    
    # Service Specifics
    services: List[str] = [] 
    service_details: List[ServiceDetail] = []
    engagement_models: List[str] = [] # e.g., "Project Based", "Retainer", "Bodyshop"
    
    key_differentiators: List[str] = []

class CaseStudy(BaseModel):
    title: Optional[str] = None
    client_name: Optional[str] = None
    industry: Optional[str] = None
    challenge: Optional[str] = None
    solution: Optional[str] = None
    outcome: Optional[str] = None

class Reputation(BaseModel):
    certifications: List[str] = [] # Company level (ISO, Anvisa)
    awards: List[str] = []
    partnerships: List[str] = [] # Technology or commercial partners
    client_list: List[str] = [] # Key clients
    case_studies: List[CaseStudy] = []

class Contact(BaseModel):
    emails: List[str] = []
    phones: List[str] = []
    linkedin_url: Optional[str] = None
    website_url: Optional[str] = None
    headquarters_address: Optional[str] = None
    locations: List[str] = [] # Branches/Filiais

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
