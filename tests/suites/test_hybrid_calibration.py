"""
Teste de Calibração da Estratégia Híbrida (Fast + Retry).
Objetivo: Encontrar o ponto ótimo de agressividade do Fast Track.
"""

import sys
import asyncio
import json
import time
import logging
from pathlib import Path

# Setup paths
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.services.scraper.scraper_service import scrape_batch_hybrid
from app.services.scraper.constants import scraper_config, FAST_TRACK_CONFIG, RETRY_TRACK_CONFIG
from app.services.scraper import reset_circuit_breaker

# Configurar logging para arquivo e console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Carregar URLs
def load_urls(limit=100):
    reports_dir = Path("tests/reports")
    discovery_files = sorted(
        reports_dir.glob("discovery_test_*.json"),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    if not discovery_files:
        raise FileNotFoundError("Nenhum relatório de discovery encontrado")
    
    with open(discovery_files[0], 'r') as f:
        data = json.load(f)
    
    urls = []
    seen = set()
    for r in data.get('results', []):
        if r.get('success') and r.get('url'):
            url = r['url']
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls[:limit]

async def run_calibration_round(name, fast_overrides, urls):
    print(f"\n{'='*80}")
    print(f"🔄 RODADA: {name}")
    print(f"⚙️ Config Fast: {fast_overrides}")
    print(f"{'='*80}")
    
    # Atualizar perfil FAST com overrides
    current_fast = FAST_TRACK_CONFIG.copy()
    current_fast.update(fast_overrides)
    
    # Monkeypatch nas constantes para o teste (já que o scraper lê de lá)
    import app.services.scraper.scraper_service as ss
    # Precisamos atualizar o scraper_config antes de chamar, mas a função scrape_batch_hybrid
    # recarrega FAST_TRACK_CONFIG internamente. Vamos modificar o dicionário importado.
    
    # Truque: atualizar o dicionário FAST_TRACK_CONFIG no módulo constants
    import app.services.scraper.constants as const
    const.FAST_TRACK_CONFIG.update(fast_overrides)
    
    # Resetar estado
    reset_circuit_breaker()
    
    start_time = time.perf_counter()
    results = await scrape_batch_hybrid(urls, max_subpages=15)
    total_time = time.perf_counter() - start_time
    
    # Analisar resultados
    success = 0
    total_content = 0
    for res in results:
        if res and res[0]:
            success += 1
            total_content += len(res[0])
            
    print(f"\n📊 RESULTADO {name}:")
    print(f"   Tempo Total: {total_time:.2f}s")
    print(f"   Sucesso: {success}/{len(urls)} ({(success/len(urls)*100):.1f}%)")
    print(f"   Conteúdo Total: {total_content/1024/1024:.2f} MB")
    print(f"   Velocidade Média: {total_time/len(urls):.2f}s/site")
    
    return {
        "name": name,
        "time": total_time,
        "success": success,
        "rate": (success/len(urls))*100,
        "config": fast_overrides
    }

async def main():
    urls = load_urls(100)
    print(f"Carregadas {len(urls)} URLs para teste.")
    
    rounds = [
        ("R1_Baseline", {}), # Usa R5 atual como base
        
        ("R2_ShortSession", {"session_timeout": 8}),
        
        ("R3_ShortBreaker", {"circuit_breaker_threshold": 3}),
        
        ("R4_RelaxedQual", {"min_word_threshold": 2, "md_threshold": 0.3}),
        
        # Assumindo que max_retries seria implementado no scraper_service ou constants, 
        # mas como não temos esse param explícito no constants ainda, vamos pular este.
        # ("R5_ZeroRetries", {"max_retries": 0}), 
        
        ("R6_SpeedCombo1", {"session_timeout": 8, "circuit_breaker_threshold": 3}),
        
        ("R7_SpeedCombo2", {"min_word_threshold": 2, "md_threshold": 0.3, "session_timeout": 8}),
        
        ("R8_StrictQuality", {"min_word_threshold": 10, "md_threshold": 0.8}),
        
        ("R9_AggressiveALL", {
            "session_timeout": 8, 
            "circuit_breaker_threshold": 3,
            "min_word_threshold": 2, 
            "md_threshold": 0.3
        }),
        
        ("R10_Balanced", {
            "session_timeout": 10,
            "circuit_breaker_threshold": 4
        })
    ]
    
    results = []
    for name, config in rounds:
        res = await run_calibration_round(name, config, urls)
        results.append(res)
        # Pause para limpar conexões
        await asyncio.sleep(5)
        
    print("\n" + "="*80)
    print("🏆 RESUMO FINAL")
    print("="*80)
    print(f"{'Round':<20} | {'Tempo':<10} | {'Sucesso':<10} | {'Score (S/T)':<10}")
    print("-" * 60)
    
    # Score = Sucesso / Tempo (quanto maior melhor: mais sites por segundo)
    best_score = 0
    winner = None
    
    for r in results:
        score = r['success'] / r['time'] if r['time'] > 0 else 0
        print(f"{r['name']:<20} | {r['time']:<10.1f} | {r['rate']:<9.1f}% | {score:.3f}")
        
        if score > best_score:
            best_score = score
            winner = r
            
    print(f"\n🥇 VENCEDOR: {winner['name']}")
    print(f"⚙️ Config Ideal: {winner['config']}")

if __name__ == "__main__":
    asyncio.run(main())

