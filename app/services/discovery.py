import asyncio
import logging
import json
import urllib.parse
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.proxy import proxy_manager

logger = logging.getLogger(__name__)

DISCOVERY_PROMPT = """# Prompt: Agente Especialista em Localizar Sites Oficiais de Empresas

## Objetivo
Você é um agente especializado em localizar **o site oficial de uma empresa brasileira**, com base em dados cadastrais e resultados de busca. Seu papel é garantir que o site identificado seja **efetivamente controlado pela empresa**, mesmo que o nome da empresa apareça com pequenas variações.

## Informações de entrada
Você receberá:
- Nome Fantasia
- Razão Social
- CNPJ (quando disponível)
- E-mail (quando disponível) - Verifique se o domínio do e-mail coincide com o site.
- Município - Verifique se o site menciona a cidade ou região.
- CNAEs (atividades) - Verifique se o site oferece serviços compatíveis com estas atividades.
- Lista de Resultados da Busca (Título, URL, Snippet)

## Estratégia de Busca e Verificação

1. **Busque domínios corporativos próprios**, incluindo sufixos como:
   `.com.br`, `.com`, `.net.br`, `.eng.br`, `.ind.br`, `.wixsite.com` (com validação reforçada).

2. **Aceite variações no nome da empresa no domínio**, desde que:
   - O nome esteja parcialmente presente no domínio (ex: `rubiengenharia.com.br` para "Rubi Engenharia").
   - O conteúdo do site comprove a identidade por outros meios (ver abaixo).

3. **Valide a identidade com base em ao menos duas das evidências abaixo**:
   - Nome da empresa (ou variação) na seção "Sobre", "Contato" ou rodapé do site;
   - Endereço compatível com a cidade ou estado fornecidos;
   - E-mail corporativo no domínio (ex: contato@empresa.com.br);
   - Presença de CNPJ ou razão social completa no site;
   - Perfis oficiais da empresa (Instagram, LinkedIn, etc.) apontando diretamente para o domínio;
   - Serviços, clientes ou projetos listados que confirmam o segmento informado.

4. **Sites em plataformas como Wix ou WordPress** são aceitáveis **se o conteúdo comprovar a identidade institucional** com base nas evidências acima.

5. **Similaridade de Domínio (Alta Prioridade)**:
   - Se a URL contém o "Nome Fantasia" ou "Razão Social" de forma clara (ex: Empresa "Eco Mineral", Site "ecomineral.com.br"), considere isso o fator MAIS FORTE.
   - **IMPORTANTE:** Se o domínio for um match quase exato com o nome, **IGNORE** divergências leves no snippet ou descrição de atividade. O snippet do Google muitas vezes é impreciso. Dê o benefício da dúvida para domínios com nome igual.

6. **Atividade Econômica (CNAEs/Descrição) - Fator Secundário**:
   - Use os CNAEs apenas para confirmação sutil ("tie-breaker").
   - **NÃO DESCARTE** um site apenas porque a descrição do snippet não bate perfeitamente com os CNAEs.
   - Exemplo: Se a empresa é "Mineração" (CNAE) e o site fala de "Produtos Abrasivos" ou "Soluções Ambientais", considere VÁLIDO se o nome bater. As empresas muitas vezes têm braços comerciais diferentes do CNAE principal.

7. **Validação de E-mail (Se fornecido)**:
   - O campo "email" é APENAS para validação.
   - Se o domínio do site encontrado bater com o domínio do e-mail (ex: site 'empresa.com.br', email 'contato@empresa.com.br'), é uma confirmação definitiva (100% certeza).
   - Se o domínio do site for DIFERENTE do e-mail (ex: email gmail, ou email de consultoria), isso **NÃO** invalida o site.

8. Se houver **múltiplos sites candidatos**, selecione o que possuir mais evidências cruzadas de vínculo com a empresa.

## Exclusões Obrigatórias

Rejeite os seguintes tipos de páginas, mesmo se mencionarem a empresa:
- Diretórios empresariais (ex: CNPJ.biz, Econodata, TeleListas, Apontador, SerasaExperian)
- Sites de marketplaces (ex: OLX, Mercado Livre, Shopee)
- Sites de releases, notícias ou matérias jornalísticas
- Blogs ou páginas pessoais que apenas mencionem a empresa
- Páginas com nomes semelhantes, mas sem qualquer evidência de vínculo com os dados fornecidos

## Exemplos para calibração

**Aceite:**
- `https://www.brzfire.com.br` → domínio combina com nome fantasia, e-mail institucional aparece no rodapé.
- `http://www.rubiengenharia.com.br` → nome parcialmente compatível, site descreve serviços de engenharia e localização compatível.
- `https://ethicusscs.wixsite.com/refrigeracao` → site Wix, mas com nome da empresa, segmento e contato institucional válidos.

**NÃO ACEITE DE MANEIRA ALGUMA:**
RESULTADOS QUE EXIBEM UM DOMINIO ENQUADRADO DENTRO DOS TIPOS ABAIXO SÃO CONSIDERADOS COMO "NÃO CONFIAVEIS" E NÃO DEVEM SER RETORNADOS, AO INVÈS DISSO RESPONDA COM "nao_encontrado".
- `https://cnpj.biz/empresa-nome` → diretório empresarial sem vínculo institucional.
- `https://shopee.com/empresa-xyz` → perfil em marketplace, não institucional.
- `https://econodata.com.br/empresa-xyz` → diretório empresarial sem vínculo institucional.
- `https://facebook.com/empresa-xyz` → perfil em redes sociais, não institucional.

## Formato de Resposta (JSON)
O parametro "site_oficial" deve ser "sim" para sites que com certeza pertencem a empresa em si, não representando sites de terceiros ou menções ou diretórios ou qualquer coisa nesse sentido. Sites que não estão em contro da empresa e são diretórios ou sites de terceitos, devem ter "site_oficial" = "nao".

Se o site for considerado oficial:
```json
{
  "site": "https://www.nomedasuaempresa.com.br",
  "justificativa": "O domínio contém o nome fantasia e o site descreve os serviços, endereço e e-mail institucional compatíveis com os dados fornecidos...",
 "site_oficial" : "sim"
}
```

Se nenhum site for confiável:
```json
{
  "site": "nao_encontrado",
  "justificativa": "Nenhum dos sites encontrados possui evidência suficiente de pertencimento à empresa. Todos são diretórios, domínios genéricos ou menções indiretas.",
 "site_oficial" : "nao"
}
```

Apenas diretórios, redes sociais, ou marketplaces foram encontrados:
```json
{
"site": "nao_encontrado",
"justificativa": "Os domínios encontrados representam diretórios empresariais...",
 "site_oficial" : "nao"
}
```
"""

