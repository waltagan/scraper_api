#!/usr/bin/env python3
"""
Teste de Produção Massivo - Processamento paralelo de empresas
Autor: Auto-gerado para teste do B2B Flash Profiler
"""

import asyncio
import aiohttp
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from collections import defaultdict

# Configurações
API_URL = "http://localhost:8000/analyze"
API_KEY = os.getenv("API_ACCESS_TOKEN", "buscafornecedor-api")
TIMEOUT_SECONDS = 180
MAX_CONCURRENT = 300  # Máximo de requisições simultâneas

@dataclass
class CompanyResult:
    """Resultado do processamento de uma empresa"""
    cnpj: str
    razao_social: str
    nome_fantasia: Optional[str]
    status: str  # success, error, timeout, not_found
    http_code: Optional[int] = None
    error_message: Optional[str] = None
    execution_time_seconds: float = 0.0
    profile: Optional[Dict[str, Any]] = None
    discovered_url: Optional[str] = None

@dataclass
class TestMetrics:
    """Métricas agregadas do teste"""
    total_empresas: int = 0
    success_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    not_found_count: int = 0
    total_time_seconds: float = 0.0
    avg_time_per_company: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    success_rate: float = 0.0
    
    # Distribuição de tempos
    time_distribution: Dict[str, int] = field(default_factory=lambda: {
        "0-30s": 0,
        "30-60s": 0,
        "60-90s": 0,
        "90-120s": 0,
        "120-180s": 0,
        ">180s": 0
    })
    
    # Erros por tipo
    errors_by_type: Dict[str, int] = field(default_factory=dict)

def categorize_time(seconds: float) -> str:
    """Categoriza tempo de execução em faixas"""
    if seconds <= 30:
        return "0-30s"
    elif seconds <= 60:
        return "30-60s"
    elif seconds <= 90:
        return "60-90s"
    elif seconds <= 120:
        return "90-120s"
    elif seconds <= 180:
        return "120-180s"
    else:
        return ">180s"

async def analyze_company(
    session: aiohttp.ClientSession,
    empresa: Dict[str, Any],
    index: int,
    total: int
) -> CompanyResult:
    """Processa uma empresa via API - SEM semáforo para início simultâneo"""
    
    cnpj = empresa.get("cnpj", "")
    razao_social = empresa.get("razao_social", "")
    nome_fantasia = empresa.get("nome_fantasia")
    email = empresa.get("email")
    uf = empresa.get("uf")
    
    result = CompanyResult(
        cnpj=cnpj,
        razao_social=razao_social,
        nome_fantasia=nome_fantasia,
        status="pending"
    )
    
    payload = {
        "razao_social": razao_social,
        "nome_fantasia": nome_fantasia,
        "cnpj": cnpj,
    }
    
    # Adiciona email se disponível
    if email:
        payload["email"] = email
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY
    }
    
    start_time = time.perf_counter()
    
    # SEM semáforo - todas iniciam simultaneamente
    try:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        async with session.post(
            API_URL,
            json=payload,
            headers=headers,
            timeout=timeout
        ) as response:
            result.http_code = response.status
            result.execution_time_seconds = time.perf_counter() - start_time
            
            if response.status == 200:
                result.status = "success"
                result.profile = await response.json()
                
                # Extrair URL descoberta se houver
                sources = result.profile.get("sources", [])
                if sources:
                    # Primeiro source geralmente é "Discovered via Google Search: URL"
                    for source in sources:
                        if source.startswith("Discovered via"):
                            result.discovered_url = source.split(": ")[-1]
                            break
                        elif source.startswith("http"):
                            result.discovered_url = source
                            break
                            
            elif response.status == 404:
                result.status = "not_found"
                error_data = await response.json()
                result.error_message = error_data.get("detail", "Site não encontrado")
                
            elif response.status == 504:
                result.status = "timeout"
                error_data = await response.json()
                result.error_message = error_data.get("detail", "Timeout na análise")
                
            else:
                result.status = "error"
                try:
                    error_data = await response.json()
                    result.error_message = error_data.get("detail", f"HTTP {response.status}")
                except:
                    result.error_message = f"HTTP {response.status}"
                    
    except asyncio.TimeoutError:
        result.status = "timeout"
        result.error_message = f"Client timeout após {TIMEOUT_SECONDS}s"
        result.execution_time_seconds = time.perf_counter() - start_time
        
    except aiohttp.ClientError as e:
        result.status = "error"
        result.error_message = f"Erro de conexão: {str(e)}"
        result.execution_time_seconds = time.perf_counter() - start_time
        
    except Exception as e:
        result.status = "error"
        result.error_message = f"Erro inesperado: {str(e)}"
        result.execution_time_seconds = time.perf_counter() - start_time
    
    # Log de progresso
    status_icon = {
        "success": "✅",
        "not_found": "🔍",
        "timeout": "⏱️",
        "error": "❌"
    }.get(result.status, "❓")
    
    print(f"{status_icon} [{index+1}/{total}] [{result.execution_time_seconds:.1f}s] {nome_fantasia or razao_social[:40]} - {result.status}", flush=True)
    
    return result

