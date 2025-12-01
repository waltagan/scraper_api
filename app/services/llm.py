import json
import asyncio
import time
from typing import List, Dict, Any, Optional, Tuple
from openai import AsyncOpenAI, RateLimitError, APIError, APITimeoutError, BadRequestError, NotFoundError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging
import json_repair
from app.core.config import settings
from app.schemas.profile import CompanyProfile

# Configurar logger
logger = logging.getLogger(__name__)

# Semaphores individuais por provedor LLM (respeitar rate limits)
llm_semaphores = {
    # Gemini: 10M tokens/min, 10k RPM. 
    # Usamos 15 concurrency seguro.
    "Google Gemini": asyncio.Semaphore(15),      
    
    # OpenAI: 4M tokens/min, 5k RPM.
    # Usamos 10 concurrency seguro.
    "OpenAI": asyncio.Semaphore(10),             
}

# Semaphore global para throttling geral (max 20 requisições simultâneas ao total)
# Limitado pelo servidor da aplicação, não apenas pelas APIs
llm_global_semaphore = asyncio.Semaphore(20)

# Configuração de fallback chain
FALLBACK_CHAIN = [
    ("Google Gemini", settings.GOOGLE_API_KEY, settings.GOOGLE_BASE_URL, settings.GOOGLE_MODEL),
    ("OpenAI", settings.OPENAI_API_KEY, settings.OPENAI_BASE_URL, settings.OPENAI_MODEL),
]

# Filtrar apenas provedores com chave configurada
AVAILABLE_PROVIDERS = [(name, key, url, model) for name, key, url, model in FALLBACK_CHAIN if key]

if not AVAILABLE_PROVIDERS:
    logger.error("CRITICAL: Nenhum provedor de LLM configurado! Defina pelo menos uma API key.")

# Cliente primário (atual)
client_args = {
    "api_key": settings.LLM_API_KEY,
    "base_url": settings.LLM_BASE_URL,
}

client = AsyncOpenAI(**client_args)

SYSTEM_PROMPT = """Você é um extrator de dados B2B especializado. Gere estritamente um JSON válido correspondente ao schema abaixo.
Extraia dados do texto Markdown e PDF fornecido.

INSTRUÇÕES CRÍTICAS:
1. IDIOMA DE SAÍDA: PORTUGUÊS (BRASIL). Todo o conteúdo extraído deve estar em Português. Traduza descrições, cargos e categorias. Mantenha em inglês apenas termos técnicos globais (ex: "SaaS", "Big Data", "Machine Learning") ou nomes próprios de produtos não traduzíveis.
2. PRODUTOS vs SERVIÇOS: Distinga claramente entre produtos físicos e serviços intangíveis.
3. DETALHES DO SERVIÇO: Para os principais serviços, tente extrair 'metodologia' (como eles fazem) e 'entregáveis' (o que o cliente recebe).
4. LISTAGEM DE PRODUTOS EXAUSTIVA - CRÍTICO E OBRIGATÓRIO: 
   - Ao extrair 'product_categories', você DEVE preencher o campo 'items' de CADA categoria com TODOS os produtos individuais encontrados.
   - NUNCA deixe 'items' vazio ou como array vazio []. Se uma categoria é mencionada, você DEVE encontrar e listar os produtos específicos.
   - O QUE SÃO ITEMS: Items são PRODUTOS ESPECÍFICOS (nomes de produtos, modelos, referências, SKUs). NÃO são nomes de categorias, NÃO são marcas isoladas, NÃO são descrições genéricas de categorias.
   - EXEMPLO CORRETO: Se o texto menciona "Fios e Cabos" e lista "Cabo 1KV HEPR", "Cabo 1KV LSZH", "Cabo Flex 750V", então 'items' DEVE ser ["Cabo 1KV HEPR", "Cabo 1KV LSZH", "Cabo Flex 750V"].
   - EXEMPLO INCORRETO: NÃO faça {"category_name": "Fios e Cabos", "items": ["Fios e Cabos", "Automação"]} - esses são nomes de categorias, não produtos.
   - EXEMPLO INCORRETO: NÃO faça {"category_name": "Marcas", "items": ["Philips", "Siemens"]} - marcas isoladas não são produtos. Se houver "Luminária Philips XYZ", extraia "Luminária Philips XYZ" como item.
   - PROCURE no texto: nomes de produtos, modelos, referências, SKUs, códigos de produto, listas de itens, catálogos, especificações técnicas.
   - Se você criar uma categoria, você DEVE preencher seus items com produtos encontrados no texto. Se não encontrar produtos específicos, NÃO crie a categoria.
   - NÃO crie categorias genéricas como "Outras Categorias", "Marcas", "Geral" - apenas categorias específicas mencionadas no conteúdo.
   - Extraia TUDO que encontrar: nomes completos de produtos, modelos, marcas quando parte do nome do produto, referências. NÃO resuma, NÃO filtre por "qualidade".
5. PROVA SOCIAL: Extraia Estudos de Caso específicos, Nomes de Clientes e Certificações. Estes são de alta prioridade.
6. ENGAJAMENTO: Procure como eles vendem (Mensalidade? Por Projeto? Alocação de equipe?).
7. CONSOLIDAÇÃO: Se receber múltiplos fragmentos de conteúdo, consolide as informações sem duplicar. Priorize informações mais detalhadas e completas.

Se um campo não for encontrado, use null ou lista vazia. NÃO gere blocos de código markdown (```json). Gere APENAS a string JSON bruta.

Schema (Mantenha as chaves em inglês, valores em Português):
{
  "identity": { 
    "company_name": "string", 
    "cnpj": "string",
    "tagline": "string", 
    "description": "string", 
    "founding_year": "string",
    "employee_count_range": "string"
  },
  "classification": { 
    "industry": "string", 
    "business_model": "string", 
    "target_audience": "string",
    "geographic_coverage": "string"
  },
  "team": {
    "size_range": "string",
    "key_roles": ["string"],
    "team_certifications": ["string"]
  },
  "offerings": { 
    "products": ["string"],
    "product_categories": [
        { "category_name": "string", "items": ["string"] }
    ],
    "services": ["string"], 
    "service_details": [
        { 
          "name": "string", 
          "description": "string", 
          "methodology": "string", 
          "deliverables": ["string"],
          "ideal_client_profile": "string"
        }
    ],
    "engagement_models": ["string"],
    "key_differentiators": ["string"] 
  },
  "reputation": {
    "certifications": ["string"],
    "awards": ["string"],
    "partnerships": ["string"],
    "client_list": ["string"],
    "case_studies": [
        {
          "title": "string",
          "client_name": "string",
          "industry": "string",
          "challenge": "string",
          "solution": "string",
          "outcome": "string"
        }
    ]
  },
  "contact": { 
    "emails": ["string"], 
    "phones": ["string"], 
    "linkedin_url": "string", 
    "website_url": "string",
    "headquarters_address": "string",
    "locations": ["string"]
  }
}
"""

# --- UTILS ---

def estimate_tokens(text: str, include_overhead: bool = True) -> int:
    """
    Estima a quantidade de tokens em um texto.
    Aproximação melhorada para português e conteúdo HTML/Markdown:
    - 1 token ≈ 2.5 caracteres (mais conservador que 4)
    - include_overhead: Se True, adiciona overhead do prompt do sistema (~50k tokens)
    """
    base_tokens = len(text) // 2.5  # Melhor para português
    
    if include_overhead:
        system_prompt_tokens = 50000  # Overhead do SYSTEM_PROMPT
        return int(base_tokens + system_prompt_tokens)
    
    return int(base_tokens)

