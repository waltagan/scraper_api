import asyncio
import json
import time
import sys
import os
import logging
import random
from typing import Dict, Any

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AggressiveOptimizer")

# Garantir que o diretório atual está no path para imports
sys.path.append(os.getcwd())

from app.services.scraper import scrape_url, configure_scraper_params

class AggressiveOptimizer:
    def __init__(self):
        self.input_file = 'outras_empreas.json'
        self.output_file = 'aggressive_optimization_results.json'
        self.history = []
        
    def generate_aggressive_config(self) -> Dict[str, Any]:
        """Gera uma configuração focado puramente em velocidade"""
        return {
            'playwright_semaphore_limit': random.choice([30, 40, 50, 60]), # Muito paralelismo
            'circuit_breaker_threshold': random.choice([1, 2]), # Fail fast
            'page_timeout': random.choice([5000, 8000, 10000, 12000]), # Timeouts curtos (5-12s)
            'md_threshold': random.choice([0.6, 0.7, 0.8]), # Menos processamento de markdown
            'min_word_threshold': random.choice([3, 4, 5]), # Aceitar textos menores
            'chunk_size': random.choice([10, 15, 20]), # Lotes grandes
            'chunk_semaphore_limit': random.choice([40, 50, 60, 70]), # Subpáginas massivas
            'session_timeout': random.choice([3, 5, 8]) # Sessões rápidas
        }

    async def run_round(self, round_id: int):
        logger.info(f"\n{'='*50}")
        logger.info(f"🔄 INICIANDO RODADA {round_id}/5")
        logger.info(f"{'='*50}")

        # 1. Gerar e Aplicar Configuração
        config = self.generate_aggressive_config()
        logger.info(f"⚡ Configuração Agressiva: {json.dumps(config, indent=2)}")
        
        configure_scraper_params(**config)

        # 2. Carregar Sites
        try:
            with open(self.input_file, 'r', encoding='utf-8') as f:
                companies = json.load(f)
        except Exception as e:
            logger.error(f"Erro ao ler arquivo: {e}")
            return

        # 3. Executar Benchmark (Lógica do benchmark_parallel.py embutida)
        start_round = time.time()
        
        async def process_company(company):
            site_url = company.get('site')
            if not site_url: return None
            
            t0 = time.time()
            try:
                text, pdfs, links = await scrape_url(site_url, max_subpages=40) # Limitado para garantir velocidade
                dt = time.time() - t0
                return {
                    "site": site_url,
                    "status": "success" if text else "empty",
                    "time": dt,
                    "size": len(text) if text else 0,
                    "pages": len(links) if links else 0
                }
            except Exception as e:
                return {
                    "site": site_url,
                    "status": "error",
                    "time": time.time() - t0,
                    "error": str(e),
                    "size": 0
                }

        logger.info(f"🚀 Disparando scraping paralelo para {len(companies)} sites...")
        tasks = [process_company(c) for c in companies]
        results = await asyncio.gather(*tasks)
        
        round_duration = time.time() - start_round
        
        # 4. Calcular Métricas
        valid_results = [r for r in results if r and r['status'] == 'success']
        total_size = sum(r['size'] for r in valid_results)
        success_count = len(valid_results)
        avg_time = sum(r['time'] for r in valid_results) / len(valid_results) if valid_results else 0
        
        # Score simples: (Velocidade * 0.6) + (Dados * 0.4)
        # Queremos MENOR tempo e MAIOR dados.
        # Score = (Total Sites / Tempo Total) * 1000 + (Dados / 1000)
        # Ajuste: Penalizar fortemente se success_count for baixo
        
        sites_per_second = len(companies) / round_duration
        score = (sites_per_second * 100) + (total_size / 10000)
        
        if success_count < len(companies) * 0.8: # Se menos de 80% de sucesso, penaliza
            score = score * 0.5

        round_data = {
            "round": round_id,
            "config": config,
            "metrics": {
                "total_duration": round_duration,
                "avg_time_per_site": avg_time,
                "total_data_chars": total_size,
                "success_rate": f"{success_count}/{len(companies)}",
                "sites_per_second": sites_per_second
            },
            "score": score
        }
        
        self.history.append(round_data)
        logger.info(f"🏁 Fim da Rodada {round_id}")
        logger.info(f"⏱️ Tempo Total: {round_duration:.2f}s | Média/Site: {avg_time:.2f}s")
        logger.info(f"📦 Dados Totais: {total_size} chars")
        logger.info(f"🏆 Score da Rodada: {score:.2f}")

    def save_results(self):
        # Encontrar a melhor rodada
        best_round = max(self.history, key=lambda x: x['score'])
        
        output = {
            "summary": {
                "timestamp": time.time(),
                "total_rounds": len(self.history),
                "best_round_id": best_round['round'],
                "best_score": best_round['score']
            },
            "best_config": best_round['config'],
            "best_metrics": best_round['metrics'],
            "history": self.history
        }
        
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
            
        logger.info(f"\n🎉 Otimização concluída!")
        logger.info(f"💾 Resultados salvos em {self.output_file}")
        logger.info(f"👑 Melhor Configuração (Rodada {best_round['round']}):")
        logger.info(json.dumps(best_round['config'], indent=2))

async def main():
    optimizer = AggressiveOptimizer()
    for i in range(1, 6):
        await optimizer.run_round(i)
        # Breve pausa para limpar recursos/conecções
        await asyncio.sleep(2) 
    
    optimizer.save_results()

if __name__ == "__main__":
    asyncio.run(main())