async def run_test(empresas: List[Dict[str, Any]]) -> tuple[List[CompanyResult], TestMetrics]:
    """Executa o teste em todas as empresas - TODAS SIMULTÂNEAS"""
    
    print(f"\n{'='*60}")
    print(f"🚀 INICIANDO TESTE DE PRODUÇÃO MASSIVO")
    print(f"{'='*60}")
    print(f"📊 Total de empresas: {len(empresas)}")
    print(f"⏱️  Timeout por empresa: {TIMEOUT_SECONDS}s")
    print(f"🔀 TODAS {len(empresas)} INICIANDO SIMULTANEAMENTE!")
    print(f"{'='*60}\n", flush=True)
    
    results: List[CompanyResult] = []
    metrics = TestMetrics()
    
    start_time = time.perf_counter()
    
    # Connector com limite alto de conexões simultâneas
    connector = aiohttp.TCPConnector(limit=0, limit_per_host=0)  # Sem limite
    
    async with aiohttp.ClientSession(connector=connector) as session:
        # Criar todas as tasks
        total = len(empresas)
        tasks = [
            analyze_company(session, empresa, idx, total)
            for idx, empresa in enumerate(empresas)
        ]
        
        print(f"🚀 Disparando {len(tasks)} requisições SIMULTANEAMENTE...\n", flush=True)
        
        # asyncio.gather executa todas simultaneamente e espera todas terminarem
        results = await asyncio.gather(*tasks, return_exceptions=False)
    
    total_time = time.perf_counter() - start_time
    
    # Calcular métricas finais
    metrics.total_empresas = len(results)
    metrics.total_time_seconds = total_time
    
    success_times = []
    
    for r in results:
        if r.status == "success":
            metrics.success_count += 1
            success_times.append(r.execution_time_seconds)
        elif r.status == "not_found":
            metrics.not_found_count += 1
        elif r.status == "timeout":
            metrics.timeout_count += 1
        else:
            metrics.error_count += 1
            # Agrupar erros por tipo
            error_type = r.error_message.split(":")[0] if r.error_message else "Unknown"
            metrics.errors_by_type[error_type] = metrics.errors_by_type.get(error_type, 0) + 1
        
        # Distribuição de tempos
        time_cat = categorize_time(r.execution_time_seconds)
        metrics.time_distribution[time_cat] += 1
        
        # Min/Max
        if r.execution_time_seconds > 0:
            metrics.min_time = min(metrics.min_time, r.execution_time_seconds)
            metrics.max_time = max(metrics.max_time, r.execution_time_seconds)
    
    # Calcular médias
    if metrics.success_count > 0:
        metrics.avg_time_per_company = sum(success_times) / len(success_times)
    
    metrics.success_rate = (metrics.success_count / metrics.total_empresas * 100) if metrics.total_empresas > 0 else 0
    
    # Ajustar min_time se não houve resultados
    if metrics.min_time == float('inf'):
        metrics.min_time = 0
    
    return results, metrics

