"""
Serviço de banco de dados 100% assíncrono.
"""
import json
import logging
from typing import List, Optional, Dict, Any
from app.core.database import get_pool
from app.schemas.profile import CompanyProfile

logger = logging.getLogger(__name__)


class DatabaseService:
    """Serviço de CRUD assíncrono para todas as tabelas."""
    
    # ========== SERPER RESULTS ==========
    
    async def save_serper_results(
        self,
        cnpj_basico: str,
        results: List[dict],
        query_used: str,
        company_name: Optional[str] = None,
        razao_social: Optional[str] = None,
        nome_fantasia: Optional[str] = None,
        municipio: Optional[str] = None,
    ) -> int:
        """
        Salva resultados Serper e retorna ID.
        
        Args:
            cnpj_basico: CNPJ básico da empresa
            results: Lista de resultados da busca (array de dicts)
            query_used: Query usada na busca
            company_name: Nome da empresa (opcional)
            razao_social: Razão social (opcional)
            nome_fantasia: Nome fantasia (opcional)
            municipio: Município (opcional)
        
        Returns:
            ID do registro criado
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO serper_results 
                    (cnpj_basico, company_name, razao_social, nome_fantasia, 
                     municipio, results_json, results_count, query_used)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
                RETURNING id
                """,
                cnpj_basico,
                company_name,
                razao_social,
                nome_fantasia,
                municipio,
                json.dumps(results),  # Converter para JSON string e fazer cast para JSONB
                len(results),
                query_used
            )
            serper_id = row['id']
            logger.debug(f"✅ Serper results salvos: id={serper_id}, cnpj={cnpj_basico}, results={len(results)}")
            return serper_id
    
    async def get_serper_results(self, cnpj_basico: str) -> Optional[Dict[str, Any]]:
        """
        Busca resultados Serper mais recentes para um CNPJ.
        
        Args:
            cnpj_basico: CNPJ básico da empresa
        
        Returns:
            Dict com os resultados ou None se não encontrado
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM serper_results 
                WHERE cnpj_basico = $1 
                ORDER BY created_at DESC 
                LIMIT 1
                """,
                cnpj_basico
            )
            if row:
                result = dict(row)
                # Parse JSONB se for string
                if isinstance(result.get('results_json'), str):
                    result['results_json'] = json.loads(result['results_json'])
                return result
            return None
    
    # ========== WEBSITE DISCOVERY ==========
    
    async def save_discovery(
        self,
        cnpj_basico: str,
        website_url: Optional[str],
        discovery_status: str,
        serper_id: Optional[int] = None,
        confidence_score: Optional[float] = None,
        llm_reasoning: Optional[str] = None,
    ) -> int:
        """
        Salva resultado da descoberta de site.
        
        Args:
            cnpj_basico: CNPJ básico da empresa
            website_url: URL do site encontrado (None se não encontrado)
            discovery_status: Status ('found', 'not_found', 'error')
            serper_id: ID do resultado Serper relacionado (opcional)
            confidence_score: Score de confiança (opcional)
            llm_reasoning: Raciocínio do LLM (opcional)
        
        Returns:
            ID do registro criado ou atualizado
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Verificar se já existe registro para este CNPJ
            existing = await conn.fetchrow(
                "SELECT id FROM website_discovery WHERE cnpj_basico = $1",
                cnpj_basico
            )
            
            if existing:
                # Atualizar registro existente
                row = await conn.fetchrow(
                    """
                    UPDATE website_discovery 
                    SET website_url = $2,
                        discovery_status = $3,
                        serper_id = $4,
                        confidence_score = $5,
                        llm_reasoning = $6,
                        updated_at = NOW()
                    WHERE cnpj_basico = $1
                    RETURNING id
                    """,
                    cnpj_basico,
                    website_url,
                    discovery_status,
                    serper_id,
                    confidence_score,
                    llm_reasoning
                )
                discovery_id = row['id']
                logger.debug(f"✅ Discovery atualizado: id={discovery_id}, cnpj={cnpj_basico}, status={discovery_status}")
            else:
                # Criar novo registro
                row = await conn.fetchrow(
                    """
                    INSERT INTO website_discovery 
                        (cnpj_basico, serper_id, website_url, discovery_status, 
                         confidence_score, llm_reasoning)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                    """,
                    cnpj_basico,
                    serper_id,
                    website_url,
                    discovery_status,
                    confidence_score,
                    llm_reasoning
                )
                discovery_id = row['id']
                logger.debug(f"✅ Discovery criado: id={discovery_id}, cnpj={cnpj_basico}, status={discovery_status}")
            
            return discovery_id
    
    async def get_discovery(self, cnpj_basico: str) -> Optional[Dict[str, Any]]:
        """
        Busca descoberta de site para um CNPJ.
        
        Args:
            cnpj_basico: CNPJ básico da empresa
        
        Returns:
            Dict com os dados da descoberta ou None se não encontrado
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM website_discovery 
                WHERE cnpj_basico = $1
                """,
                cnpj_basico
            )
            if row:
                return dict(row)
            return None
    
    # ========== SCRAPED CHUNKS ==========
    
    async def save_chunks_batch(
        self,
        cnpj_basico: str,
        chunks: List[Any],  # Lista de objetos Chunk
        website_url: str,
        discovery_id: Optional[int] = None,
    ) -> int:
        """
        Salva múltiplos chunks em batch (transação única).
        
        Args:
            cnpj_basico: CNPJ básico da empresa
            chunks: Lista de objetos Chunk (com content, tokens, index, total_chunks, pages_included)
            website_url: URL do site
            discovery_id: ID da descoberta relacionada (opcional)
        
        Returns:
            Número de chunks salvos
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Transação para garantir atomicidade
            async with conn.transaction():
                # Preparar dados para batch insert
                records = []
                for chunk in chunks:
                    # Extrair page_source (primeira página ou todas concatenadas)
                    page_source = None
                    if hasattr(chunk, 'pages_included') and chunk.pages_included:
                        page_source = ','.join(chunk.pages_included[:5])  # Limitar a 5 URLs
                    
                    records.append((
                        cnpj_basico,
                        discovery_id,
                        website_url,
                        chunk.index,
                        chunk.total_chunks,
                        chunk.content,
                        chunk.tokens,
                        page_source
                    ))
                
                # Batch insert (muito mais eficiente)
                await conn.executemany(
                    """
                    INSERT INTO scraped_chunks 
                        (cnpj_basico, discovery_id, website_url, chunk_index, 
                         total_chunks, chunk_content, token_count, page_source)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    records
                )
                
                logger.debug(f"✅ {len(records)} chunks salvos para cnpj={cnpj_basico}")
                return len(records)
    
    async def get_chunks(self, cnpj_basico: str) -> List[Dict[str, Any]]:
        """
        Busca todos os chunks para um CNPJ, ordenados por índice.
        
        Args:
            cnpj_basico: CNPJ básico da empresa
        
        Returns:
            Lista de dicts com os dados dos chunks
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM scraped_chunks 
                WHERE cnpj_basico = $1 
                ORDER BY chunk_index ASC
                """,
                cnpj_basico
            )
            return [dict(row) for row in rows]
    
    # ========== COMPANY PROFILE ==========
    
    async def save_profile(
        self,
        cnpj_basico: str,
        profile: CompanyProfile,
        company_name: Optional[str] = None,
    ) -> int:
        """
        Salva perfil completo da empresa.
        
        Args:
            cnpj_basico: CNPJ básico da empresa
            profile: Objeto CompanyProfile (Pydantic)
            company_name: Nome da empresa (opcional, extraído do profile se None)
        
        Returns:
            ID do registro criado ou atualizado
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Extrair dados do profile
            company_name = company_name or profile.identity.company_name
            cnpj = profile.identity.cnpj or cnpj_basico
            industry = profile.classification.industry
            business_model = profile.classification.business_model
            target_audience = profile.classification.target_audience
            geographic_coverage = profile.classification.geographic_coverage
            founding_year = int(profile.identity.founding_year) if profile.identity.founding_year and profile.identity.founding_year.isdigit() else None
            
            # Extrair employee_count (range)
            employee_count_min = None
            employee_count_max = None
            if profile.identity.employee_count_range:
                # Tentar parsear "10-50" ou similar
                try:
                    parts = profile.identity.employee_count_range.split('-')
                    if len(parts) == 2:
                        employee_count_min = int(parts[0].strip())
                        employee_count_max = int(parts[1].strip())
                except:
                    pass
            
            headquarters_address = profile.contact.headquarters_address
            linkedin_url = profile.contact.linkedin_url
            website_url = profile.contact.website_url
            
            # Converter profile para JSON string (será convertido para JSONB no SQL)
            profile_json = json.dumps(profile.model_dump())
            
            # Verificar se já existe registro
            existing = await conn.fetchrow(
                "SELECT id FROM company_profile WHERE cnpj = $1",
                cnpj
            )
            
            if existing:
                # Atualizar registro existente
                row = await conn.fetchrow(
                    """
                    UPDATE company_profile 
                    SET company_name = $2,
                        industry = $3,
                        business_model = $4,
                        target_audience = $5,
                        geographic_coverage = $6,
                        founding_year = $7,
                        employee_count_min = $8,
                        employee_count_max = $9,
                        headquarters_address = $10,
                        linkedin_url = $11,
                        website_url = $12,
                        profile_json = $13::jsonb,
                        updated_at = NOW()
                    WHERE cnpj = $1
                    RETURNING id
                    """,
                    cnpj,
                    company_name,
                    industry,
                    business_model,
                    target_audience,
                    geographic_coverage,
                    founding_year,
                    employee_count_min,
                    employee_count_max,
                    headquarters_address,
                    linkedin_url,
                    website_url,
                    profile_json
                )
                company_id = row['id']
                logger.debug(f"✅ Profile atualizado: id={company_id}, cnpj={cnpj}")
            else:
                # Criar novo registro
                row = await conn.fetchrow(
                    """
                    INSERT INTO company_profile 
                        (company_name, cnpj, industry, business_model, 
                         target_audience, geographic_coverage, founding_year,
                         employee_count_min, employee_count_max, 
                         headquarters_address, linkedin_url, website_url, profile_json)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb)
                    RETURNING id
                    """,
                    company_name,
                    cnpj,
                    industry,
                    business_model,
                    target_audience,
                    geographic_coverage,
                    founding_year,
                    employee_count_min,
                    employee_count_max,
                    headquarters_address,
                    linkedin_url,
                    website_url,
                    profile_json
                )
                company_id = row['id']
                logger.debug(f"✅ Profile criado: id={company_id}, cnpj={cnpj}")
            
            return company_id
    
    async def get_profile(self, cnpj_basico: str) -> Optional[Dict[str, Any]]:
        """
        Busca perfil completo da empresa.
        
        Args:
            cnpj_basico: CNPJ básico da empresa
        
        Returns:
            Dict com os dados do perfil ou None se não encontrado
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM company_profile 
                WHERE cnpj = $1 OR cnpj LIKE $2
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                cnpj_basico,
                f"{cnpj_basico}%"
            )
            if row:
                result = dict(row)
                # Parse JSONB se for string
                if isinstance(result.get('profile_json'), str):
                    result['profile_json'] = json.loads(result['profile_json'])
                return result
            return None


# Singleton
_db_service: Optional[DatabaseService] = None


def get_db_service() -> DatabaseService:
    """
    Retorna instância singleton do DatabaseService.
    
    Returns:
        DatabaseService: Instância do serviço de banco de dados
    """
    global _db_service
    if _db_service is None:
        _db_service = DatabaseService()
    return _db_service