import httpx

async def search_google_serper(query: str, num_results: int = 20) -> List[Dict[str, str]]:
    """
    Realiza uma busca no Google usando a API Serper.dev (mais confiável).
    """
    if not settings.SERPER_API_KEY:
        logger.warning("⚠️ SERPER_API_KEY não configurada. Usando fallback para scraping (pode falhar).")
        return await search_google(query, num_results) # Fallback para o antigo se não tiver key

    logger.info(f"🔎 Buscando no Google via Serper: {query}")
    
    url = "https://google.serper.dev/search"
    payload = json.dumps({
        "q": query,
        "num": num_results,
        "gl": "br",
        "hl": "pt-br"
    })
    headers = {
        'X-API-KEY': settings.SERPER_API_KEY,
        'Content-Type': 'application/json'
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, data=payload, timeout=30.0)
            
            if response.status_code != 200:
                logger.error(f"❌ Erro na Serper API: {response.status_code} - {response.text}")
                return []
            
            data = response.json()
            organic_results = data.get("organic", [])
            
            results = []
            for item in organic_results:
                results.append({
                    "title": item.get("title"),
                    "link": item.get("link"),
                    "snippet": item.get("snippet", "")
                })
            
            logger.info(f"✅ Serper retornou {len(results)} resultados.")
            return results
            
    except Exception as e:
        logger.error(f"❌ Erro na execução da busca Serper: {e}")
        return []

