"""
Serviço de banco de dados 100% assíncrono.
Atualizado para usar o schema busca_fornecedor.
"""
import json
import logging
from typing import List, Optional, Dict, Any
from app.core.database import get_pool
from app.schemas.profile import CompanyProfile

logger = logging.getLogger(__name__)

# Schema do banco de dados - IMPORTANTE: sempre usar explicitamente nas queries
# Usar aspas duplas para garantir que o PostgreSQL use o schema correto
SCHEMA = "busca_fornecedor"


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
            # Garantir que estamos usando o schema correto - SEMPRE explícito
            query = f"""
                INSERT INTO "{SCHEMA}".serper_results 
                    (cnpj_basico, company_name, razao_social, nome_fantasia, 
                     municipio, results_json, results_count, query_used)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
                RETURNING id
                """
            logger.info(f"🔍 [SCHEMA={SCHEMA}] Executando INSERT em serper_results")
            logger.debug(f"🔍 Query: {query[:150]}...")
            row = await conn.fetchrow(
                query,
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
            query = f"""
                SELECT * FROM "{SCHEMA}".serper_results 
                WHERE cnpj_basico = $1 
                ORDER BY created_at DESC 
                LIMIT 1
                """
            logger.debug(f"🔍 [SCHEMA={SCHEMA}] SELECT serper_results")
            row = await conn.fetchrow(
                query,
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
            # Garantir que estamos usando o schema correto - SEMPRE explícito
            query_check = f'SELECT id FROM "{SCHEMA}".website_discovery WHERE cnpj_basico = $1'
            logger.info(f"🔍 [SCHEMA={SCHEMA}] Verificando discovery")
            # Verificar se já existe registro para este CNPJ
            existing = await conn.fetchrow(
                query_check,
                cnpj_basico
            )
            
            if existing:
                # Atualizar registro existente
                query_update = f"""
                    UPDATE "{SCHEMA}".website_discovery 
                    SET website_url = $2,
                        discovery_status = $3,
                        serper_id = $4,
                        confidence_score = $5,
                        llm_reasoning = $6,
                        updated_at = NOW()
                    WHERE cnpj_basico = $1
                    RETURNING id
                    """
                logger.info(f"🔍 [SCHEMA={SCHEMA}] UPDATE website_discovery")
                row = await conn.fetchrow(
                    query_update,
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
                query_insert = f"""
                    INSERT INTO "{SCHEMA}".website_discovery 
                        (cnpj_basico, serper_id, website_url, discovery_status, 
                         confidence_score, llm_reasoning)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                    """
                logger.info(f"🔍 [SCHEMA={SCHEMA}] INSERT website_discovery")
                row = await conn.fetchrow(
                    query_insert,
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
            query = f"""
                SELECT * FROM "{SCHEMA}".website_discovery 
                WHERE cnpj_basico = $1
                """
            logger.debug(f"🔍 [SCHEMA={SCHEMA}] SELECT website_discovery")
            row = await conn.fetchrow(
                query,
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
                
                # Batch insert (muito mais eficiente) - SEMPRE com schema explícito
                query_chunks = f"""
                    INSERT INTO "{SCHEMA}".scraped_chunks 
                        (cnpj_basico, discovery_id, website_url, chunk_index, 
                         total_chunks, chunk_content, token_count, page_source)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """
                logger.info(f"🔍 [SCHEMA={SCHEMA}] Salvando {len(records)} chunks")
                await conn.executemany(
                    query_chunks,
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
            query = f"""
                SELECT * FROM "{SCHEMA}".scraped_chunks 
                WHERE cnpj_basico = $1 
                ORDER BY chunk_index ASC
                """
            logger.debug(f"🔍 [SCHEMA={SCHEMA}] SELECT scraped_chunks")
            rows = await conn.fetch(
                query,
                cnpj_basico
            )
            return [dict(row) for row in rows]
    
    # ========== BATCH SCRAPE ==========
    
    async def count_pending_scrape_companies(
        self,
        status_filter: Optional[List[str]] = None,
    ) -> int:
        """
        Conta empresas pendentes de scrape.
        Usa SET LOCAL statement_timeout para permitir query longa (300s)
        sem afetar o command_timeout global do pool (60s).
        """
        if not status_filter:
            status_filter = ['muito_alto', 'alto', 'medio']
        
        pool = await get_pool()
        async with pool.acquire() as conn:
            placeholders = ', '.join(f'${i+1}' for i in range(len(status_filter)))
            async with conn.transaction():
                await conn.execute("SET LOCAL statement_timeout = '300000'")
                total = await conn.fetchval(
                    f'SELECT COUNT(*) FROM "{SCHEMA}".website_discovery '
                    f'WHERE discovery_status IN ({placeholders}) AND website_url IS NOT NULL',
                    *status_filter
                )
            already_scraped = await conn.fetchval(
                f'SELECT COUNT(DISTINCT cnpj_basico) FROM "{SCHEMA}".scraped_chunks'
            )
            return max(0, total - already_scraped)
    
    async def get_pending_scrape_companies(
        self,
        limit: int = 5000,
        after_id: int = 0,
        status_filter: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Busca empresas pendentes de scrape via cursor-based pagination.
        Usa WHERE id > after_id (rapido via PK index) + NOT EXISTS.
        Padrao identico ao processar_medio_llm.py.
        """
        if not status_filter:
            status_filter = ['muito_alto', 'alto', 'medio']
        
        pool = await get_pool()
        async with pool.acquire() as conn:
            placeholders = ', '.join(f'${i+1}' for i in range(len(status_filter)))
            n = len(status_filter)
            query = f"""
                SELECT wd.id as wd_id, wd.cnpj_basico, wd.website_url, 
                       wd.discovery_status
                FROM "{SCHEMA}".website_discovery wd
                WHERE wd.discovery_status IN ({placeholders})
                  AND wd.website_url IS NOT NULL
                  AND wd.id > ${n + 1}
                  AND NOT EXISTS (
                    SELECT 1 FROM "{SCHEMA}".scraped_chunks sc
                    WHERE sc.cnpj_basico = wd.cnpj_basico
                  )
                ORDER BY wd.id
                LIMIT ${n + 2}
                """
            rows = await conn.fetch(query, *status_filter, after_id, limit)
            return [dict(row) for row in rows]
    
    async def save_scrape_results_mega_batch(
        self,
        records: List[tuple],
    ) -> int:
        """
        Insere chunks de multiplas empresas em uma unica transacao via copy_records_to_table.
        
        Cada record e uma tupla:
        (cnpj_basico, discovery_id, website_url, chunk_index, total_chunks, 
         chunk_content, token_count, page_source, error)
        """
        if not records:
            return 0
        
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.copy_records_to_table(
                    'scraped_chunks',
                    records=records,
                    columns=[
                        'cnpj_basico', 'discovery_id', 'website_url',
                        'chunk_index', 'total_chunks', 'chunk_content',
                        'token_count', 'page_source', 'error'
                    ],
                    schema_name=SCHEMA,
                )
                logger.info(f"✅ Mega batch: {len(records)} records inseridos")
                return len(records)
    
    # ========== COMPANY PROFILE ==========
    
    async def save_profile(
        self,
        cnpj_basico: str,
        profile: CompanyProfile,
        company_name: Optional[str] = None,
    ) -> int:
        """
        Salva perfil completo da empresa no novo esquema.
        Inclui salvamento nas tabelas auxiliares (locations, services, products, etc).
        
        Args:
            cnpj_basico: CNPJ básico da empresa
            profile: Objeto CompanyProfile (Pydantic)
            company_name: Nome da empresa (opcional, extraído do profile se None)
        
        Returns:
            ID do registro criado ou atualizado
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Transação para garantir atomicidade
            async with conn.transaction():
                # Verificar e garantir que estamos usando o schema correto
                logger.info(f"📊 Salvando perfil no schema: {SCHEMA}")
                # Extrair dados do profile
                company_name = company_name or profile.identity.company_name
                
                # VALIDAÇÃO CRÍTICA: company_name é NOT NULL no banco
                # Se não houver nome, usar fallback baseado em outros campos
                if not company_name or company_name.strip() == "":
                    # Fallback 1: Usar tagline se disponível
                    if profile.identity.tagline and profile.identity.tagline.strip():
                        company_name = profile.identity.tagline.strip()[:100]  # Limitar tamanho
                        logger.warning(
                            f"⚠️ company_name ausente para cnpj={cnpj_basico}, "
                            f"usando tagline como fallback: {company_name[:50]}..."
                        )
                    # Fallback 2: Usar primeira parte da descrição
                    elif profile.identity.description and profile.identity.description.strip():
                        desc = profile.identity.description.strip()
                        # Pegar primeiras palavras (até 50 chars)
                        company_name = desc[:50].split('.')[0].strip()
                        if not company_name:
                            company_name = desc[:50].strip()
                        logger.warning(
                            f"⚠️ company_name ausente para cnpj={cnpj_basico}, "
                            f"usando descrição como fallback: {company_name[:50]}..."
                        )
                    # Fallback 3: Usar CNPJ como último recurso
                    else:
                        company_name = f"Empresa CNPJ {cnpj_basico}"
                        logger.warning(
                            f"⚠️ company_name ausente para cnpj={cnpj_basico}, "
                            f"usando CNPJ como fallback"
                        )
                
                # SEMPRE usar cnpj_basico (das tabelas iniciais), não o extraído pelo LLM
                cnpj = cnpj_basico
                razao_social = None  # Não está no schema atual, mas pode ser adicionado
                tagline = profile.identity.tagline
                description = profile.identity.description
                industry = profile.classification.industry
                business_model = profile.classification.business_model
                target_audience = profile.classification.target_audience
                geographic_coverage = profile.classification.geographic_coverage
                
                # Founding year
                founding_year = None
                if profile.identity.founding_year:
                    try:
                        founding_year = int(profile.identity.founding_year)
                    except (ValueError, TypeError):
                        pass
                
                # Employee count (range)
                employee_count_min = None
                employee_count_max = None
                employee_count_range = profile.identity.employee_count_range
                if employee_count_range:
                    # Tentar parsear "10-50" ou similar
                    try:
                        parts = employee_count_range.split('-')
                        if len(parts) == 2:
                            employee_count_min = int(parts[0].strip())
                            employee_count_max = int(parts[1].strip())
                    except:
                        pass
                
                # Contact info
                headquarters_address = profile.contact.headquarters_address
                emails = profile.contact.emails or []
                phones = profile.contact.phones or []
                linkedin_url = profile.contact.linkedin_url
                website_url = profile.contact.website_url
                instagram_url = None  # Não está no schema atual, mas pode ser adicionado
                
                # Sources
                sources = profile.sources or []
                
                # Campos opcionais
                n_exibicoes = 0  # Default
                recebe_email = False  # Default
                
                # Converter profile para JSON string (será convertido para JSONB no SQL)
                profile_dict = profile.model_dump()
                profile_json = json.dumps(profile_dict, ensure_ascii=False)
                # full_profile: salva o perfil completo gerado
                full_profile = json.dumps(profile_dict, ensure_ascii=False)
                
                # Verificar se já existe registro - SEMPRE com schema explícito
                query_check_profile = f'SELECT id FROM "{SCHEMA}".company_profile WHERE cnpj = $1'
                logger.info(f"🔍 [SCHEMA={SCHEMA}] Verificando profile existente")
                existing = await conn.fetchrow(
                    query_check_profile,
                    cnpj
                )
                
                if existing:
                    # Atualizar registro existente - SEMPRE com schema explícito
                    query_update = f"""
                        UPDATE "{SCHEMA}".company_profile 
                        SET company_name = $2,
                            razao_social = $3,
                            tagline = $4,
                            description = $5,
                            industry = $6,
                            business_model = $7,
                            target_audience = $8,
                            geographic_coverage = $9,
                            founding_year = $10,
                            employee_count_min = $11,
                            employee_count_max = $12,
                            employee_count_range = $13,
                            headquarters_address = $14,
                            emails = $15,
                            phones = $16,
                            linkedin_url = $17,
                            website_url = $18,
                            instagram_url = $19,
                            sources = $20,
                            n_exibicoes = $21,
                            recebe_email = $22,
                            profile_json = $23::jsonb,
                            full_profile = $24::jsonb,
                            updated_at = NOW()
                        WHERE cnpj = $1
                        RETURNING id
                        """
                    logger.info(f"🔍 [SCHEMA={SCHEMA}] UPDATE company_profile")
                    row = await conn.fetchrow(
                        query_update,
                        cnpj,
                        company_name,
                        razao_social,
                        tagline,
                        description,
                        industry,
                        business_model,
                        target_audience,
                        geographic_coverage,
                        founding_year,
                        employee_count_min,
                        employee_count_max,
                        employee_count_range,
                        headquarters_address,
                        emails,
                        phones,
                        linkedin_url,
                        website_url,
                        instagram_url,
                        sources,
                        n_exibicoes,
                        recebe_email,
                        profile_json,
                        full_profile
                    )
                    company_id = row['id']
                    logger.debug(f"✅ Profile atualizado: id={company_id}, cnpj={cnpj}")
                else:
                    # Criar novo registro - SEMPRE com schema explícito
                    query_insert_profile = f"""
                        INSERT INTO "{SCHEMA}".company_profile 
                            (company_name, razao_social, cnpj, tagline, description,
                             industry, business_model, target_audience, geographic_coverage,
                             founding_year, employee_count_min, employee_count_max, employee_count_range,
                             headquarters_address, emails, phones, linkedin_url, website_url,
                             instagram_url, sources, n_exibicoes, recebe_email, profile_json, full_profile)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23::jsonb, $24::jsonb)
                        RETURNING id
                        """
                    logger.info(f"🔍 [SCHEMA={SCHEMA}] INSERT company_profile")
                    row = await conn.fetchrow(
                        query_insert_profile,
                        company_name,
                        razao_social,
                        cnpj,
                        tagline,
                        description,
                        industry,
                        business_model,
                        target_audience,
                        geographic_coverage,
                        founding_year,
                        employee_count_min,
                        employee_count_max,
                        employee_count_range,
                        headquarters_address,
                        emails,
                        phones,
                        linkedin_url,
                        website_url,
                        instagram_url,
                        sources,
                        n_exibicoes,
                        recebe_email,
                        profile_json,
                        full_profile
                    )
                    company_id = row['id']
                    logger.debug(f"✅ Profile criado: id={company_id}, cnpj={cnpj}")
                
                # Salvar dados nas tabelas auxiliares
                await self._save_profile_auxiliary_data(conn, company_id, profile)
                
                return company_id
    
    async def _save_profile_auxiliary_data(
        self,
        conn,
        company_id: int,
        profile: CompanyProfile
    ):
        """
        Salva dados nas tabelas auxiliares (locations, services, products, etc).
        
        Args:
            conn: Conexão do banco de dados
            company_id: ID da empresa
            profile: Objeto CompanyProfile
        """
        # 1. Locations - SEMPRE com schema explícito
        if profile.contact.locations:
            # Deletar locations antigas
            query_delete_locations = f'DELETE FROM "{SCHEMA}".company_location WHERE company_id = $1'
            logger.info(f"🔍 [SCHEMA={SCHEMA}] DELETE company_location")
            await conn.execute(query_delete_locations, company_id)
            # Inserir novas locations
            for location in profile.contact.locations:
                if location and location.strip():
                    query_insert_location = f'INSERT INTO "{SCHEMA}".company_location (company_id, location) VALUES ($1, $2)'
                    logger.debug(f"🔍 [SCHEMA={SCHEMA}] INSERT location: {location[:50]}")
                    await conn.execute(query_insert_location, company_id, location.strip())
        
        # 2. Services - SEMPRE com schema explícito
        if profile.offerings.service_details:
            # Deletar services antigos
            query_delete_services = f'DELETE FROM "{SCHEMA}".company_service WHERE company_id = $1'
            logger.info(f"🔍 [SCHEMA={SCHEMA}] DELETE company_service")
            await conn.execute(query_delete_services, company_id)
            # Inserir novos services
            for service in profile.offerings.service_details:
                if service.name:
                    deliverables_json = json.dumps(service.deliverables or [], ensure_ascii=False)
                    query_insert_service = f"""
                        INSERT INTO "{SCHEMA}".company_service 
                            (company_id, name, description, methodology, ideal_client_profile, deliverables)
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                        """
                    logger.debug(f"🔍 [SCHEMA={SCHEMA}] INSERT service: {service.name}")
                    await conn.execute(
                        query_insert_service,
                        company_id,
                        service.name,
                        service.description,
                        service.methodology,
                        service.ideal_client_profile,
                        deliverables_json
                    )
        
        # 3. Product Categories - SEMPRE com schema explícito
        if profile.offerings.product_categories:
            # Deletar product categories antigas
            query_delete_categories = f'DELETE FROM "{SCHEMA}".company_product_category WHERE company_id = $1'
            logger.info(f"🔍 [SCHEMA={SCHEMA}] DELETE company_product_category")
            await conn.execute(query_delete_categories, company_id)
            # Inserir novas product categories
            for category in profile.offerings.product_categories:
                if category.category_name:
                    items_json = json.dumps(category.items or [], ensure_ascii=False)
                    query_insert_category = f"""
                        INSERT INTO "{SCHEMA}".company_product_category 
                            (company_id, category_name, items)
                        VALUES ($1, $2, $3::jsonb)
                        """
                    logger.debug(f"🔍 [SCHEMA={SCHEMA}] INSERT product_category: {category.category_name}")
                    await conn.execute(
                        query_insert_category,
                        company_id,
                        category.category_name,
                        items_json
                    )
        
        # 4. Certifications - SEMPRE com schema explícito
        if profile.reputation.certifications:
            # Deletar certifications antigas
            query_delete_certs = f'DELETE FROM "{SCHEMA}".company_certification WHERE company_id = $1'
            logger.info(f"🔍 [SCHEMA={SCHEMA}] DELETE company_certification")
            await conn.execute(query_delete_certs, company_id)
            # Inserir novas certifications
            for cert in profile.reputation.certifications:
                if cert and cert.strip():
                    query_insert_cert = f'INSERT INTO "{SCHEMA}".company_certification (company_id, name) VALUES ($1, $2)'
                    logger.debug(f"🔍 [SCHEMA={SCHEMA}] INSERT certification: {cert[:50]}")
                    await conn.execute(query_insert_cert, company_id, cert.strip())
        
        # 5. Awards - SEMPRE com schema explícito
        if profile.reputation.awards:
            # Deletar awards antigos
            query_delete_awards = f'DELETE FROM "{SCHEMA}".company_award WHERE company_id = $1'
            logger.info(f"🔍 [SCHEMA={SCHEMA}] DELETE company_award")
            await conn.execute(query_delete_awards, company_id)
            # Inserir novos awards
            for award in profile.reputation.awards:
                if award and award.strip():
                    query_insert_award = f'INSERT INTO "{SCHEMA}".company_award (company_id, name) VALUES ($1, $2)'
                    logger.debug(f"🔍 [SCHEMA={SCHEMA}] INSERT award: {award[:50]}")
                    await conn.execute(query_insert_award, company_id, award.strip())
        
        # 6. Partnerships - SEMPRE com schema explícito
        if profile.reputation.partnerships:
            # Deletar partnerships antigas
            query_delete_partners = f'DELETE FROM "{SCHEMA}".company_partnership WHERE company_id = $1'
            logger.info(f"🔍 [SCHEMA={SCHEMA}] DELETE company_partnership")
            await conn.execute(query_delete_partners, company_id)
            # Inserir novas partnerships
            for partnership in profile.reputation.partnerships:
                if partnership and partnership.strip():
                    query_insert_partner = f'INSERT INTO "{SCHEMA}".company_partnership (company_id, name) VALUES ($1, $2)'
                    logger.debug(f"🔍 [SCHEMA={SCHEMA}] INSERT partnership: {partnership[:50]}")
                    await conn.execute(query_insert_partner, company_id, partnership.strip())
    
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
            query = f"""
                SELECT * FROM "{SCHEMA}".company_profile 
                WHERE cnpj = $1 OR cnpj LIKE $2
                ORDER BY updated_at DESC
                LIMIT 1
                """
            logger.debug(f"🔍 [SCHEMA={SCHEMA}] SELECT company_profile")
            row = await conn.fetchrow(
                query,
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