def chunk_content(text: str, max_tokens: int = 500_000) -> List[str]:
    """
    Divide o conteúdo em chunks respeitando o limite de tokens.
    NOVA ESTRATÉGIA OTIMIZADA: Agrupamento Inteligente (Smart Chunking).
    - Agrupa múltiplas páginas pequenas em um único chunk para reduzir overhead de requisições.
    - Mantém páginas processadas isoladamente se forem muito grandes.
    - Só divide uma página se ela exceder o limite de tokens
    
    max_tokens padrão: 500k (50% do limite do Gemini de 1.048M)
    """
    # Separar por marcadores de página
    page_markers = text.split("--- PAGE START:")
    raw_pages = []
    
    for i, page in enumerate(page_markers):
        if i == 0 and not page.strip():
            continue  # Pular chunk vazio inicial
        
        # Construir conteúdo da página com marcador
        page_content = "--- PAGE START:" + page if i > 0 else page
        page_tokens = estimate_tokens(page_content)
        page_chars = len(page_content)
        
        # Se a página individual excede o limite, ela deve ser tratada separadamente (e dividida se necessário)
        if page_tokens > max_tokens:
            logger.warning(f"⚠️ Página {i+1} muito grande ({page_tokens:,} tokens, {page_chars:,} chars), dividindo em partes...")
            page_chunks = _split_large_page(page_content, max_tokens)
            raw_pages.extend(page_chunks)
            logger.info(f"  📄 Página {i+1} dividida em {len(page_chunks)} partes")
        else:
            raw_pages.append(page_content)
            
    # Agrupar páginas em chunks maiores
    # Alvo: ~20k tokens por chunk (balanceado para evitar "Lost in the Middle")
    # Reduzido de 100k para 20k para garantir que o modelo capture detalhes de todos os itens
    GROUP_TARGET_TOKENS = 20_000
    
    grouped_chunks = []
    current_group = ""
    current_tokens = 0
    
    logger.info(f"Agrupando {len(raw_pages)} páginas em chunks (Alvo: {GROUP_TARGET_TOKENS} tokens)...")
    
    for page in raw_pages:
        # Usar contagem de tokens SEM overhead para agrupar conteúdo
        # O overhead do system prompt será adicionado apenas uma vez por chunk final
        page_tokens = estimate_tokens(page, include_overhead=False)
        
        # Se adicionar a página atual ultrapassa o alvo E já temos conteúdo no grupo...
        # (Se o grupo está vazio, aceitamos a página mesmo que seja grande, desde que < max_tokens global)
        if current_tokens + page_tokens > GROUP_TARGET_TOKENS and current_group:
            grouped_chunks.append(current_group)
            current_group = page
            current_tokens = page_tokens
        else:
            if current_group:
                current_group += "\n\n" + page
            else:
                current_group = page
            current_tokens += page_tokens
            
    if current_group:
        grouped_chunks.append(current_group)
    
    logger.info(f"✅ Conteúdo consolidado em {len(grouped_chunks)} chunks (era {len(raw_pages)} páginas)")
    return grouped_chunks

def _split_large_page(page_content: str, max_tokens: int) -> List[str]:
    """
    Divide uma página muito grande em múltiplos chunks menores.
    Tenta dividir por parágrafos ou linhas para manter contexto.
    Usa margem de segurança de 80% do max_tokens para evitar exceder limites.
    """
    # Margem de segurança: usar 80% do limite para garantir que não exceda
    safe_max_tokens = int(max_tokens * 0.8)
    chunks = []
    current_chunk = ""
    current_tokens = 0
    
    # Tentar dividir por parágrafos duplos primeiro (melhor contexto)
    paragraphs = page_content.split('\n\n')
    
    # Se não houver parágrafos duplos, dividir por linhas
    if len(paragraphs) == 1:
        paragraphs = page_content.split('\n')
    
    for para in paragraphs:
        para_with_sep = para + ('\n\n' if '\n\n' in page_content else '\n')
        para_tokens = estimate_tokens(para_with_sep)
        
        # Se um parágrafo individual excede o limite, dividir por linhas
        if para_tokens > safe_max_tokens:
            logger.warning(f"⚠️ Parágrafo muito grande ({para_tokens} tokens), dividindo por linhas...")
            para_lines = para.split('\n')
            for line in para_lines:
                line_with_newline = line + '\n'
                line_tokens = estimate_tokens(line_with_newline)
                
                # Se uma linha excede o limite, truncar
                if line_tokens > safe_max_tokens:
                    logger.warning(f"⚠️ Linha muito grande ({line_tokens} tokens), truncando...")
                    max_chars = int(safe_max_tokens * 2.5)  # 2.5 chars por token
                    truncated = line[:max_chars]
                    if current_chunk:
                        chunks.append(current_chunk)
                        current_chunk = ""
                        current_tokens = 0
                    chunks.append(truncated)
                    continue
                
                # Se adicionar esta linha exceder o limite, finalizar chunk atual
                if current_tokens + line_tokens > safe_max_tokens:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = line_with_newline
                    current_tokens = line_tokens
                else:
                    current_chunk += line_with_newline
                    current_tokens += line_tokens
            continue
        
        # Se adicionar este parágrafo exceder o limite, finalizar chunk atual
        if current_tokens + para_tokens > safe_max_tokens:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = para_with_sep
            current_tokens = para_tokens
        else:
            current_chunk += para_with_sep
            current_tokens += para_tokens
    
    # Adicionar último chunk
    if current_chunk:
        chunks.append(current_chunk)
    
    # Validar que todos os chunks estão dentro do limite
    for i, chunk in enumerate(chunks):
        chunk_tokens = estimate_tokens(chunk)
        if chunk_tokens > max_tokens:
            logger.warning(f"⚠️ Chunk {i+1} ainda excede limite ({chunk_tokens} > {max_tokens} tokens), truncando...")
            max_chars = int(max_tokens * 2.5)
            chunks[i] = chunk[:max_chars]
    
    return chunks

