"""
Benchmark de saturação de workers.
Testa diferentes quantidades de workers para encontrar o ponto ótimo.
"""
import subprocess
import time
import json
import sys
import os

BASE_URL = "http://localhost:8000"
LIMIT = 400
WORKER_COUNTS = [400, 600, 800, 1000, 1200]
POLL_INTERVAL = 5
MAX_WAIT = 300  # 5 min max por teste

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOG_DIR, "server_20260219.log")


def curl_json(method, path, data=None):
    cmd = ["curl", "-s"]
    if method == "POST":
        cmd += ["-X", "POST", "-H", "Content-Type: application/json"]
        if data:
            cmd += ["-d", json.dumps(data)]
    cmd.append(f"{BASE_URL}{path}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception as e:
        print(f"  Erro curl: {e}")
    return None


def wait_server_ready(timeout=30):
    for _ in range(timeout):
        r = curl_json("GET", "/health")
        if r and r.get("status") == "ok":
            return True
        time.sleep(1)
    return False


def start_server():
    open(LOG_FILE, "w").close()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"],
        cwd=os.path.dirname(__file__),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def stop_server(proc):
    proc.kill()
    proc.wait()
    subprocess.run(["pkill", "-9", "-f", "uvicorn"], capture_output=True)
    time.sleep(2)


def run_test(worker_count):
    print(f"\n{'='*60}")
    print(f"  TESTE: {worker_count} workers, {LIMIT} empresas")
    print(f"{'='*60}")

    proc = start_server()
    if not wait_server_ready():
        print("  ❌ Servidor não iniciou!")
        stop_server(proc)
        return None

    print(f"  ✅ Servidor pronto")

    r = curl_json("POST", "/v2/scrape/batch", {
        "limit": LIMIT,
        "worker_count": worker_count
    })
    if not r or not r.get("success"):
        print(f"  ❌ Falha ao iniciar batch: {r}")
        stop_server(proc)
        return None

    batch_id = r["batch_id"]
    print(f"  Batch {batch_id} iniciado")
    start = time.time()

    last_processed = 0
    stall_count = 0

    while time.time() - start < MAX_WAIT:
        time.sleep(POLL_INTERVAL)
        status = curl_json("GET", "/v2/scrape/batch/status")
        if not status:
            continue

        processed = status.get("processed", 0)
        success = status.get("success_count", 0)
        errors = status.get("error_count", 0)
        throughput = status.get("throughput_per_min", 0)
        elapsed = time.time() - start

        print(f"  [{elapsed:5.0f}s] {processed}/{LIMIT} "
              f"(✅{success} ❌{errors}) "
              f"throughput={throughput:.0f}/min")

        if processed == last_processed:
            stall_count += 1
            if stall_count >= 6:
                print("  ⚠️ Stall detectado! Abortando...")
                break
        else:
            stall_count = 0
        last_processed = processed

        if status.get("status") == "completed":
            break

    elapsed = time.time() - start
    final = curl_json("GET", "/v2/scrape/batch/status")

    stop_server(proc)

    if not final:
        return None

    result = {
        "workers": worker_count,
        "total": final.get("total", LIMIT),
        "processed": final.get("processed", 0),
        "success": final.get("success_count", 0),
        "errors": final.get("error_count", 0),
        "elapsed_s": round(elapsed, 1),
        "throughput_per_min": round(final.get("processed", 0) / elapsed * 60, 1),
        "success_rate": round(final.get("success_count", 0) / max(1, final.get("processed", 1)) * 100, 1),
        "status": final.get("status", "unknown"),
    }

    print(f"\n  Resultado: {result['processed']}/{result['total']} em {result['elapsed_s']}s")
    print(f"  Throughput: {result['throughput_per_min']:.0f} empresas/min")
    print(f"  Taxa sucesso: {result['success_rate']:.1f}%")

    return result


def main():
    print("=" * 60)
    print("  BENCHMARK DE SATURAÇÃO DE WORKERS")
    print(f"  Testando: {WORKER_COUNTS}")
    print(f"  Empresas por teste: {LIMIT}")
    print("=" * 60)

    results = []
    for wc in WORKER_COUNTS:
        result = run_test(wc)
        if result:
            results.append(result)
        time.sleep(3)

    print("\n\n" + "=" * 80)
    print("  RESUMO FINAL")
    print("=" * 80)
    print(f"{'Workers':>8} | {'Tempo(s)':>8} | {'Throughput':>12} | {'Sucesso':>8} | {'Erros':>6} | {'Taxa':>6}")
    print("-" * 80)
    for r in results:
        print(f"{r['workers']:>8} | {r['elapsed_s']:>8} | "
              f"{r['throughput_per_min']:>10.0f}/m | "
              f"{r['success']:>8} | {r['errors']:>6} | {r['success_rate']:>5.1f}%")

    if results:
        best = max(results, key=lambda x: x["throughput_per_min"])
        print(f"\n  🏆 MELHOR: {best['workers']} workers "
              f"→ {best['throughput_per_min']:.0f} empresas/min "
              f"(sucesso: {best['success_rate']:.1f}%)")

    with open("benchmark_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n  Resultados salvos em benchmark_results.json")


if __name__ == "__main__":
    main()
