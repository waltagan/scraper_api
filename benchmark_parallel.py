import asyncio
import json
import time
import sys
import os
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Garantir que o diretório atual está no path para imports
sys.path.append(os.getcwd())

from app.services.scraper import scrape_url

async def run_benchmark():
    input_file = 'outras_empreas.json'
    output_file = 'benchmark_results.json'
    
    logger.info(f"Lendo sites de {input_file}...")
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            companies = json.load(f)
    except Exception as e:
        logger.error(f"Erro ao ler arquivo: {e}")
        return

    total_sites = len(companies)
    logger.info(f"Iniciando benchmark paralelo para {total_sites} sites...")
    
    results = []
    start_total_time = time.time()
    
    async def process_company(company):
        site_url = company.get('site')
        name = company.get('razao_social')
        
        if not site_url:
            return None
            
        start_unit = time.time()
        result_data = {
            "razao_social": name,
            "site": site_url,
            "status": "pending",
            "execution_time": 0,
            "data_size": 0,
            "pages_processed": 0,
            "error": None
        }
        
        try:
            # O scraper já possui controle de concorrência interno (semaphore)
            text, pdfs, links = await scrape_url(site_url)
            
            duration = time.time() - start_unit
            result_data.update({
                "status": "success",
                "execution_time": duration,
                "data_size": len(text) if text else 0,
                "pages_processed": len(links) if links else 0, # Aproximação baseada nos links retornados
                "pdfs_count": len(pdfs) if pdfs else 0
            })
            logger.info(f"✅ {name}: {duration:.2f}s - {len(text)} chars")
            
        except Exception as e:
            duration = time.time() - start_unit
            result_data.update({
                "status": "error",
                "execution_time": duration,
                "error": str(e)
            })
            logger.error(f"❌ {name}: {str(e)}")
            
        return result_data

    # Criar todas as tasks
    tasks = [process_company(company) for company in companies]
    
    # Executar em paralelo
    # O scraper.py gerencia o limite de concorrência via playwright_semaphore
    site_results = await asyncio.gather(*tasks)
    
    end_total_time = time.time()
    total_duration = end_total_time - start_total_time
    
    # Filtrar resultados nulos
    valid_results = [r for r in site_results if r]
    
    # Calcular estatísticas
    total_data_size = sum(r['data_size'] for r in valid_results if r['status'] == 'success')
    success_count = sum(1 for r in valid_results if r['status'] == 'success')
    
    final_output = {
        "summary": {
            "total_sites_processed": len(valid_results),
            "successful_sites": success_count,
            "total_execution_time_seconds": total_duration,
            "average_time_per_site_seconds": total_duration / len(valid_results) if valid_results else 0,
            "total_data_extracted_chars": total_data_size,
            "timestamp": time.time()
        },
        "results": valid_results
    }
    
    # Salvar resultado
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Benchmark concluído em {total_duration:.2f}s")
    logger.info(f"Resultados salvos em {output_file}")

if __name__ == "__main__":
    asyncio.run(run_benchmark())