def merge_profiles(profiles: List[CompanyProfile]) -> CompanyProfile:
    """
    Consolida múltiplos perfis parciais em um único perfil completo.
    Prioriza informações mais completas e remove duplicatas.
    Remove profiles None antes de processar.
    """
    logger.info(f"🔄 Iniciando merge de {len(profiles)} perfis")
    
    # Filtrar profiles None ou inválidos
    valid_profiles = [p for p in profiles if p is not None and isinstance(p, CompanyProfile)]
    invalid_count = len(profiles) - len(valid_profiles)
    
    if invalid_count > 0:
        logger.warning(f"⚠️ {invalid_count} perfis inválidos/None foram filtrados")
    
    if not valid_profiles:
        logger.warning("❌ Nenhum profile válido para mergear, retornando perfil vazio")
        return CompanyProfile()
    
    if len(valid_profiles) == 1:
        logger.info("ℹ️ Apenas 1 perfil válido, retornando sem merge")
        return valid_profiles[0]
    
    # Analisar dados antes do merge
    logger.info(f"📊 Analisando {len(valid_profiles)} perfis válidos antes do merge:")
    for i, profile in enumerate(valid_profiles):
        p_dict = profile.model_dump()
        filled_fields = sum(1 for k, v in p_dict.items() 
                          if v and (isinstance(v, dict) and any(v.values()) or isinstance(v, list) and len(v) > 0))
        logger.info(f"  Perfil {i+1}: {filled_fields} campos preenchidos")
        if filled_fields > 0:
            # Mostrar quais campos têm dados
            for key, value in p_dict.items():
                if value and (isinstance(value, dict) and any(v for v in value.values() if v) or isinstance(value, list) and len(value) > 0):
                    logger.debug(f"    - {key}: {len(value) if isinstance(value, list) else 'objeto com dados'}")
    
    # Escolher perfil mais completo como base
    # IMPORTANTE: Todos os perfis serão mergeados depois, então a escolha do base
    # apenas determina qual será o ponto de partida. Não perdemos informações.
    def count_filled_fields(profile_dict: dict) -> int:
        """Conta quantos campos têm dados preenchidos"""
        count = 0
        for key, value in profile_dict.items():
            if value and (isinstance(value, dict) and any(v for v in value.values() if v) or isinstance(value, list) and len(value) > 0):
                count += 1
        return count
    
    def score_profile_completeness(profile_dict: dict) -> int:
        """Score mais sofisticado: conta campos + itens em listas + comprimento de textos"""
        score = 0
        for key, value in profile_dict.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_value:
                        if isinstance(sub_value, list):
                            score += len(sub_value)  # Mais itens = mais completo
                        elif isinstance(sub_value, str):
                            score += len(sub_value) // 10  # Textos maiores = mais completo
                        else:
                            score += 1
            elif isinstance(value, list) and len(value) > 0:
                score += len(value)
            elif value:
                score += 1
        return score
    
    # Encontrar perfil mais completo usando score sofisticado
    profiles_dicts = [p.model_dump() for p in valid_profiles]
    base_idx = max(range(len(profiles_dicts)), key=lambda i: score_profile_completeness(profiles_dicts[i]))
    merged = profiles_dicts[base_idx].copy()
    base_score = score_profile_completeness(merged)
    logger.info(f"📌 Usando perfil {base_idx+1} como base (score de completude: {base_score})")
    
    # Mergear outros perfis
    for i, profile in enumerate(valid_profiles):
        if i == base_idx:
            continue  # Pular o perfil base
        
        p_dict = profile.model_dump()
        profile_num = i + 1
        logger.debug(f"🔄 Mergeando perfil {profile_num}/{len(valid_profiles)}")
        
        # Mergear campos de texto de forma inteligente
        # CRÍTICO: Descrições podem começar em um chunk e terminar em outro
        # Precisamos detectar se são complementares e concatenar, não apenas escolher uma
        def are_texts_complementary(text1: str, text2: str, similarity_threshold: float = 0.3) -> bool:
            """
            Detecta se dois textos são complementares (não duplicados).
            Se houver sobreposição significativa, são duplicados.
            Se forem muito diferentes, podem ser complementares.
            """
            if not text1 or not text2:
                return False
            
            text1_lower = text1.lower().strip()
            text2_lower = text2.lower().strip()
            
            # Se um está contido no outro, são duplicados
            if text1_lower in text2_lower or text2_lower in text1_lower:
                return False
            
            # Calcular similaridade simples (palavras em comum)
            words1 = set(text1_lower.split())
            words2 = set(text2_lower.split())
            if len(words1) == 0 or len(words2) == 0:
                return False
            
            common_words = words1 & words2
            similarity = len(common_words) / max(len(words1), len(words2))
            
            # Se similaridade < threshold, são complementares
            return similarity < similarity_threshold
        
        def merge_text_fields(current: Optional[str], new: Optional[str], field_name: str) -> str:
            """
            Merge inteligente de campos de texto:
            1. Se current vazio, usar new
            2. Se new vazio, manter current
            3. Se são complementares, concatenar
            4. Se são duplicados ou similares, usar o mais longo/completo
            """
            if not new:
                return current or ""
            if not current:
                return new
            
            # Campos que podem ser concatenados (descrições, metodologias)
            concatenatable_fields = ["description", "methodology", "tagline"]
            
            if field_name in concatenatable_fields:
                if are_texts_complementary(current, new):
                    # Textos complementares: concatenar
                    merged_text = f"{current.strip()}. {new.strip()}"
                    logger.debug(f"  🔗 Concatenado campo '{field_name}': textos complementares detectados")
                    return merged_text
                else:
                    # Textos similares/duplicados: usar o mais longo
                    if len(new) > len(current):
                        logger.debug(f"  📝 Substituído campo '{field_name}': novo texto é mais longo ({len(new)} vs {len(current)} chars)")
                        return new
                    else:
                        return current
            else:
                # Campos não-concatenáveis: usar o mais longo ou mais completo
                if len(new) > len(current):
                    return new
                return current
        
        # Mergear campos simples com merge inteligente
        for section in ["identity", "classification", "team", "contact"]:
            if section in merged and section in p_dict:
                for key, value in p_dict[section].items():
                    if not value:
                        continue
                    
                    current_value = merged[section].get(key)
                    field_path = f"{section}.{key}"
                    
                    if isinstance(value, str) and isinstance(current_value, str):
                        # Campo de texto: usar merge inteligente
                        merged[section][key] = merge_text_fields(current_value, value, key)
                    elif value and not current_value:
                        # Campo não-texto: usar se current vazio
                        merged[section][key] = value
                    elif isinstance(value, str) and len(value) > len(str(current_value or "")):
                        # Campo texto novo é mais longo
                        merged[section][key] = value
        
        # Mergear listas (união sem duplicatas)
        if "offerings" in merged and "offerings" in p_dict:
            merged["offerings"]["products"] = list(set(merged["offerings"].get("products", []) + p_dict["offerings"].get("products", [])))
            merged["offerings"]["services"] = list(set(merged["offerings"].get("services", []) + p_dict["offerings"].get("services", [])))
            merged["offerings"]["engagement_models"] = list(set(merged["offerings"].get("engagement_models", []) + p_dict["offerings"].get("engagement_models", [])))
            merged["offerings"]["key_differentiators"] = list(set(merged["offerings"].get("key_differentiators", []) + p_dict["offerings"].get("key_differentiators", [])))
            
            # Mergear service_details: se serviço já existe, fazer merge dos campos
            service_dict = {s["name"]: s for s in merged["offerings"].get("service_details", [])}
            
            for service in p_dict["offerings"].get("service_details", []):
                service_name = service.get("name")
                if not service_name or not isinstance(service_name, str):
                    logger.warning(f"  ⚠️ Serviço sem nome válido ignorado: {service}")
                    continue
                
                if service_name in service_dict:
                    # Serviço já existe: fazer merge inteligente dos campos
                    existing = service_dict[service_name]
                    # Mergear description (usar merge inteligente - pode concatenar se complementares)
                    existing["description"] = merge_text_fields(
                        existing.get("description"), 
                        service.get("description"), 
                        "description"
                    )
                    # Mergear methodology (usar merge inteligente)
                    existing["methodology"] = merge_text_fields(
                        existing.get("methodology"), 
                        service.get("methodology"), 
                        "methodology"
                    )
                    # Mergear deliverables (união sem duplicatas)
                    existing_deliverables = set(existing.get("deliverables", []))
                    new_deliverables = set(service.get("deliverables", []))
                    existing["deliverables"] = list(existing_deliverables | new_deliverables)
                    # Mergear ideal_client_profile (usar merge inteligente)
                    existing["ideal_client_profile"] = merge_text_fields(
                        existing.get("ideal_client_profile"), 
                        service.get("ideal_client_profile"), 
                        "ideal_client_profile"
                    )
                    logger.debug(f"  🔄 Mergeado serviço '{service_name}': {len(existing.get('deliverables', []))} deliverables")
                else:
                    # Novo serviço: adicionar
                    service_dict[service_name] = service.copy()
                    logger.debug(f"  ➕ Novo serviço adicionado: '{service_name}'")
            
            # Atualizar merged com os serviços modificados
            merged["offerings"]["service_details"] = list(service_dict.values())
            
            # Mergear product_categories: se categoria já existe, fazer merge dos items
            # Criar dict indexado por nome para acesso rápido
            cat_dict = {c["category_name"]: c for c in merged["offerings"].get("product_categories", [])}
            
            for cat in p_dict["offerings"].get("product_categories", []):
                cat_name = cat.get("category_name")
                if not cat_name or not isinstance(cat_name, str):
                    logger.warning(f"  ⚠️ Categoria sem nome válido ignorada: {cat}")
                    continue
                
                if cat_name in cat_dict:
                    # Categoria já existe: fazer merge dos items (união sem duplicatas)
                    existing_items = set(cat_dict[cat_name].get("items", []))
                    new_items = set(cat.get("items", []))
                    merged_items = list(existing_items | new_items)  # União de sets
                    cat_dict[cat_name]["items"] = merged_items
                    logger.debug(f"  🔄 Mergeado items da categoria '{cat_name}': {len(existing_items)} + {len(new_items)} = {len(merged_items)} items")
                else:
                    # Nova categoria: adicionar
                    cat_dict[cat_name] = cat.copy()  # Fazer cópia para não modificar original
                    logger.debug(f"  ➕ Nova categoria adicionada: '{cat_name}' com {len(cat.get('items', []))} items")
            
            # Atualizar merged com as categorias modificadas
            merged["offerings"]["product_categories"] = list(cat_dict.values())
        
        # Mergear reputation
        if "reputation" in merged and "reputation" in p_dict:
            merged["reputation"]["certifications"] = list(set(merged["reputation"].get("certifications", []) + p_dict["reputation"].get("certifications", [])))
            merged["reputation"]["awards"] = list(set(merged["reputation"].get("awards", []) + p_dict["reputation"].get("awards", [])))
            merged["reputation"]["partnerships"] = list(set(merged["reputation"].get("partnerships", []) + p_dict["reputation"].get("partnerships", [])))
            merged["reputation"]["client_list"] = list(set(merged["reputation"].get("client_list", []) + p_dict["reputation"].get("client_list", [])))
            
            # Mergear case studies: se case study já existe, fazer merge dos campos
            case_dict = {cs["title"]: cs for cs in merged["reputation"].get("case_studies", [])}
            
            for case in p_dict["reputation"].get("case_studies", []):
                case_title = case.get("title")
                if not case_title or not isinstance(case_title, str):
                    logger.warning(f"  ⚠️ Case study sem título válido ignorado: {case}")
                    continue
                
                if case_title in case_dict:
                    # Case study já existe: fazer merge inteligente dos campos
                    existing = case_dict[case_title]
                    # Campos de texto que podem ser concatenados
                    text_fields = ["challenge", "solution", "outcome"]
                    # Campos simples (não concatenáveis)
                    simple_fields = ["client_name", "industry"]
                    
                    # Mergear campos de texto com merge inteligente
                    for field in text_fields:
                        if case.get(field):
                            existing[field] = merge_text_fields(
                                existing.get(field), 
                                case.get(field), 
                                field
                            )
                    
                    # Mergear campos simples (usar o mais longo se ambos existirem)
                    for field in simple_fields:
                        if case.get(field) and (not existing.get(field) or len(str(case[field])) > len(str(existing.get(field, "")))):
                            existing[field] = case[field]
                    
                    logger.debug(f"  🔄 Mergeado case study '{case_title}'")
                else:
                    # Novo case study: adicionar
                    case_dict[case_title] = case.copy()
                    logger.debug(f"  ➕ Novo case study adicionado: '{case_title}'")
            
            # Atualizar merged com os case studies modificados
            merged["reputation"]["case_studies"] = list(case_dict.values())
        
        # Mergear sources (união sem duplicatas, preservando ordem)
        if "sources" in merged and "sources" in p_dict:
            existing_sources = set(merged.get("sources", []))
            new_sources = set(p_dict.get("sources", []))
            # Preservar ordem: primeiro os existentes, depois os novos
            merged["sources"] = list(merged.get("sources", [])) + [s for s in p_dict.get("sources", []) if s not in existing_sources]
    
    # Validação e limpeza final antes de criar CompanyProfile
    # Garantir que todas as listas são válidas
    if "offerings" in merged and isinstance(merged["offerings"], dict):
        offerings = merged["offerings"]
        # Remover strings vazias de listas
        for field in ["products", "services", "engagement_models", "key_differentiators"]:
            if isinstance(offerings.get(field), list):
                offerings[field] = [item for item in offerings[field] if isinstance(item, str) and item.strip()]
        
        # Validar product_categories: remover apenas categorias que são claramente metadados/erros estruturais
        # MANTER categorias sem items - se o fornecedor mencionou a categoria, é informação válida
        # NÃO filtrar items por "qualidade" - se foi extraído, deve ser mantido
        if isinstance(offerings.get("product_categories"), list):
            valid_cats = []
            invalid_structure_cats = []
            
            # Categorias que são claramente metadados/erros estruturais (não categorias reais de produtos)
            invalid_category_names = {
                "outras categorias", "outras", "marcas", "marca", "geral", "diversos", 
                "outros", "categorias", "categoria", "produtos", "produto"
            }
            
            for cat in offerings["product_categories"]:
                if not isinstance(cat, dict) or not cat.get("category_name"):
                    continue
                
                cat_name = cat.get("category_name", "").strip().lower()
                
                # Remover apenas categorias que são claramente metadados/erros estruturais
                if cat_name in invalid_category_names:
                    invalid_structure_cats.append(cat.get("category_name"))
                    logger.debug(f"  🗑️ Categoria inválida (metadado) removida: '{cat.get('category_name')}'")
                    continue
                
                # Garantir que items é uma lista válida (mesmo que vazia)
                if not isinstance(cat.get("items"), list):
                    cat["items"] = []
                else:
                    # Filtrar apenas strings vazias (não filtrar por "qualidade")
                    cat["items"] = [item for item in cat["items"] if isinstance(item, str) and item.strip()]
                
                # MANTER a categoria mesmo se items estiver vazio - é informação válida do fornecedor
                valid_cats.append(cat)
            
            if invalid_structure_cats:
                logger.info(f"🗑️ {len(invalid_structure_cats)} categorias inválidas (metadados) removidas: {invalid_structure_cats}")
            offerings["product_categories"] = valid_cats
        
        # Validar service_details
        if isinstance(offerings.get("service_details"), list):
            valid_services = []
            for service in offerings["service_details"]:
                if isinstance(service, dict) and service.get("name"):
                    if isinstance(service.get("deliverables"), list):
                        service["deliverables"] = [d for d in service["deliverables"] if isinstance(d, str) and d.strip()]
                    valid_services.append(service)
            offerings["service_details"] = valid_services
    
    # Validar reputation
    if "reputation" in merged and isinstance(merged["reputation"], dict):
        reputation = merged["reputation"]
        for field in ["certifications", "awards", "partnerships", "client_list"]:
            if isinstance(reputation.get(field), list):
                reputation[field] = [item for item in reputation[field] if isinstance(item, str) and item.strip()]
        
        # Validar case_studies
        if isinstance(reputation.get("case_studies"), list):
            valid_cases = []
            for case in reputation["case_studies"]:
                if isinstance(case, dict) and case.get("title"):
                    valid_cases.append(case)
            reputation["case_studies"] = valid_cases
    
    # Validar contact
    if "contact" in merged and isinstance(merged["contact"], dict):
        contact = merged["contact"]
        for field in ["emails", "phones", "locations"]:
            if isinstance(contact.get(field), list):
                contact[field] = [item for item in contact[field] if isinstance(item, str) and item.strip()]
    
    # Validar sources
    if isinstance(merged.get("sources"), list):
        merged["sources"] = [s for s in merged["sources"] if isinstance(s, str) and s.strip()]
    
    # Analisar resultado final do merge
    filled_fields = sum(1 for k, v in merged.items() 
                      if v and (isinstance(v, dict) and any(v.values()) or isinstance(v, list) and len(v) > 0))
    logger.info(f"✅ Merge concluído: {filled_fields} campos preenchidos no perfil final")
    
    # Estatísticas detalhadas
    if "offerings" in merged and isinstance(merged["offerings"], dict):
        offerings = merged["offerings"]
        total_products = len(offerings.get("products", []))
        total_categories = len(offerings.get("product_categories", []))
        categories_with_items = sum(1 for cat in offerings.get("product_categories", []) if cat.get("items"))
        total_items = sum(len(cat.get("items", [])) for cat in offerings.get("product_categories", []))
        logger.info(f"📦 Offerings: {total_products} produtos, {total_categories} categorias ({categories_with_items} com items, {total_items} items totais)")
    
    if filled_fields == 0:
        logger.warning("⚠️ ATENÇÃO: Perfil final está completamente vazio após merge!")
        logger.debug(f"📋 Estrutura do perfil final: {json.dumps(merged, indent=2, ensure_ascii=False)[:1000]}")
    else:
        # Mostrar quais campos têm dados
        for key, value in merged.items():
            if value and (isinstance(value, dict) and any(v for v in value.values() if v) or isinstance(value, list) and len(value) > 0):
                logger.info(f"  ✅ {key}: {len(value) if isinstance(value, list) else 'objeto com dados'}")
    
    try:
        return CompanyProfile(**merged)
    except Exception as e:
        logger.error(f"❌ Erro ao criar CompanyProfile após merge: {e}")
        logger.error(f"📋 Dados problemáticos: {json.dumps(merged, indent=2, ensure_ascii=False)[:2000]}")
        raise e