def save_results(results: List[CompanyResult], metrics: TestMetrics, output_dir: Path):
    """Salva resultados em arquivos JSON"""
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 1. Salvar todos os resultados detalhados
    results_file = output_dir / f"producao_results_{timestamp}.json"
    results_data = []
    
    for r in results:
        result_dict = {
            "cnpj": r.cnpj,
            "razao_social": r.razao_social,
            "nome_fantasia": r.nome_fantasia,
            "status": r.status,
            "http_code": r.http_code,
            "error_message": r.error_message,
            "execution_time_seconds": round(r.execution_time_seconds, 2),
            "discovered_url": r.discovered_url,
            "profile": r.profile
        }
        results_data.append(result_dict)
    
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n📁 Resultados salvos em: {results_file}")
    
    # 2. Salvar apenas os perfis de sucesso
    profiles_file = output_dir / f"producao_profiles_{timestamp}.json"
    profiles_data = []
    
    for r in results:
        if r.status == "success" and r.profile:
            profile_with_meta = {
                "cnpj": r.cnpj,
                "razao_social": r.razao_social,
                "nome_fantasia": r.nome_fantasia,
                "discovered_url": r.discovered_url,
                "execution_time_seconds": round(r.execution_time_seconds, 2),
                **r.profile
            }
            profiles_data.append(profile_with_meta)
    
    with open(profiles_file, 'w', encoding='utf-8') as f:
        json.dump(profiles_data, f, ensure_ascii=False, indent=2)
    
    print(f"📁 Perfis de sucesso salvos em: {profiles_file}")
    
    # 3. Salvar métricas
    metrics_file = output_dir / f"producao_metrics_{timestamp}.json"
    metrics_dict = {
        "timestamp": timestamp,
        "config": {
            "timeout_seconds": TIMEOUT_SECONDS,
            "max_concurrent": MAX_CONCURRENT,
            "api_url": API_URL
        },
        "summary": {
            "total_empresas": metrics.total_empresas,
            "success_count": metrics.success_count,
            "not_found_count": metrics.not_found_count,
            "timeout_count": metrics.timeout_count,
            "error_count": metrics.error_count,
            "success_rate_percent": round(metrics.success_rate, 2),
            "total_time_seconds": round(metrics.total_time_seconds, 2),
            "total_time_minutes": round(metrics.total_time_seconds / 60, 2),
            "avg_time_per_success_seconds": round(metrics.avg_time_per_company, 2),
            "min_time_seconds": round(metrics.min_time, 2),
            "max_time_seconds": round(metrics.max_time, 2),
            "throughput_per_minute": round(metrics.total_empresas / (metrics.total_time_seconds / 60), 2) if metrics.total_time_seconds > 0 else 0
        },
        "time_distribution": metrics.time_distribution,
        "errors_by_type": metrics.errors_by_type
    }
    
    with open(metrics_file, 'w', encoding='utf-8') as f:
        json.dump(metrics_dict, f, ensure_ascii=False, indent=2)
    
    print(f"📁 Métricas salvos em: {metrics_file}")
    
    return results_file, profiles_file, metrics_file

def print_summary(metrics: TestMetrics):
    """Imprime resumo do teste"""
    
    print(f"\n{'='*60}")
    print(f"📊 RESUMO DO TESTE DE PRODUÇÃO")
    print(f"{'='*60}")
    print(f"Total de empresas processadas: {metrics.total_empresas}")
    print(f"")
    print(f"✅ Sucesso:      {metrics.success_count:4d} ({metrics.success_rate:.1f}%)")
    print(f"🔍 Não encontrado: {metrics.not_found_count:4d} ({100*metrics.not_found_count/metrics.total_empresas:.1f}%)")
    print(f"⏱️  Timeout:      {metrics.timeout_count:4d} ({100*metrics.timeout_count/metrics.total_empresas:.1f}%)")
    print(f"❌ Erro:         {metrics.error_count:4d} ({100*metrics.error_count/metrics.total_empresas:.1f}%)")
    print(f"")
    print(f"⏱️  TEMPOS:")
    print(f"   Total:        {metrics.total_time_seconds/60:.1f} minutos")
    print(f"   Média/sucesso: {metrics.avg_time_per_company:.1f}s")
    print(f"   Mínimo:       {metrics.min_time:.1f}s")
    print(f"   Máximo:       {metrics.max_time:.1f}s")
    print(f"   Throughput:   {metrics.total_empresas / (metrics.total_time_seconds / 60):.1f} empresas/min")
    print(f"")
    print(f"📈 DISTRIBUIÇÃO DE TEMPOS:")
    for time_range, count in metrics.time_distribution.items():
        if count > 0:
            bar = "█" * int(count / metrics.total_empresas * 40)
            print(f"   {time_range:10s}: {count:4d} {bar}")
    
    if metrics.errors_by_type:
        print(f"\n❌ ERROS POR TIPO:")
        for error_type, count in sorted(metrics.errors_by_type.items(), key=lambda x: -x[1]):
            print(f"   {error_type}: {count}")
    
    print(f"{'='*60}\n")

async def main():
    """Função principal"""
    
    # Encontrar o arquivo de empresas
    script_dir = Path(__file__).parent.parent.parent
    empresas_file = script_dir / "empresas_teste_final.json"
    
    if not empresas_file.exists():
        print(f"❌ Arquivo não encontrado: {empresas_file}")
        sys.exit(1)
    
    # Carregar empresas
    with open(empresas_file, 'r', encoding='utf-8') as f:
        empresas = json.load(f)
    
    print(f"📂 Carregadas {len(empresas)} empresas de {empresas_file}")
    
    # Criar diretório de saída
    output_dir = script_dir / "tests" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Executar teste
    results, metrics = await run_test(empresas)
    
    # Salvar resultados
    save_results(results, metrics, output_dir)
    
    # Imprimir resumo
    print_summary(metrics)
    
    return results, metrics

if __name__ == "__main__":
    asyncio.run(main())

