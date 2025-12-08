import asyncio
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Imports do app
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from app.services.llm.llm_service import get_llm_service
from app.core.config import settings

# Constantes de teste
MAX_CONCURRENT_REQUESTS = 300 # Stress test total
TOTAL_SITES_TO_TEST = 300    # Meta: 300 empresas

async def load_test_data() -> List[str]:
    """Carrega dados de relatórios anteriores ou gera dados fake."""
    reports_dir = Path("tests/reports")
    # Tentar pegar os relatórios mais recentes de scraper
    scraper_reports = sorted(list(reports_dir.glob("scraper_test_*.json")), reverse=True)
    
    contents = []
    
    print("📂 Buscando dados de scraping anteriores...")
    for report_file in scraper_reports:
        try:
            with open(report_file, 'r') as f:
                data = json.load(f)
                
                # Formato 1: Lista de resultados
                results = data.get('results', [])
                if isinstance(results, dict):
                    results_list = results.values()
                else:
                    results_list = results
                    
                for result in results_list:
                    text = ""
                    # Tenta extrair texto de diferentes formatos possíveis
                    if isinstance(result, list) and len(result) > 0:
                         # Formato (text, docs, links)
                        text = result[0]
                    elif isinstance(result, dict):
                        # Formato ScrapedContent
                        text = result.get('content', '') or result.get('text', '') or result.get('main_content', '')
                        if not text and 'main_page' in result:
                             text = result['main_page'].get('content', '')
                    
                    if text and isinstance(text, str) and len(text) > 500: # Ignorar textos muito curtos
                        contents.append(text)
                        
        except Exception as e:
            # logger.warning(f"Erro ao ler {report_file}: {e}")
            pass
            
        if len(contents) >= TOTAL_SITES_TO_TEST:
            break
            
    print(f"📊 Dados reais encontrados: {len(contents)}")
            
    # Se não tiver dados suficientes, preencher com dados sintéticos ou duplicar
    if not contents:
        logger.warning("Nenhum conteúdo real encontrado, usando dados sintéticos.")
        base_text = """
        A TechSolutions é uma empresa líder em desenvolvimento de software e soluções digitais.
        Fundada em 2010, oferecemos serviços de consultoria em TI, desenvolvimento web, aplicativos mobile e cloud computing.
        Nossa missão é transformar negócios através da tecnologia.
        Atuamos nos setores financeiro, varejo e saúde.
        Nossos principais produtos incluem o TechFlow (plataforma SaaS de gestão) e o CyberGuard (solução de segurança cibernética).
        Temos parcerias estratégicas com AWS, Microsoft e Google.
        A empresa possui certificação ISO 27001 e GPTW (Great Place to Work).
        Contato: contato@techsolutions.com.br | Tel: (11) 3333-4444
        Endereço: Av. Paulista, 1000, 5º andar, São Paulo - SP.
        CEO: João Silva. CTO: Maria Oliveira.
        """
        contents = [base_text for _ in range(TOTAL_SITES_TO_TEST)]
    
    # Completar se faltar (duplicando dados reais para teste de carga)
    original_len = len(contents)
    if original_len > 0:
        while len(contents) < TOTAL_SITES_TO_TEST:
            # Pega um aleatório ou ciclo
            idx = len(contents) % original_len
            contents.append(contents[idx])
        
    return contents[:TOTAL_SITES_TO_TEST]

async def run_profiler_test():
    """Executa o teste de carga do profiler."""
    print(f"🚀 Iniciando Teste de Perfil (LLM) - {datetime.now().isoformat()}")
    print(f"📊 Alvo: {TOTAL_SITES_TO_TEST} empresas em paralelo")
    
    # 1. Carregar dados
    contents = await load_test_data()
    print(f"✅ {len(contents)} textos preparados para análise.")
    
    # 2. Preparar LLM Service
    service = get_llm_service()
    providers = service.provider_manager.available_providers
    print(f"🤖 Providers disponíveis: {providers}")
    
    # 3. Executar em paralelo
    print("⚡ Iniciando processamento paralelo...")
    start_time = time.perf_counter()
    
    # Semáforo para controlar concorrência local
    sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    
    results = []
    
    async def analyze_wrapper(index, text):
        async with sem:
            t0 = time.perf_counter()
            try:
                # Simula delay de rede/IO aleatório antes de chamar LLM para não bater todos exatos no mesmo ms
                await asyncio.sleep(index * 0.01) 
                
                profile = await service.analyze(text)
                duration = time.perf_counter() - t0
                
                # Verifica se houve retorno válido
                has_identity = profile.identity and profile.identity.company_name
                is_success = bool(has_identity or (profile.offerings.products and len(profile.offerings.products) > 0))
                
                return {
                    "index": index,
                    "success": is_success,
                    "duration": duration,
                    "profile_name": profile.identity.company_name if has_identity else "Unknown",
                    "error": None
                }
            except Exception as e:
                duration = time.perf_counter() - t0
                return {
                    "index": index,
                    "success": False,
                    "duration": duration,
                    "profile_name": None,
                    "error": str(e)
                }

    tasks = [analyze_wrapper(i, text) for i, text in enumerate(contents)]
    
    # Barra de progresso
    completed = 0
    total = len(tasks)
    
    # Usar as_completed para monitorar progresso
    for future in asyncio.as_completed(tasks):
        res = await future
        results.append(res)
        completed += 1
        if completed % 10 == 0:
            print(f"   Progresso: {completed}/{total} ({(completed/total)*100:.1f}%) - Último: {res['duration']:.2f}s {'✅' if res['success'] else '❌'}")
            
    total_time = time.perf_counter() - start_time
    
    # 4. Análise de Resultados
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    avg_time = sum(r['duration'] for r in results) / len(results) if results else 0
    
    print("\n" + "="*50)
    print("🏁 RELATÓRIO FINAL DE TESTE (LLM / PERFIL)")
    print("="*50)
    print(f"⏱️ Tempo Total de Execução: {total_time:.2f}s")
    print(f"📉 Tempo Médio por Requisição: {avg_time:.2f}s")
    print(f"✅ Sucessos: {len(successful)} ({len(successful)/total*100:.1f}%)")
    print(f"❌ Falhas: {len(failed)} ({len(failed)/total*100:.1f}%)")
    print(f"🚀 Throughput: {(len(results)/total_time)*60:.1f} RPM")
    
    if failed:
        print("\n🔍 Principais Erros:")
        errors = {}
        for f in failed:
            msg = f['error'] or "Unknown"
            # Simplificar mensagem de erro
            short_msg = msg[:100]
            errors[short_msg] = errors.get(short_msg, 0) + 1
        for msg, count in errors.items():
            print(f"   - {msg}...: {count}x")
            
    # Salvar relatório detalhado
    report = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "total_sites": TOTAL_SITES_TO_TEST,
            "max_concurrent": MAX_CONCURRENT_REQUESTS,
            "providers": providers
        },
        "metrics": {
            "total_time": total_time,
            "success_rate": len(successful)/total,
            "avg_latency": avg_time,
            "throughput_rpm": (len(results) / total_time) * 60
        },
        "details": sorted(results, key=lambda x: x['index'])
    }
    
    report_path = f"tests/reports/profiler_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    os.makedirs("tests/reports", exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
        
    print(f"\n📄 Relatório completo salvo em: {report_path}")

if __name__ == "__main__":
    try:
        asyncio.run(run_profiler_test())
    except KeyboardInterrupt:
        print("\n🛑 Teste interrompido pelo usuário.")