# --- CORE FUNCTIONS ---

@retry(
    retry=retry_if_exception_type((RateLimitError, APIError, APITimeoutError)),
    wait=wait_exponential(multiplier=1, min=2, max=120),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
def normalize_llm_response(data: Any) -> dict:
    """
    Normaliza e valida a resposta do LLM para garantir compatibilidade com CompanyProfile.
    Corrige:
    - Arrays retornados ao invés de objetos
    - Campos None que deveriam ser listas vazias
    - Objetos aninhados com valores None
    """
    # Validar se é um objeto (não array)
    if isinstance(data, list):
        logger.warning(f"LLM retornou array ao invés de objeto. Tentando extrair primeiro item...")
        if len(data) > 0 and isinstance(data[0], dict):
            data = data[0]
            logger.info("✅ Array convertido para objeto (primeiro item extraído)")
        else:
            logger.error(f"❌ Array vazio ou inválido. Tipo do primeiro item: {type(data[0]) if len(data) > 0 else 'N/A'}")
            raise ValueError("LLM retornou array vazio ou inválido")
    
    if not isinstance(data, dict):
        logger.error(f"❌ Tipo inválido recebido: {type(data)}. Esperado: dict")
        raise ValueError(f"LLM retornou tipo inválido: {type(data)}. Esperado dict, recebido {type(data).__name__}")
    
    # Garantir que campos de lista nunca sejam None
    # 1. TeamProfile
    if "team" in data:
        if not isinstance(data["team"], dict):
            data["team"] = {}
        team = data["team"]
        if team.get("key_roles") is None:
            team["key_roles"] = []
        if team.get("team_certifications") is None:
            team["team_certifications"] = []
    
    # 2. Offerings
    if "offerings" in data:
        if not isinstance(data["offerings"], dict):
            data["offerings"] = {}
        offerings = data["offerings"]
        
        # Listas simples
        for field in ["products", "services", "engagement_models", "key_differentiators"]:
            if offerings.get(field) is None:
                offerings[field] = []
            elif not isinstance(offerings[field], list):
                logger.warning(f"⚠️ Campo '{field}' não é uma lista, convertendo...")
                offerings[field] = []
        
        # Listas de objetos
        if offerings.get("product_categories") is None:
            offerings["product_categories"] = []
        elif not isinstance(offerings["product_categories"], list):
            logger.warning(f"⚠️ product_categories não é uma lista, convertendo...")
            offerings["product_categories"] = []
        else:
            # Validar e limpar cada ProductCategory
            valid_categories = []
            for cat in offerings["product_categories"]:
                if not isinstance(cat, dict):
                    logger.warning(f"⚠️ Categoria inválida (não é dict): {cat}")
                    continue
                cat_name = cat.get("category_name")
                if not cat_name or not isinstance(cat_name, str):
                    logger.warning(f"⚠️ Categoria sem nome válido ignorada: {cat}")
                    continue
                # Garantir que items é uma lista de strings
                if cat.get("items") is None:
                    cat["items"] = []
                elif not isinstance(cat["items"], list):
                    logger.warning(f"⚠️ Items da categoria '{cat_name}' não é uma lista, convertendo...")
                    cat["items"] = []
                else:
                    # Filtrar apenas strings válidas
                    cat["items"] = [item for item in cat["items"] if isinstance(item, str) and item.strip()]
                valid_categories.append(cat)
            offerings["product_categories"] = valid_categories
        
        if offerings.get("service_details") is None:
            offerings["service_details"] = []
        elif not isinstance(offerings["service_details"], list):
            logger.warning(f"⚠️ service_details não é uma lista, convertendo...")
            offerings["service_details"] = []
        else:
            # Validar cada ServiceDetail
            valid_services = []
            for service in offerings["service_details"]:
                if not isinstance(service, dict):
                    logger.warning(f"⚠️ Serviço inválido (não é dict): {service}")
                    continue
                if not service.get("name") or not isinstance(service.get("name"), str):
                    logger.warning(f"⚠️ Serviço sem nome válido ignorado: {service}")
                    continue
                if service.get("deliverables") is None:
                    service["deliverables"] = []
                elif not isinstance(service["deliverables"], list):
                    logger.warning(f"⚠️ Deliverables do serviço '{service.get('name')}' não é uma lista, convertendo...")
                    service["deliverables"] = []
                else:
                    # Filtrar apenas strings válidas
                    service["deliverables"] = [d for d in service["deliverables"] if isinstance(d, str) and d.strip()]
                valid_services.append(service)
            offerings["service_details"] = valid_services
    
    # 3. Reputation
    if "reputation" in data:
        if not isinstance(data["reputation"], dict):
            data["reputation"] = {}
        reputation = data["reputation"]
        
        # Listas simples
        for field in ["certifications", "awards", "partnerships", "client_list"]:
            if reputation.get(field) is None:
                reputation[field] = []
        
        # Lista de CaseStudies
        if reputation.get("case_studies") is None:
            reputation["case_studies"] = []
    
    # 4. Contact
    if "contact" in data:
        if not isinstance(data["contact"], dict):
            data["contact"] = {}
        contact = data["contact"]
        for field in ["emails", "phones", "locations"]:
            if contact.get(field) is None:
                contact[field] = []
    
    # 5. Sources (nível raiz)
    if data.get("sources") is None:
        data["sources"] = []
    
    # 6. Identity e Classification (objetos obrigatórios - não podem ser None)
    if data.get("identity") is None or not isinstance(data.get("identity"), dict):
        logger.warning("⚠️ identity é None ou inválido, criando objeto vazio")
        data["identity"] = {}
    if data.get("classification") is None or not isinstance(data.get("classification"), dict):
        logger.warning("⚠️ classification é None ou inválido, criando objeto vazio")
        data["classification"] = {}
    
    # 7. Team (garantir que é objeto válido)
    if data.get("team") is None or not isinstance(data.get("team"), dict):
        data["team"] = {}
    
    # 8. Contact (garantir que é objeto válido)
    if data.get("contact") is None or not isinstance(data.get("contact"), dict):
        data["contact"] = {}
    
    # 9. Reputation (garantir que é objeto válido)
    if data.get("reputation") is None or not isinstance(data.get("reputation"), dict):
        data["reputation"] = {}
    
    # 10. Offerings (garantir que é objeto válido)
    if data.get("offerings") is None or not isinstance(data.get("offerings"), dict):
        data["offerings"] = {}
    
    return data

async def _call_llm(client: AsyncOpenAI, model: str, text_content: str) -> CompanyProfile:
    """
    Faz a chamada real ao LLM com retry automático.
    Registra tempo total de inferência do modelo.
    """
    logger.info(f"📤 Enviando requisição para {model} (tamanho do conteúdo: {len(text_content)} chars)")
    start_ts = time.perf_counter()
    
    # Se o conteúdo for muito pequeno, logar para debug
    if len(text_content) < 500:
        logger.warning(f"⚠️ Conteúdo muito pequeno ({len(text_content)} chars) - pode indicar problema de scraping")
        # Extrair URL da página se presente
        if "--- PAGE START:" in text_content:
            url_line = text_content.split("\n")[0]
            logger.warning(f"📄 URL da página: {url_line.replace('--- PAGE START:', '').strip()}")
        # Mostrar primeiras linhas do conteúdo
        preview = '\n'.join(text_content.split('\n')[:15])
        logger.warning(f"📄 Preview do conteúdo ({len(text_content)} chars):\n{preview}")
    
    # Configuração da requisição
    request_params = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analise este conteúdo e extraia os dados em Português:\n\n{text_content}"}
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }
    
    response = await client.chat.completions.create(**request_params)
    
    # Verificar se há conteúdo na resposta
    if not response.choices or not response.choices[0].message.content:
        error_msg = f"❌ {model} retornou resposta vazia (sem choices ou content)"
        logger.error(error_msg)
        logger.error(f"📊 Response object: {response}")
        raise ValueError(error_msg)
    
    raw_content = response.choices[0].message.content.strip()
    duration = time.perf_counter() - start_ts
    logger.info(
        f"[PERF] llm step=model_inference model={model} "
        f"duration={duration:.3f}s response_chars={len(raw_content)}"
    )
    
    # Verificar se conteúdo está realmente vazio
    if not raw_content or len(raw_content) < 10:
        error_msg = f"❌ {model} retornou conteúdo vazio ou muito curto ({len(raw_content)} chars)"
        logger.error(error_msg)
        logger.error(f"📄 Conteúdo recebido: '{raw_content}'")
        logger.error(f"📊 Response completo: {response}")
        raise ValueError(error_msg)
    
    logger.debug(f"📥 Resposta recebida de {model} (tamanho: {len(raw_content)} chars)")
    logger.debug(f"📄 Primeiros 200 chars da resposta: {raw_content[:200]}")
    
    # Limpar markdown se presente
    if raw_content.startswith("```json"):
        raw_content = raw_content[7:]
        logger.debug("🧹 Removido prefixo ```json")
    if raw_content.startswith("```"):
        raw_content = raw_content[3:]
        logger.debug("🧹 Removido prefixo ```")
    if raw_content.endswith("```"):
        raw_content = raw_content[:-3]
        logger.debug("🧹 Removido sufixo ```")
    
    # Parse JSON
    try:
        data = json.loads(raw_content)
        
        # Validar tipo antes de processar
        if isinstance(data, list):
            logger.warning(f"⚠️ JSON parseado é uma lista, não um objeto. Primeiro item será usado.")
            if len(data) > 0 and isinstance(data[0], dict):
                data = data[0]
                logger.info("✅ Primeiro item da lista extraído como objeto")
            else:
                raise ValueError(f"Lista vazia ou primeiro item não é um dict. Tipo: {type(data[0]) if len(data) > 0 else 'N/A'}")
        
        if not isinstance(data, dict):
            raise ValueError(f"JSON parseado não é um dict. Tipo: {type(data)}")
        
        logger.debug(f"✅ JSON parseado com sucesso. Chaves principais: {list(data.keys())}")
        
        # Verificar se há dados extraídos
        has_data = False
        for key, value in data.items():
            if value and (isinstance(value, dict) and any(v for v in value.values() if v) or isinstance(value, list) and len(value) > 0):
                has_data = True
                logger.info(f"📊 Dados encontrados em '{key}': {len(value) if isinstance(value, list) else 'objeto'}")
                break
        
        # Verificar especificamente product_categories e seus items
        if "offerings" in data and isinstance(data["offerings"], dict):
            if "product_categories" in data["offerings"]:
                categories = data["offerings"]["product_categories"]
                total_categories = len(categories) if isinstance(categories, list) else 0
                categories_with_items = 0
                total_items = 0
                if isinstance(categories, list):
                    for cat in categories:
                        if isinstance(cat, dict) and cat.get("items"):
                            items = cat.get("items", [])
                            if isinstance(items, list) and len(items) > 0:
                                categories_with_items += 1
                                total_items += len(items)
                logger.info(f"📦 Product Categories: {total_categories} categorias, {categories_with_items} com items ({total_items} items totais)")
                if categories_with_items < total_categories:
                    empty_cats = [cat.get("category_name", "?") for cat in categories if isinstance(cat, dict) and not cat.get("items")]
                    logger.warning(f"⚠️ {total_categories - categories_with_items} categorias SEM items: {empty_cats[:5]}")
        
        if not has_data:
            logger.warning(f"⚠️ Resposta do {model} não contém dados extraídos (todos os campos estão vazios)")
            logger.warning(f"📋 Estrutura completa recebida: {json.dumps(data, indent=2, ensure_ascii=False)[:1000]}")
        
        data = normalize_llm_response(data)
        logger.debug("✅ Dados normalizados com sucesso")
        
        # Validação adicional antes de criar CompanyProfile
        # Verificar se campos obrigatórios são objetos válidos (não None)
        if data.get("identity") is None or not isinstance(data.get("identity"), dict):
            logger.error(f"❌ identity inválido após normalização: {type(data.get('identity'))}")
            raise ValueError(f"identity deve ser um dict, recebido: {type(data.get('identity'))}")
        if data.get("classification") is None or not isinstance(data.get("classification"), dict):
            logger.error(f"❌ classification inválido após normalização: {type(data.get('classification'))}")
            raise ValueError(f"classification deve ser um dict, recebido: {type(data.get('classification'))}")
        
        try:
            profile = CompanyProfile(**data)
            logger.info(f"✅ CompanyProfile criado com sucesso a partir de {model}")
            return profile
        except Exception as e:
            logger.error(f"❌ Erro ao criar CompanyProfile de {model}: {e}")
            logger.error(f"📋 Dados problemáticos: {json.dumps(data, indent=2, ensure_ascii=False)[:1000]}")
            raise e
        
    except json.JSONDecodeError as e:
        logger.warning(f"⚠️ JSON padrão falhou para {model}. Tentando reparar JSON malformado...")
        logger.debug(f"❌ Erro de JSON: {e}")
        logger.debug(f"📄 Conteúdo problemático (primeiros 500 chars): {raw_content[:500]}")
        try:
            data = json_repair.loads(raw_content)
            logger.info("✅ JSON reparado com sucesso")
            
            # Validar tipo após reparo
            if isinstance(data, list):
                logger.warning(f"⚠️ JSON reparado ainda é uma lista. Primeiro item será usado.")
                if len(data) > 0 and isinstance(data[0], dict):
                    data = data[0]
                    logger.info("✅ Primeiro item da lista extraído após reparo")
                else:
                    raise ValueError(f"Lista vazia ou inválida após reparo")
            
            if not isinstance(data, dict):
                raise ValueError(f"JSON reparado não é um dict. Tipo: {type(data)}")
            
            data = normalize_llm_response(data)
            profile = CompanyProfile(**data)
            return profile
        except Exception as e2:
            logger.error(f"❌ Falha crítica no parse do JSON mesmo após reparo: {e2}")
            logger.error(f"📄 Conteúdo problemático (primeiros 500 chars): {raw_content[:500]}")
            raise e2
    except Exception as e:
        logger.error(f"❌ Erro ao validar/construir CompanyProfile de {model}: {e}")
        logger.error(f"📊 Tipo de dados recebido: {type(data)}")
        logger.error(f"📄 Dados recebidos: {str(data)[:500]}")
        raise e