async def search_google(query: str, num_results: int = 10) -> List[Dict[str, str]]:
    """
    Realiza uma busca no Google e extrai os resultados orgânicos.
    Usa crawl4ai com proxy para evitar bloqueios.
    """
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.google.com/search?q={encoded_query}&hl=pt-BR&num={num_results}"
    
    logger.info(f"🔎 Buscando no Google: {query}")
    
    # Configuração do Crawler
    # Usar user-agent realista e proxy rotativo
    proxy = await proxy_manager.get_next_proxy()
    
    browser_config = BrowserConfig(
        browser_type="chromium",
        headless=True,
        proxy_config=proxy,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        # Atraso aleatório para simular humano? O crawl4ai já tem algumas proteções.
        # Vamos confiar no proxy e no browser.
        page_timeout=30000
    )
    
    results = []
    
    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)
            
            if not result.success:
                logger.error(f"❌ Falha ao buscar no Google: {result.error_message}")
                return []
            
            # Parse HTML
            soup = BeautifulSoup(result.html, 'html.parser')
            
            # Remover scripts e estilos para limpar o texto
            for script in soup(["script", "style"]):
                script.decompose()

            # Estratégia de Extração em Camadas
            # O Google muda muito o HTML (div.g, div.MjjYud, etc).
            # Vamos tentar identificar blocos de resultado.
            
            results_found = False
            
            # 1. Seletores Específicos Conhecidos
            possible_result_selectors = ['div.g', 'div.MjjYud', 'div.tF2Cxc']
            
            for selector in possible_result_selectors:
                items = soup.select(selector)
                if items:
                    for item in items:
                        # Tenta extrair título (h3) e link (a)
                        h3 = item.find('h3')
                        a = item.find('a', href=True)
                        
                        if h3 and a:
                            link = a['href']
                            title = h3.get_text(strip=True)
                            
                            # Tenta extrair snippet (texto descritivo)
                            # Geralmente está em um div ou span após o título
                            # Vamos pegar todo o texto do container e remover o título
                            container_text = item.get_text(separator=' ', strip=True)
                            snippet = container_text.replace(title, '', 1).strip()
                            # Limpeza extra do snippet (remover URLs visuais comuns)
                            snippet = snippet.replace(link, '')
                            
                            if link.startswith('http') and 'google.com' not in link:
                                results.append({
                                    "title": title,
                                    "link": link,
                                    "snippet": snippet[:400]
                                })
                                results_found = True
                    
                    if results_found:
                        break # Se funcionou com este seletor, paramos.

            # 2. Fallback Agressivo (Se seletores falharem)
            if not results_found:
                logger.warning("⚠️ Seletores específicos falharam. Usando extração por proximidade.")
                # Procura todos h3 (que geralmente são títulos)
                all_h3 = soup.find_all('h3')
                for h3 in all_h3:
                    # O link costuma ser o pai ou vizinho
                    parent_a = h3.find_parent('a', href=True)
                    if not parent_a:
                        # Às vezes o h3 está dentro do a, ou o a está logo antes
                        continue
                        
                    link = parent_a['href']
                    title = h3.get_text(strip=True)
                    
                    if not link.startswith('http') or 'google.com' in link:
                        continue

                    # Tenta pegar o snippet: texto no elemento pai do link (container do resultado)
                    container = parent_a.find_parent('div')
                    snippet = ""
                    if container:
                        full_text = container.get_text(separator=' ', strip=True)
                        snippet = full_text.replace(title, '', 1).replace(link, '').strip()
                    
                    results.append({
                        "title": title,
                        "link": link,
                        "snippet": snippet[:400]
                    })
                        
    except Exception as e:
        logger.error(f"❌ Erro na execução da busca: {e}")
        return []

    logger.info(f"✅ Encontrados {len(results)} resultados na busca.")
    return results

