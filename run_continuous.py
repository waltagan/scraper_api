#!/usr/bin/env python3
"""
Script de execução contínua do batch unificado.
Dispara o endpoint sync, espera a conclusão e redispara automaticamente.

Uso:
  python run_continuous.py                          # defaults (1000 empresas, loop infinito)
  python run_continuous.py --total 2000 --workers 8 # 2000 empresas, 8 parse workers
  python run_continuous.py --max-runs 5             # para após 5 runs
  python run_continuous.py --url http://localhost:8000  # servidor local
"""
import argparse
import json
import sys
import time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


DEFAULT_URL = "https://scraperapi-buscafornecedor-d46e.up.railway.app"
ENDPOINT = "/v2/scrape/main-page/unified/batch/sync"


def run_batch(base_url: str, payload: dict, timeout: int) -> dict:
    url = f"{base_url}{ENDPOINT}"
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    resp = urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Loop contínuo do batch unificado")
    parser.add_argument("--url", default=DEFAULT_URL, help="URL base da API")
    parser.add_argument("--total", type=int, default=3000, help="Empresas por run")
    parser.add_argument("--batch-size", type=int, default=3000, help="Tamanho do lote concorrente")
    parser.add_argument("--workers", type=int, default=6, help="Parse workers (loky)")
    parser.add_argument("--timeout-seconds", type=int, default=35, help="Timeout HTTP por empresa")
    parser.add_argument("--save-mode", default="final_only", help="checkpoint ou final_only")
    parser.add_argument("--save-in-batches", type=int, default=200, help="Tamanho do flush")
    parser.add_argument("--max-runs", type=int, default=300, help="Máximo de runs (0=infinito)")
    parser.add_argument("--pause", type=int, default=1, help="Pausa entre runs (segundos)")
    parser.add_argument("--http-timeout", type=int, default=600, help="Timeout HTTP total da request (segundos)")
    args = parser.parse_args()

    payload = {
        "total_samples": args.total,
        "batch_size": args.batch_size,
        "save_every": 100,
        "save_mode": args.save_mode,
        "save_in_batches": args.save_in_batches,
        "timeout_seconds": args.timeout_seconds,
        "redis_ttl_seconds": 600,
        "parse_workers": args.workers,
    }

    run_number = 0
    total_completed = 0
    total_persisted = 0
    total_elapsed = 0.0

    print(f"{'='*70}")
    print(f" Batch Contínuo — {args.total} empresas/run | workers={args.workers}")
    print(f" API: {args.url}")
    print(f" Max runs: {'infinito' if args.max_runs == 0 else args.max_runs}")
    print(f"{'='*70}\n")

    try:
        while True:
            run_number += 1
            if args.max_runs > 0 and run_number > args.max_runs:
                break

            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] Run #{run_number} iniciando ({args.total} empresas)...")

            try:
                t0 = time.time()
                result = run_batch(args.url, payload, args.http_timeout)
                wall = round(time.time() - t0, 1)

                status = result.get("status", "?")
                completed = result.get("completed", 0)
                persisted = result.get("persisted", 0)
                elapsed = result.get("elapsed_s", 0)
                run_id = result.get("run_id", "?")[:8]
                executor = result.get("executor_type", "?")
                loaded = result.get("loaded_from_db", 0)
                s1_pct = result.get("step1_success_pct", 0)
                s1_err = result.get("step1_errors", 0)
                s2_pct = result.get("step2_success_pct", 0)
                s2_err = result.get("step2_errors", 0)
                s3_pct = result.get("step3_success_pct", 0)
                s3_err = result.get("step3_errors", 0)

                total_completed += completed
                total_persisted += persisted
                total_elapsed += elapsed

                icon = "✅" if status == "success" else "⚠️"
                print(f"  {icon} run={run_id} | {elapsed}s | {executor} | carga={loaded}")
                print(f"     Step1: {s1_pct}% ok ({s1_err} erros) | Step2: {s2_pct}% ok ({s2_err} erros) | Step3: {s3_pct}% ok ({s3_err} erros)")
                print(f"     Salvas: {persisted}/{completed} | Acumulado: {total_persisted} salvas | {round(total_elapsed, 1)}s total\n")

            except HTTPError as e:
                print(f"  ❌ HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:200]}\n")
            except URLError as e:
                print(f"  ❌ Conexão falhou: {e.reason}\n")
            except Exception as e:
                print(f"  ❌ Erro: {type(e).__name__}: {e}\n")

            if args.max_runs > 0 and run_number >= args.max_runs:
                break

            if args.pause > 0:
                print(f"  ⏳ Aguardando {args.pause}s antes do próximo run...\n")
                time.sleep(args.pause)

    except KeyboardInterrupt:
        print(f"\n{'='*70}")
        print(f" Interrompido pelo usuário após {run_number} runs")

    print(f"\n{'='*70}")
    print(f" RESUMO FINAL")
    print(f"  Runs: {run_number}")
    print(f"  Processadas: {total_completed}")
    print(f"  Salvas: {total_persisted}")
    print(f"  Tempo total server: {round(total_elapsed, 1)}s")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