async def analyze_content_with_fallback(text_content: str, provider_name: Optional[str] = None) -> CompanyProfile:
    """
    Tenta analisar o conteúdo com fallback automático entre provedores.
    Se um provedor falhar com RateLimitError, tenta o próximo.
    Usa semaphores individuais por provedor para respeitar rate limits.
    Registra tempo total da análise considerando fallback.
    """
    start_ts = time.perf_counter()
    # Throttling global
    async with llm_global_semaphore:
        # Se um provedor específico foi solicitado, tentar apenas ele
        if provider_name:
            providers_to_try = [p for p in AVAILABLE_PROVIDERS if p[0] == provider_name]
        else:
            providers_to_try = AVAILABLE_PROVIDERS
        
        last_error = None
        
        for name, key, base_url, model in providers_to_try:
            # Throttling específico do provedor
            provider_semaphore = llm_semaphores.get(name, asyncio.Semaphore(3))  # Default: 3
            
            async with provider_semaphore:
                try:
                    logger.info(f"Tentando análise com {name} ({model})...")
                    
                    # Criar cliente para este provedor
                    client_args = {"api_key": key, "base_url": base_url}
                    provider_client = AsyncOpenAI(**client_args)
                    
                    # Tentar análise
                    profile = await _call_llm(provider_client, model, text_content)
                    logger.info(f"✅ Análise bem-sucedida com {name}")
                    return profile
                    
                except RateLimitError as e:
                    logger.warning(f"⚠️ {name} rate limited: {e}")
                    last_error = e
                    continue  # Tentar próximo provedor
                    
                except BadRequestError as e:
                    logger.error(f"❌ {name} bad request (provavelmente conteúdo muito grande): {e}")
                    last_error = e
                    # Não tentar outros provedores para BadRequest, propagar o erro
                    raise e
                    
                except Exception as e:
                    logger.error(f"❌ {name} falhou com erro inesperado: {e}")
                    last_error = e
                    continue  # Tentar próximo provedor
        
        # Se chegou aqui, todos falharam
        total_duration = time.perf_counter() - start_ts
        error_msg = f"Todos os provedores LLM falharam. Último erro: {last_error}"
        logger.error(f"[PERF] llm step=analyze_content_with_fallback_all_failed duration={total_duration:.3f}s")
        logger.error(error_msg)
        raise Exception(error_msg)