async def find_company_website(
    razao_social: str, 
    nome_fantasia: str, 
    cnpj: str,
    email: Optional[str] = None,
    municipio: Optional[str] = None,
    cnaes: Optional[List[str]] = None
) -> Optional[str]:
    """
    Orquestra a descoberta do site oficial da empresa.
    1. Monta as queries (Múltiplas buscas: Nome Fantasia e Razão Social separadas)
    2. Busca no Google
    3. Usa LLM com contexto rico (Email, Cidade, CNAEs) para analisar resultados
    """
    
    queries = []
    
    nf = nome_fantasia.strip() if nome_fantasia else ""
    rs = razao_social.strip() if razao_social else ""
    city = municipio.strip() if municipio else ""
    
    # Query 1: Nome Fantasia + Municipio (se existir)
    if nf:
        q1 = f'{nf} {city} site oficial'.strip()
        queries.append(q1)
    
    # Query 2: Razão Social + Municipio (se existir)
    if rs:
        # Remover "LTDA", "S.A.", "EIRELI", "ME", "EPP" para limpar a busca
        clean_rs = rs.replace(" LTDA", "").replace(" S.A.", "").replace(" EIRELI", "").replace(" ME", "").replace(" EPP", "")
        q2 = f'{clean_rs} {city} site oficial'.strip()
        queries.append(q2)
    
    # Query 3: Busca apenas pelo primeiro nome (Marca) + site oficial
    # Isso ajuda quando o nome fantasia é longo (ECOMINERAL TECH LTDA) mas o site é curto (ecomineral.com.br)
    if nf:
        first_name = nf.split()[0]
        if len(first_name) > 3: # Evitar siglas muito curtas isoladas
            q3 = f'{first_name} {city} site oficial'.strip()
            queries.append(q3)
            # Query 4: Nome curto sem cidade (para empresas nacionais)
            q4 = f'{first_name} site oficial'.strip()
            queries.append(q4)
    elif rs:
         # Fallback para primeiro nome da razão social se não tiver fantasia
        clean_rs = rs.replace(" LTDA", "").replace(" S.A.", "").replace(" EIRELI", "").replace(" ME", "").replace(" EPP", "")
        first_name = clean_rs.split()[0]
        if len(first_name) > 3:
             q3 = f'{first_name} {city} site oficial'.strip()
             queries.append(q3)
    
    # Se não gerou queries (input vazio), retorna
    if not queries:
        logger.warning("⚠️ Sem Nome Fantasia ou Razão Social para busca.")
        return None

    # ESTRATÉGIA EXTRA: Validação de E-mail (Apenas Log)
    # Se tiver email corporativo, logamos para debug, mas não forçamos busca específica.
    if email and "@" in email:
        domain_part = email.split("@")[1].lower().strip()
        generic_domains = [
            "gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "yahoo.com.br", 
            "uol.com.br", "bol.com.br", "terra.com.br", "ig.com.br", "icloud.com", "me.com"
        ]
        if domain_part not in generic_domains and "." in domain_part:
            logger.info(f"📧 Domínio de email disponível para validação cruzada: {domain_part}")

    # Executar buscas (sequencial para evitar rate limit agressivo)
    all_results = []
    seen_links = set()
    
    # Executar queries em ordem de prioridade
    
    for q in queries:
        res = await search_google_serper(q)
        for r in res:
            if r['link'] not in seen_links:
                all_results.append(r)
                seen_links.add(r['link'])
    
    if not all_results:
        logger.warning("⚠️ Nenhum resultado encontrado no Google após múltiplas buscas.")
        return None
    
    if not all_results:
        logger.warning("⚠️ Nenhum resultado encontrado no Google após múltiplas buscas.")
        return None
        
    # Logar resultados consolidados para debug
    logger.info(f"🔍 Resultados consolidados enviados para IA ({len(all_results)} itens):")
    logger.info(json.dumps(all_results, indent=2, ensure_ascii=False))

    # 3. Analisar com LLM
    client = AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
    
    # Preparar input para o LLM
    results_text = json.dumps(all_results, indent=2, ensure_ascii=False)
    
    user_content = f"""
    Dados da Empresa:
    - Nome Fantasia: {nome_fantasia or 'Não informado'}
    - Razão Social: {razao_social or 'Não informado'}
    - CNPJ: {cnpj or 'Não informado'}
    - E-mail: {email or 'Não informado'}
    - Município: {municipio or 'Não informado'}
    - CNAEs (Atividades): {', '.join(cnaes) if cnaes else 'Não informado'}
    
    Resultados da Busca (Consolidados):
    {results_text}
    """
    
    try:
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": DISCOVERY_PROMPT},
                {"role": "user", "content": user_content}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content.strip()
        logger.info(f"🧠 Decisão do LLM: {content}")
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Tentar limpar markdown se houver
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
                data = json.loads(content)
            else:
                raise

        # Tratamento para caso a IA retorne uma lista em vez de um objeto
        if isinstance(data, list):
            if len(data) > 0:
                data = data[0]
            else:
                logger.warning("⚠️ IA retornou lista vazia.")
                return None
        
        if data.get("site_oficial") == "sim" and data.get("site") and data.get("site") != "nao_encontrado":
            return data.get("site")
        else:
            logger.info(f"❌ Site não encontrado ou não oficial. Justificativa: {data.get('justificativa')}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Erro na análise do LLM para descoberta de site: {e}")
        return None