async def process_chunk_with_retry(chunk: str, chunk_num: int, total_chunks: int, primary_provider: Optional[str] = None) -> Optional[CompanyProfile]:
    """
    Processa um chunk (geralmente uma página) com retry e fallback.
    Adiciona logs detalhados para rastrear extração de categorias.
    
    Estratégia:
    1. Tenta com o provedor primário designado
    2. Se falhar, tenta com outros provedores disponíveis
    3. Se todos falharem, tenta reprocessar uma vez
    4. Se ainda falhar, retorna None
    """
    # Extrair URL da página do chunk para logging
    page_url = "desconhecida"
    if "--- PAGE START:" in chunk:
        try:
            first_line = chunk.split("\n")[0]
            if "--- PAGE START:" in first_line:
                page_url = first_line.replace("--- PAGE START:", "").strip()
        except:
            pass
    
    logger.info(f"📄 Processando Chunk {chunk_num}/{total_chunks} (Página: {page_url[:80]}...)")
    # Lista de provedores para tentar (começando com o primário)
    providers_to_try = []
    if primary_provider:
        # Adicionar provedor primário primeiro
        primary = [p for p in AVAILABLE_PROVIDERS if p[0] == primary_provider]
        if primary:
            providers_to_try.append(primary[0])
        # Adicionar outros provedores como fallback
        for p in AVAILABLE_PROVIDERS:
            if p[0] != primary_provider:
                providers_to_try.append(p)
    else:
        # Sem provedor primário, tentar todos em ordem
        providers_to_try = list(AVAILABLE_PROVIDERS)
    
    # Log do conteúdo do chunk se for muito pequeno (pode indicar problema de scraping)
    chunk_size = len(chunk)
    if chunk_size < 500:
        logger.warning(f"⚠️ Chunk {chunk_num}/{total_chunks} tem apenas {chunk_size} chars - pode ter pouco conteúdo para extrair")
        # Mostrar primeiras linhas do conteúdo para debug
        first_lines = '\n'.join(chunk.split('\n')[:10])
        logger.debug(f"📄 Primeiras 10 linhas do chunk {chunk_num}: {first_lines[:500]}")
    
    # Primeira tentativa: tentar todos os provedores
    last_error = None
    for name, key, base_url, model in providers_to_try:
        try:
            logger.info(f"🔄 Chunk {chunk_num}/{total_chunks}: Tentando com {name} ({model})...")
            profile = await analyze_content_with_fallback(chunk, provider_name=name)
            
            # Log detalhado das categorias extraídas deste chunk
            if profile and hasattr(profile, 'offerings') and profile.offerings:
                categories = profile.offerings.product_categories if hasattr(profile.offerings, 'product_categories') else []
                if categories:
                    cat_names = [cat.category_name for cat in categories if hasattr(cat, 'category_name') and cat.category_name]
                    total_items = sum(len(cat.items) if hasattr(cat, 'items') and cat.items else 0 for cat in categories)
                    logger.info(f"✅ Chunk {chunk_num}/{total_chunks}: Sucesso com {name} - Extraídas {len(cat_names)} categorias ({total_items} items totais): {', '.join(cat_names[:5])}{'...' if len(cat_names) > 5 else ''}")
                else:
                    logger.warning(f"⚠️ Chunk {chunk_num}/{total_chunks}: Sucesso com {name} mas NENHUMA categoria extraída (conteúdo pode estar vazio ou incompleto)")
                    # Se não extraiu categorias e o chunk é pequeno, logar o conteúdo completo
                    if chunk_size < 1000:
                        logger.debug(f"📄 Conteúdo completo do chunk {chunk_num} (para debug):\n{chunk[:2000]}")
            else:
                logger.warning(f"⚠️ Chunk {chunk_num}/{total_chunks}: Sucesso com {name} mas perfil vazio ou sem offerings")
            
            return profile
        except Exception as e:
            logger.warning(f"⚠️ Chunk {chunk_num}/{total_chunks}: {name} falhou: {type(e).__name__}")
            last_error = e
            continue  # Tentar próximo provedor
    
    # Se todos os provedores falharam, tentar reprocessar uma vez (retry)
    logger.warning(f"🔄 Chunk {chunk_num}/{total_chunks}: Todos os provedores falharam. Tentando reprocessar uma vez...")
    for name, key, base_url, model in providers_to_try:
        try:
            logger.info(f"🔄 Chunk {chunk_num}/{total_chunks}: Retry com {name} ({model})...")
            profile = await analyze_content_with_fallback(chunk, provider_name=name)
            logger.info(f"✅ Chunk {chunk_num}/{total_chunks}: Sucesso no retry com {name}")
            return profile
        except Exception as e:
            logger.warning(f"⚠️ Chunk {chunk_num}/{total_chunks}: Retry com {name} falhou: {type(e).__name__}")
            last_error = e
            continue
    
    # Se ainda falhou após retry, retornar None
    logger.error(f"❌ Chunk {chunk_num}/{total_chunks}: Falhou após tentar todos os provedores e retry. Último erro: {last_error}")
    return None

async def analyze_content(text_content: str) -> CompanyProfile:
    """
    Função principal de análise com chunking automático e consolidação.
    SEMPRE processa uma página por requisição LLM para garantir que todas as páginas sejam analisadas.
    Distribui chunks entre múltiplos provedores LLM para evitar rate limits.
    Registra métricas de tempo de chunking, processamento de chunks e merge final.
    """
    global_start = time.perf_counter()
    tokens = estimate_tokens(text_content)
    logger.info(f"Conteúdo total: ~{tokens:,} tokens estimados")
    
    # SEMPRE dividir por páginas (uma página por requisição LLM)
    # Isso garante que todas as páginas sejam analisadas, mesmo que o conteúdo total seja pequeno
    MAX_TOKENS = 500_000  # 50% do limite do Gemini 2.0 Flash (1.048.575) - Muito conservador
    
    chunk_start = time.perf_counter()
    logger.info("Aplicando chunking por página (uma página por requisição LLM)...")
    chunks = chunk_content(text_content, MAX_TOKENS)
    chunk_duration = time.perf_counter() - chunk_start
    logger.info(
        f"[PERF] llm step=chunk_content chunks={len(chunks)} "
        f"duration={chunk_duration:.3f}s estimated_tokens={tokens}"
    )
    
    # Se houver apenas 1 chunk e for pequeno, ainda assim processar normalmente
    if len(chunks) == 1:
        logger.info(f"Uma única página detectada, processando diretamente...")
        single_start = time.perf_counter()
        profile = await analyze_content_with_fallback(chunks[0])
        total_duration = time.perf_counter() - global_start
        logger.info(
            f"[PERF] llm step=analyze_content_single_chunk duration={total_duration:.3f}s"
        )
        return profile
    
    # LOAD BALANCING: Distribuir chunks entre provedores disponíveis em round-robin
    if len(AVAILABLE_PROVIDERS) > 1:
        logger.info(f"🔄 Distribuindo {len(chunks)} chunks entre {len(AVAILABLE_PROVIDERS)} provedores LLM:")
        for provider_name, _, _, _ in AVAILABLE_PROVIDERS:
            logger.info(f"  • {provider_name}")
        
        # Atribuir cada chunk a um provedor em round-robin e processar com retry
        tasks = []
        for i, chunk in enumerate(chunks):
            provider_idx = i % len(AVAILABLE_PROVIDERS)
            provider_name = AVAILABLE_PROVIDERS[provider_idx][0]
            logger.info(f"  Chunk {i+1}/{len(chunks)} → {provider_name} (com retry e fallback)")
            tasks.append(process_chunk_with_retry(chunk, i+1, len(chunks), primary_provider=provider_name))
    else:
        # Apenas 1 provedor disponível, usar retry mesmo assim
        logger.info(f"Processando {len(chunks)} chunks com provedor único (com retry)...")
        tasks = [process_chunk_with_retry(chunk, i+1, len(chunks), primary_provider=None) 
                for i, chunk in enumerate(chunks)]
    
    # Processar todos os chunks em paralelo (com throttling do semaphore)
    process_chunks_start = time.perf_counter()
    partial_profiles = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filtrar exceções e None, manter apenas perfis válidos
    valid_profiles = []
    failed_chunks = []
    for i, result in enumerate(partial_profiles):
        if isinstance(result, Exception):
            logger.error(f"❌ Chunk {i+1}/{len(chunks)} falhou com exceção: {result}")
            failed_chunks.append(i+1)
        elif result is None:
            logger.warning(f"⚠️ Chunk {i+1}/{len(chunks)} retornou None (falhou após todos os retries)")
            failed_chunks.append(i+1)
        else:
            # Verificar se o perfil tem dados
            if isinstance(result, CompanyProfile):
                p_dict = result.model_dump()
                filled_fields = sum(1 for k, v in p_dict.items() 
                                  if v and (isinstance(v, dict) and any(v.values()) or isinstance(v, list) and len(v) > 0))
                if filled_fields > 0:
                    logger.info(f"✅ Chunk {i+1}/{len(chunks)} processado com sucesso ({filled_fields} campos preenchidos)")
                else:
                    logger.warning(f"⚠️ Chunk {i+1}/{len(chunks)} processado mas sem dados extraídos")
            valid_profiles.append(result)
    
    if failed_chunks:
        logger.warning(f"⚠️ {len(failed_chunks)} chunks falharam após retries: {failed_chunks}")
    
    if not valid_profiles:
        total_duration = time.perf_counter() - global_start
        logger.error(
            f"[PERF] llm step=analyze_content_all_chunks_failed duration={total_duration:.3f}s"
        )
        raise Exception("Todos os chunks falharam no processamento")
    
    # Analisar perfis antes do merge
    process_chunks_duration = time.perf_counter() - process_chunks_start
    logger.info(
        f"[PERF] llm step=process_chunks valid_profiles={len(valid_profiles)} "
        f"total_chunks={len(chunks)} duration={process_chunks_duration:.3f}s"
    )
    logger.info(f"📊 Análise pré-merge: {len(valid_profiles)}/{len(chunks)} perfis válidos")
    total_filled = sum(1 for p in valid_profiles 
                    if isinstance(p, CompanyProfile) and 
                    any(v for v in p.model_dump().values() 
                        if v and (isinstance(v, dict) and any(v.values()) or isinstance(v, list) and len(v) > 0)))
    logger.info(f"📊 Perfis com dados: {total_filled}/{len(valid_profiles)}")
    
    # Consolidar resultados
    merge_start = time.perf_counter()
    logger.info(f"✅ Consolidando {len(valid_profiles)}/{len(chunks)} perfis parciais bem-sucedidos...")
    final_profile = merge_profiles(valid_profiles)
    merge_duration = time.perf_counter() - merge_start
    logger.info(
        f"[PERF] llm step=merge_profiles duration={merge_duration:.3f}s "
        f"profiles_input={len(valid_profiles)}"
    )
    
    # Verificar resultado final
    final_dict = final_profile.model_dump()
    final_filled = sum(1 for k, v in final_dict.items() 
                      if v and (isinstance(v, dict) and any(v.values()) or isinstance(v, list) and len(v) > 0))
    total_duration = time.perf_counter() - global_start
    logger.info(f"📊 Resultado final: {final_filled} campos preenchidos")
    logger.info(
        f"[PERF] llm step=analyze_content_total duration={total_duration:.3f}s "
        f"chunks={len(chunks)}"
    )
    
    return final_profile
