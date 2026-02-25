# Stress Test Unificado — 711Proxy + Decodo + Evomi

**Data:** 2026-02-24 15:34:25
**Timeout:** 40s
**Níveis testados:** 1200
**Fonte de URLs:** `busca_fornecedor.website_discovery` (discovery_status = 'alto')
**711Proxy:** 900 proxies
**Decodo:** 9999 proxies
**Evomi:** 10000 proxies

---


## Comparativo Geral entre Providers

### Taxa de Sucesso (%) por Nível

| Nível |   711Proxy   |    Decodo    |    Evomi     |
|-------|--------------|--------------|--------------|
| 1200  |    92.7%     |    73.9%     |    94.1%     |

### Latência p50 (ms) por Nível

| Nível |   711Proxy   |    Decodo    |    Evomi     |
|-------|--------------|--------------|--------------|
| 1200  |   7334.1ms   |  17618.4ms   |  17198.9ms   |

### Latência p90 (ms) por Nível

| Nível |   711Proxy   |    Decodo    |    Evomi     |
|-------|--------------|--------------|--------------|
| 1200  |  11031.3ms   |  21262.1ms   |  20727.3ms   |

### Throughput (req/min) por Nível

| Nível |   711Proxy   |    Decodo    |    Evomi     |
|-------|--------------|--------------|--------------|
| 1200  |    1780.0    |    1784.8    |    1784.7    |

### Coeficiente de Variação de Latência por Nível
(>1.0 = proxy instável/sobrecarregado | <0.5 = estável)

| Nível |   711Proxy   |    Decodo    |    Evomi     |
|-------|--------------|--------------|--------------|
| 1200  |    0.537     |    0.282     |    0.233     |

### Diagnóstico de Gargalo por Nível

| Nível | Provider | Diagnóstico |
|-------|----------|-------------|
| 1200 | 711Proxy | proxy saudável — absorveu a carga sem degradação severa |
| 1200 | Decodo | proxy sob pressão — latência elevada mas ainda funcional |
| 1200 | Evomi | proxy sob pressão — latência elevada mas ainda funcional |

### Ranking de Melhor Provider por Nível (por success rate)

| Nível | 1º | 2º | 3º |
|-------|-----|-----|-----|
| 1200 | Evomi (94.1%) | 711Proxy (92.7%) | Decodo (73.9%) |


## Análise de Capacidade por Provider

### 711Proxy

- **Carga ideal** (success ≥90%, p90 ≤15s): **1200** links
- **Carga máxima** (success ≥70%): **1200** links
- **Ponto de degradação** (success <80%): **não atingido**

| Nível | Success% | p50ms | p90ms | p99ms | Erros | BW Mbps | Avaliação |
|-------|----------|-------|-------|-------|-------|---------|-----------|
| 1200 | 92.7% | 7334.1 | 11031.3 | 18539.2 | 88 | 56.83 | ✅ Ótimo |

### Decodo

- **Carga ideal** (success ≥90%, p90 ≤15s): **N/A** links
- **Carga máxima** (success ≥70%): **1200** links
- **Ponto de degradação** (success <80%): **1200**

| Nível | Success% | p50ms | p90ms | p99ms | Erros | BW Mbps | Avaliação |
|-------|----------|-------|-------|-------|-------|---------|-----------|
| 1200 | 73.9% | 17618.4 | 21262.1 | 25330.2 | 313 | 48.77 | 🔶 Degradado |

### Evomi

- **Carga ideal** (success ≥90%, p90 ≤15s): **N/A** links
- **Carga máxima** (success ≥70%): **1200** links
- **Ponto de degradação** (success <80%): **não atingido**

| Nível | Success% | p50ms | p90ms | p99ms | Erros | BW Mbps | Avaliação |
|-------|----------|-------|-------|-------|-------|---------|-----------|
| 1200 | 94.1% | 17198.9 | 20727.3 | 26760.2 | 71 | 56.85 | ✅ Ótimo |


## Gráfico: Taxa de Sucesso (%) por Nível de Carga

Nível    Provider         %  Barra
-----------------------------------------------------------------
1200     711Proxy      92.7%  ████████████████████████████░░
1200     Decodo        73.9%  ██████████████████████░░░░░░░░
1200     Evomi         94.1%  ████████████████████████████░░


## Gráfico: Latência p50 (ms) por Nível de Carga

Nível    Provider       p50ms  Barra
-----------------------------------------------------------------
1200     711Proxy      7334.1ms  ████████████░░░░░░░░░░░░░░░░░░
1200     Decodo       17618.4ms  ██████████████████████████████
1200     Evomi        17198.9ms  █████████████████████████████░


## Gráfico: Throughput (req/min) por Nível de Carga

Nível    Provider      req/min  Barra
-----------------------------------------------------------------
1200     711Proxy         1780  ██████████████████████████████
1200     Decodo           1785  ██████████████████████████████
1200     Evomi            1785  ██████████████████████████████


## Gráfico: Distribuição de Erros por Terço do Teste

(Mostra se os erros aumentam ao longo do tempo — indica degradação)

### Nível 1200
Provider      1º terço  2º terço  3º terço  Tendência
-------------------------------------------------------
711Proxy            25        34        29  → estável
Decodo              95        85       133  ↑ piora
Evomi               36        14        21  ↓ melhora


## Gráfico: Coeficiente de Variação de Latência (CV)

(CV = stdev/média | >1.0 = proxy muito instável | <0.5 = estável)

Nível    Provider         CV  Barra
-----------------------------------------------------------------
1200     711Proxy      0.537  ████████░░░░░░░░░░░░░░░░░░░░░░
1200     Decodo        0.282  ████░░░░░░░░░░░░░░░░░░░░░░░░░░
1200     Evomi         0.233  ███░░░░░░░░░░░░░░░░░░░░░░░░░░░


## Gráfico: Bandwidth p50 (MB/s) por Nível

(Calculado a partir de amostras de 0.5s durante o teste)

Nível    Provider      p50 MB/s  Barra
-----------------------------------------------------------------
1200     711Proxy         0.100  █████░░░░░░░░░░░░░░░░░░░░░░░░░
1200     Decodo           0.600  ██████████████████████████████
1200     Evomi            0.000  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░


---

## Detalhes por Nível de Carga

### Nível 1200 links

#### 711Proxy — 1200 links

- **Success:** 1112 / 1200 (92.7%)
- **Tempo total:** 40.5s
- **Throughput:** 1780.0 req/min
- **Bandwidth:** 56.83 Mbps | **Dados:** 287.35 MB
- **Peak connections:** 1199
- **Ponto de degradação:** não detectado

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 5936.4 | 7334.1 | 9217.6 | 11031.3 | 12546.6 | 18539.2 | 32346.5 | 7856.9 | 3040.2 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 7779.2 | 35428.6 | 40355.0 | 40355.0 | 12025.7 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| connection | 58 |
| http_403 | 10 |
| http_404 | 7 |
| timeout | 5 |
| http_500 | 5 |
| http_503 | 1 |
| http_410 | 1 |
| other | 1 |

**Diagnóstico sob Carga Total:**

> **proxy saudável — absorveu a carga sem degradação severa**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 8162.6ms | Tempo médio efetivo de rede |
| CV Latência | 0.537 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 1200 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 201.5 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 5895.6 | 7342.9 | 9315.3 | 11237.4 | 13645.5 | 32651.8 | 40355.0 | 8162.6 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 0.1 | 3.4 | 35.2 | 45.7 | 62.5 | 7.3 | 15.4 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 1 | 5 | 6 | 83.3% |
| 3-6s | 293 | 24 | 317 | 7.6% |
| 6-10s | 611 | 32 | 643 | 5.0% |
| 10-15s | 181 | 11 | 192 | 5.7% |
| 15-20s | 16 | 1 | 17 | 5.9% |
| 20-30s | 9 | 1 | 10 | 10.0% |
| 30-40s | 1 | 9 | 10 | 90.0% |
| 40s+ | 0 | 5 | 5 | 100.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 111 | 20 | 84.7% | 4308.3 | 4797.3 | 2.724 |
| 5s-10s | 784 | 41 | 95.0% | 7085.5 | 8921.7 | 42.3 |
| 10s-15s | 191 | 11 | 94.6% | 10939.5 | 13487.0 | 11.431 |
| 15s-20s | 16 | 1 | 94.1% | 17088.9 | 18539.2 | 0.554 |
| 20s-25s | 6 | 0 | 100.0% | 23987.2 | 24680.5 | 0.302 |
| 25s-30s | 3 | 1 | 75.0% | 27465.6 | 27839.7 | 0.14 |
| 30s-35s | 1 | 5 | 16.7% | 32346.5 | 32346.5 | 0.018 |
| 35s-40s | 0 | 4 | 0.0% | 0 | 0 | 0.0 |
| 40s-45s | 0 | 5 | 0.0% | 0 | 0 | 0.0 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 120 | 10% | 7.5% |
| 240 | 20% | 6.7% |
| 360 | 30% | 6.4% |
| 480 | 40% | 6.7% |
| 600 | 50% | 7.5% |
| 720 | 60% | 7.2% |
| 840 | 70% | 7.7% |
| 960 | 80% | 7.6% |
| 1080 | 90% | 7.4% |
| 1200 | 100% | 7.3% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 25 | 34 | 29 | → estável |

#### Decodo — 1200 links

- **Success:** 887 / 1200 (73.9%)
- **Tempo total:** 40.3s
- **Throughput:** 1784.8 req/min
- **Bandwidth:** 48.77 Mbps | **Dados:** 245.92 MB
- **Peak connections:** 1199
- **Ponto de degradação:** 6-10s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 14678.9 | 17618.4 | 19503.4 | 21262.1 | 22934.8 | 25330.2 | 39946.9 | 16720.3 | 4731.1 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 16912.6 | 20116.8 | 28769.0 | 40210.1 | 16232.5 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| dns | 173 |
| connection | 98 |
| http_522 | 19 |
| http_403 | 7 |
| http_500 | 5 |
| http_404 | 5 |
| other | 2 |
| timeout | 2 |
| http_410 | 1 |
| http_502 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy sob pressão — latência elevada mas ainda funcional**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 16593.0ms | Tempo médio efetivo de rede |
| CV Latência | 0.282 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 1200 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 478.6 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 14471.2 | 17392.3 | 19310.9 | 21044.7 | 22635.4 | 25483.3 | 40210.1 | 16593.0 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 0.6 | 7.8 | 20.7 | 27.0 | 54.4 | 6.2 | 10.4 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 0 | 2 | 2 | 100.0% |
| 3-6s | 58 | 7 | 65 | 10.8% |
| 6-10s | 24 | 11 | 35 | 31.4% |
| 10-15s | 166 | 80 | 246 | 32.5% |
| 15-20s | 470 | 177 | 647 | 27.4% |
| 20-30s | 166 | 34 | 200 | 17.0% |
| 30-40s | 3 | 0 | 3 | 0.0% |
| 40s+ | 0 | 2 | 2 | 100.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 39 | 8 | 83.0% | 4511.3 | 4907.0 | 1.397 |
| 5s-10s | 43 | 12 | 78.2% | 6256.2 | 8288.4 | 3.204 |
| 10s-15s | 162 | 78 | 67.5% | 13823.6 | 14748.0 | 7.495 |
| 15s-20s | 467 | 178 | 72.4% | 17904.9 | 19502.1 | 22.269 |
| 20s-25s | 162 | 32 | 83.5% | 21191.6 | 23628.8 | 13.865 |
| 25s-30s | 11 | 3 | 78.6% | 25330.2 | 27012.4 | 0.746 |
| 30s-35s | 1 | 0 | 100.0% | 33029.3 | 33029.3 | 0.057 |
| 35s-40s | 1 | 0 | 100.0% | 38915.2 | 38915.2 | 0.07 |
| 40s-45s | 1 | 2 | 33.3% | 39946.9 | 39946.9 | 0.08 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 120 | 10% | 26.7% |
| 240 | 20% | 20.0% |
| 360 | 30% | 23.3% |
| 480 | 40% | 23.1% |
| 600 | 50% | 22.3% |
| 720 | 60% | 21.8% |
| 840 | 70% | 22.6% |
| 960 | 80% | 24.5% |
| 1080 | 90% | 25.4% |
| 1200 | 100% | 26.1% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 95 | 85 | 133 | ↑ piora ao longo do tempo |

#### Evomi — 1200 links

- **Success:** 1129 / 1200 (94.1%)
- **Tempo total:** 40.3s
- **Throughput:** 1784.7 req/min
- **Bandwidth:** 56.85 Mbps | **Dados:** 286.68 MB
- **Peak connections:** 1199
- **Ponto de degradação:** 3-6s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 15176.1 | 17198.9 | 19332.8 | 20727.3 | 21819.3 | 26760.2 | 38910.0 | 17509.0 | 2879.9 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 15976.9 | 40160.3 | 40246.8 | 40246.8 | 18507.6 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| dns | 17 |
| connection | 14 |
| http_500 | 13 |
| timeout | 9 |
| http_403 | 7 |
| http_404 | 6 |
| ssl | 2 |
| http_503 | 1 |
| other | 1 |
| http_410 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy sob pressão — latência elevada mas ainda funcional**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 17568.1ms | Tempo médio efetivo de rede |
| CV Latência | 0.233 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 1200 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 492.4 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 15038.8 | 17120.9 | 19388.7 | 20871.3 | 22182.1 | 39212.0 | 40246.8 | 17568.1 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 0.0 | 4.2 | 30.3 | 44.2 | 72.3 | 7.4 | 14.8 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 3-6s | 0 | 17 | 17 | 100.0% |
| 10-15s | 262 | 15 | 277 | 5.4% |
| 15-20s | 640 | 18 | 658 | 2.7% |
| 20-30s | 222 | 6 | 228 | 2.6% |
| 30-40s | 5 | 5 | 10 | 50.0% |
| 40s+ | 0 | 10 | 10 | 100.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 0 | 13 | 0.0% | 0 | 0 | 0.0 |
| 5s-10s | 0 | 4 | 0.0% | 0 | 0 | 0.0 |
| 10s-15s | 258 | 15 | 94.5% | 14265.8 | 14639.5 | 10.021 |
| 15s-20s | 644 | 18 | 97.3% | 17265.0 | 19275.1 | 34.023 |
| 20s-25s | 211 | 5 | 97.7% | 20630.0 | 22562.3 | 12.327 |
| 25s-30s | 11 | 1 | 91.7% | 26772.4 | 29032.8 | 0.536 |
| 30s-35s | 3 | 0 | 100.0% | 30394.0 | 34645.0 | 0.267 |
| 35s-40s | 2 | 5 | 28.6% | 38910.0 | 38910.0 | 0.162 |
| 40s-45s | 0 | 10 | 0.0% | 0 | 0 | 0.0 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 120 | 10% | 5.8% |
| 240 | 20% | 11.7% |
| 360 | 30% | 9.2% |
| 480 | 40% | 7.9% |
| 600 | 50% | 7.0% |
| 720 | 60% | 6.2% |
| 840 | 70% | 6.0% |
| 960 | 80% | 6.1% |
| 1080 | 90% | 5.6% |
| 1200 | 100% | 5.9% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 36 | 14 | 21 | ↓ melhora ao longo do tempo |

---


## Dados Brutos (JSON)

```json
{
  "1200": {
    "711proxy": {
      "provider": "711proxy",
      "concurrency": 1200,
      "total_urls": 1200,
      "total_time_s": 40.5,
      "throughput_per_min": 1780.0,
      "success": 1112,
      "fail": 88,
      "success_rate_pct": 92.7,
      "latency_all_ms": {
        "min": 2285.2,
        "p25": 5895.6,
        "p50": 7342.9,
        "p75": 9315.3,
        "p90": 11237.4,
        "p95": 13645.5,
        "p99": 32651.8,
        "max": 40355.0,
        "avg": 8162.6,
        "stdev": 4384.0
      },
      "latency_ok_ms": {
        "min": 2396.2,
        "p25": 5936.4,
        "p50": 7334.1,
        "p75": 9217.6,
        "p90": 11031.3,
        "p95": 12546.6,
        "p99": 18539.2,
        "max": 32346.5,
        "avg": 7856.9,
        "stdev": 3040.2
      },
      "latency_fail_ms": {
        "min": 2285.2,
        "p25": 5153.2,
        "p50": 7779.2,
        "p75": 11726.8,
        "p90": 35428.6,
        "p95": 40115.0,
        "p99": 40355.0,
        "max": 40355.0,
        "avg": 12025.7,
        "stdev": 11425.9
      },
      "http_time_ms": {
        "min": 2285.2,
        "p25": 5895.6,
        "p50": 7342.9,
        "p75": 9315.3,
        "p90": 11237.4,
        "p95": 13645.5,
        "p99": 32651.8,
        "max": 40355.0,
        "avg": 8162.6,
        "stdev": 4384.0
      },
      "error_breakdown": {
        "connection": 58,
        "http_403": 10,
        "http_404": 7,
        "timeout": 5,
        "http_500": 5,
        "http_503": 1,
        "http_410": 1,
        "other": 1
      },
      "content_size_bytes": {
        "min": 49,
        "p25": 45049,
        "p50": 129221,
        "p75": 268711,
        "p90": 603396,
        "p95": 925807,
        "p99": 1880857,
        "max": 9071284,
        "avg": 258043.0,
        "stdev": 486240.7
      },
      "total_data_mb": 287.35,
      "bandwidth_mbps": 56.83,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 0.1,
        "p75": 3.4,
        "p90": 35.2,
        "p95": 45.7,
        "p99": 62.5,
        "max": 62.5,
        "avg": 7.3,
        "stdev": 15.4
      },
      "connections": {
        "peak": 1199,
        "samples": {
          "min": 0,
          "p25": 15,
          "p50": 25,
          "p75": 117,
          "p90": 1000,
          "p95": 1188,
          "p99": 1200,
          "max": 1200,
          "avg": 201.5,
          "stdev": 368.4
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 1,
          "fail": 5
        },
        "3-6s": {
          "ok": 293,
          "fail": 24
        },
        "6-10s": {
          "ok": 611,
          "fail": 32
        },
        "10-15s": {
          "ok": 181,
          "fail": 11
        },
        "15-20s": {
          "ok": 16,
          "fail": 1
        },
        "20-30s": {
          "ok": 9,
          "fail": 1
        },
        "30-40s": {
          "ok": 1,
          "fail": 9
        },
        "40s+": {
          "ok": 0,
          "fail": 5
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 25,
        "t2_mid_third": 34,
        "t3_last_third": 29
      },
      "degradation_point": null,
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 111,
          "fail": 20,
          "total": 131,
          "success_pct": 84.7,
          "lat_ok_p50_ms": 4308.3,
          "lat_ok_p90_ms": 4797.3,
          "lat_all_p50_ms": 4281.2,
          "bw_mbs": 2.724
        },
        {
          "t": "5s-10s",
          "ok": 784,
          "fail": 41,
          "total": 825,
          "success_pct": 95.0,
          "lat_ok_p50_ms": 7085.5,
          "lat_ok_p90_ms": 8921.7,
          "lat_all_p50_ms": 7082.1,
          "bw_mbs": 42.3
        },
        {
          "t": "10s-15s",
          "ok": 191,
          "fail": 11,
          "total": 202,
          "success_pct": 94.6,
          "lat_ok_p50_ms": 10939.5,
          "lat_ok_p90_ms": 13487.0,
          "lat_all_p50_ms": 10965.4,
          "bw_mbs": 11.431
        },
        {
          "t": "15s-20s",
          "ok": 16,
          "fail": 1,
          "total": 17,
          "success_pct": 94.1,
          "lat_ok_p50_ms": 17088.9,
          "lat_ok_p90_ms": 18539.2,
          "lat_all_p50_ms": 16024.5,
          "bw_mbs": 0.554
        },
        {
          "t": "20s-25s",
          "ok": 6,
          "fail": 0,
          "total": 6,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 23987.2,
          "lat_ok_p90_ms": 24680.5,
          "lat_all_p50_ms": 23987.2,
          "bw_mbs": 0.302
        },
        {
          "t": "25s-30s",
          "ok": 3,
          "fail": 1,
          "total": 4,
          "success_pct": 75.0,
          "lat_ok_p50_ms": 27465.6,
          "lat_ok_p90_ms": 27839.7,
          "lat_all_p50_ms": 27465.6,
          "bw_mbs": 0.14
        },
        {
          "t": "30s-35s",
          "ok": 1,
          "fail": 5,
          "total": 6,
          "success_pct": 16.7,
          "lat_ok_p50_ms": 32346.5,
          "lat_ok_p90_ms": 32346.5,
          "lat_all_p50_ms": 32651.8,
          "bw_mbs": 0.018
        },
        {
          "t": "35s-40s",
          "ok": 0,
          "fail": 4,
          "total": 4,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 39046.7,
          "bw_mbs": 0.0
        },
        {
          "t": "40s-45s",
          "ok": 0,
          "fail": 5,
          "total": 5,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 40125.1,
          "bw_mbs": 0.0
        }
      ],
      "saturation": {
        "avg_http_time_ms": 8162.6,
        "avg_elapsed_ms": 8162.6,
        "cv_latency": 0.537,
        "peak_active": 1200,
        "peak_active_pct": 100.0,
        "avg_active_connections": 201.5,
        "bottleneck_diagnosis": "proxy saudável — absorveu a carga sem degradação severa"
      },
      "cumulative_error_rate": [
        {
          "at_request": 120,
          "pct_complete": 10.0,
          "error_rate_pct": 7.5
        },
        {
          "at_request": 240,
          "pct_complete": 20.0,
          "error_rate_pct": 6.7
        },
        {
          "at_request": 360,
          "pct_complete": 30.0,
          "error_rate_pct": 6.4
        },
        {
          "at_request": 480,
          "pct_complete": 40.0,
          "error_rate_pct": 6.7
        },
        {
          "at_request": 600,
          "pct_complete": 50.0,
          "error_rate_pct": 7.5
        },
        {
          "at_request": 720,
          "pct_complete": 60.0,
          "error_rate_pct": 7.2
        },
        {
          "at_request": 840,
          "pct_complete": 70.0,
          "error_rate_pct": 7.7
        },
        {
          "at_request": 960,
          "pct_complete": 80.0,
          "error_rate_pct": 7.6
        },
        {
          "at_request": 1080,
          "pct_complete": 90.0,
          "error_rate_pct": 7.4
        },
        {
          "at_request": 1200,
          "pct_complete": 100.0,
          "error_rate_pct": 7.3
        }
      ]
    },
    "decodo": {
      "provider": "decodo",
      "concurrency": 1200,
      "total_urls": 1200,
      "total_time_s": 40.3,
      "throughput_per_min": 1784.8,
      "success": 887,
      "fail": 313,
      "success_rate_pct": 73.9,
      "latency_all_ms": {
        "min": 1861.6,
        "p25": 14471.2,
        "p50": 17392.3,
        "p75": 19310.9,
        "p90": 21044.7,
        "p95": 22635.4,
        "p99": 25483.3,
        "max": 40210.1,
        "avg": 16593.0,
        "stdev": 4677.9
      },
      "latency_ok_ms": {
        "min": 3312.4,
        "p25": 14678.9,
        "p50": 17618.4,
        "p75": 19503.4,
        "p90": 21262.1,
        "p95": 22934.8,
        "p99": 25330.2,
        "max": 39946.9,
        "avg": 16720.3,
        "stdev": 4731.1
      },
      "latency_fail_ms": {
        "min": 1861.6,
        "p25": 13973.4,
        "p50": 16912.6,
        "p75": 18639.5,
        "p90": 20116.8,
        "p95": 21451.5,
        "p99": 28769.0,
        "max": 40210.1,
        "avg": 16232.5,
        "stdev": 4511.6
      },
      "http_time_ms": {
        "min": 1861.6,
        "p25": 14471.2,
        "p50": 17392.3,
        "p75": 19310.9,
        "p90": 21044.7,
        "p95": 22635.4,
        "p99": 25483.3,
        "max": 40210.1,
        "avg": 16593.0,
        "stdev": 4677.9
      },
      "error_breakdown": {
        "dns": 173,
        "connection": 98,
        "http_522": 19,
        "http_403": 7,
        "http_500": 5,
        "http_404": 5,
        "other": 2,
        "timeout": 2,
        "http_410": 1,
        "http_502": 1
      },
      "content_size_bytes": {
        "min": 49,
        "p25": 60348,
        "p50": 139248,
        "p75": 311844,
        "p90": 617648,
        "p95": 981160,
        "p99": 1895764,
        "max": 9071284,
        "avg": 276812.2,
        "stdev": 508275.5
      },
      "total_data_mb": 245.92,
      "bandwidth_mbps": 48.77,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 0.6,
        "p75": 7.8,
        "p90": 20.7,
        "p95": 27.0,
        "p99": 54.4,
        "max": 54.4,
        "avg": 6.2,
        "stdev": 10.4
      },
      "connections": {
        "peak": 1199,
        "samples": {
          "min": 0,
          "p25": 5,
          "p50": 142,
          "p75": 1095,
          "p90": 1190,
          "p95": 1199,
          "p99": 1200,
          "max": 1200,
          "avg": 478.6,
          "stdev": 511.5
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 0,
          "fail": 2
        },
        "3-6s": {
          "ok": 58,
          "fail": 7
        },
        "6-10s": {
          "ok": 24,
          "fail": 11
        },
        "10-15s": {
          "ok": 166,
          "fail": 80
        },
        "15-20s": {
          "ok": 470,
          "fail": 177
        },
        "20-30s": {
          "ok": 166,
          "fail": 34
        },
        "30-40s": {
          "ok": 3,
          "fail": 0
        },
        "40s+": {
          "ok": 0,
          "fail": 2
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 95,
        "t2_mid_third": 85,
        "t3_last_third": 133
      },
      "degradation_point": "6-10s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 39,
          "fail": 8,
          "total": 47,
          "success_pct": 83.0,
          "lat_ok_p50_ms": 4511.3,
          "lat_ok_p90_ms": 4907.0,
          "lat_all_p50_ms": 4385.1,
          "bw_mbs": 1.397
        },
        {
          "t": "5s-10s",
          "ok": 43,
          "fail": 12,
          "total": 55,
          "success_pct": 78.2,
          "lat_ok_p50_ms": 6256.2,
          "lat_ok_p90_ms": 8288.4,
          "lat_all_p50_ms": 6464.4,
          "bw_mbs": 3.204
        },
        {
          "t": "10s-15s",
          "ok": 162,
          "fail": 78,
          "total": 240,
          "success_pct": 67.5,
          "lat_ok_p50_ms": 13823.6,
          "lat_ok_p90_ms": 14748.0,
          "lat_all_p50_ms": 13498.3,
          "bw_mbs": 7.495
        },
        {
          "t": "15s-20s",
          "ok": 467,
          "fail": 178,
          "total": 645,
          "success_pct": 72.4,
          "lat_ok_p50_ms": 17904.9,
          "lat_ok_p90_ms": 19502.1,
          "lat_all_p50_ms": 17850.6,
          "bw_mbs": 22.269
        },
        {
          "t": "20s-25s",
          "ok": 162,
          "fail": 32,
          "total": 194,
          "success_pct": 83.5,
          "lat_ok_p50_ms": 21191.6,
          "lat_ok_p90_ms": 23628.8,
          "lat_all_p50_ms": 21109.3,
          "bw_mbs": 13.865
        },
        {
          "t": "25s-30s",
          "ok": 11,
          "fail": 3,
          "total": 14,
          "success_pct": 78.6,
          "lat_ok_p50_ms": 25330.2,
          "lat_ok_p90_ms": 27012.4,
          "lat_all_p50_ms": 25483.3,
          "bw_mbs": 0.746
        },
        {
          "t": "30s-35s",
          "ok": 1,
          "fail": 0,
          "total": 1,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 33029.3,
          "lat_ok_p90_ms": 33029.3,
          "lat_all_p50_ms": 33029.3,
          "bw_mbs": 0.057
        },
        {
          "t": "35s-40s",
          "ok": 1,
          "fail": 0,
          "total": 1,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 38915.2,
          "lat_ok_p90_ms": 38915.2,
          "lat_all_p50_ms": 38915.2,
          "bw_mbs": 0.07
        },
        {
          "t": "40s-45s",
          "ok": 1,
          "fail": 2,
          "total": 3,
          "success_pct": 33.3,
          "lat_ok_p50_ms": 39946.9,
          "lat_ok_p90_ms": 39946.9,
          "lat_all_p50_ms": 40148.9,
          "bw_mbs": 0.08
        }
      ],
      "saturation": {
        "avg_http_time_ms": 16593.0,
        "avg_elapsed_ms": 16593.0,
        "cv_latency": 0.282,
        "peak_active": 1200,
        "peak_active_pct": 100.0,
        "avg_active_connections": 478.6,
        "bottleneck_diagnosis": "proxy sob pressão — latência elevada mas ainda funcional"
      },
      "cumulative_error_rate": [
        {
          "at_request": 120,
          "pct_complete": 10.0,
          "error_rate_pct": 26.7
        },
        {
          "at_request": 240,
          "pct_complete": 20.0,
          "error_rate_pct": 20.0
        },
        {
          "at_request": 360,
          "pct_complete": 30.0,
          "error_rate_pct": 23.3
        },
        {
          "at_request": 480,
          "pct_complete": 40.0,
          "error_rate_pct": 23.1
        },
        {
          "at_request": 600,
          "pct_complete": 50.0,
          "error_rate_pct": 22.3
        },
        {
          "at_request": 720,
          "pct_complete": 60.0,
          "error_rate_pct": 21.8
        },
        {
          "at_request": 840,
          "pct_complete": 70.0,
          "error_rate_pct": 22.6
        },
        {
          "at_request": 960,
          "pct_complete": 80.0,
          "error_rate_pct": 24.5
        },
        {
          "at_request": 1080,
          "pct_complete": 90.0,
          "error_rate_pct": 25.4
        },
        {
          "at_request": 1200,
          "pct_complete": 100.0,
          "error_rate_pct": 26.1
        }
      ]
    },
    "evomi": {
      "provider": "evomi",
      "concurrency": 1200,
      "total_urls": 1200,
      "total_time_s": 40.3,
      "throughput_per_min": 1784.7,
      "success": 1129,
      "fail": 71,
      "success_rate_pct": 94.1,
      "latency_all_ms": {
        "min": 4060.1,
        "p25": 15038.8,
        "p50": 17120.9,
        "p75": 19388.7,
        "p90": 20871.3,
        "p95": 22182.1,
        "p99": 39212.0,
        "max": 40246.8,
        "avg": 17568.1,
        "stdev": 4098.0
      },
      "latency_ok_ms": {
        "min": 11989.6,
        "p25": 15176.1,
        "p50": 17198.9,
        "p75": 19332.8,
        "p90": 20727.3,
        "p95": 21819.3,
        "p99": 26760.2,
        "max": 38910.0,
        "avg": 17509.0,
        "stdev": 2879.9
      },
      "latency_fail_ms": {
        "min": 4060.1,
        "p25": 11530.9,
        "p50": 15976.9,
        "p75": 20693.6,
        "p90": 40160.3,
        "p95": 40232.4,
        "p99": 40246.8,
        "max": 40246.8,
        "avg": 18507.6,
        "stdev": 12371.4
      },
      "http_time_ms": {
        "min": 4060.1,
        "p25": 15038.8,
        "p50": 17120.9,
        "p75": 19388.7,
        "p90": 20871.3,
        "p95": 22182.1,
        "p99": 39212.0,
        "max": 40246.8,
        "avg": 17568.1,
        "stdev": 4098.0
      },
      "error_breakdown": {
        "dns": 17,
        "connection": 14,
        "http_500": 13,
        "timeout": 9,
        "http_403": 7,
        "http_404": 6,
        "ssl": 2,
        "http_503": 1,
        "other": 1,
        "http_410": 1
      },
      "content_size_bytes": {
        "min": 49,
        "p25": 47790,
        "p50": 129431,
        "p75": 271147,
        "p90": 605006,
        "p95": 924473,
        "p99": 1778107,
        "max": 6190987,
        "avg": 253576.6,
        "stdev": 408899.6
      },
      "total_data_mb": 286.68,
      "bandwidth_mbps": 56.85,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 0.0,
        "p75": 4.2,
        "p90": 30.3,
        "p95": 44.2,
        "p99": 72.3,
        "max": 72.3,
        "avg": 7.4,
        "stdev": 14.8
      },
      "connections": {
        "peak": 1199,
        "samples": {
          "min": 0,
          "p25": 18,
          "p50": 121,
          "p75": 1183,
          "p90": 1200,
          "p95": 1200,
          "p99": 1200,
          "max": 1200,
          "avg": 492.4,
          "stdev": 531.3
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 0,
          "fail": 0
        },
        "3-6s": {
          "ok": 0,
          "fail": 17
        },
        "6-10s": {
          "ok": 0,
          "fail": 0
        },
        "10-15s": {
          "ok": 262,
          "fail": 15
        },
        "15-20s": {
          "ok": 640,
          "fail": 18
        },
        "20-30s": {
          "ok": 222,
          "fail": 6
        },
        "30-40s": {
          "ok": 5,
          "fail": 5
        },
        "40s+": {
          "ok": 0,
          "fail": 10
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 36,
        "t2_mid_third": 14,
        "t3_last_third": 21
      },
      "degradation_point": "3-6s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 0,
          "fail": 13,
          "total": 13,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 4073.9,
          "bw_mbs": 0.0
        },
        {
          "t": "5s-10s",
          "ok": 0,
          "fail": 4,
          "total": 4,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 5215.9,
          "bw_mbs": 0.0
        },
        {
          "t": "10s-15s",
          "ok": 258,
          "fail": 15,
          "total": 273,
          "success_pct": 94.5,
          "lat_ok_p50_ms": 14265.8,
          "lat_ok_p90_ms": 14639.5,
          "lat_all_p50_ms": 14265.6,
          "bw_mbs": 10.021
        },
        {
          "t": "15s-20s",
          "ok": 644,
          "fail": 18,
          "total": 662,
          "success_pct": 97.3,
          "lat_ok_p50_ms": 17265.0,
          "lat_ok_p90_ms": 19275.1,
          "lat_all_p50_ms": 17264.2,
          "bw_mbs": 34.023
        },
        {
          "t": "20s-25s",
          "ok": 211,
          "fail": 5,
          "total": 216,
          "success_pct": 97.7,
          "lat_ok_p50_ms": 20630.0,
          "lat_ok_p90_ms": 22562.3,
          "lat_all_p50_ms": 20635.4,
          "bw_mbs": 12.327
        },
        {
          "t": "25s-30s",
          "ok": 11,
          "fail": 1,
          "total": 12,
          "success_pct": 91.7,
          "lat_ok_p50_ms": 26772.4,
          "lat_ok_p90_ms": 29032.8,
          "lat_all_p50_ms": 27475.6,
          "bw_mbs": 0.536
        },
        {
          "t": "30s-35s",
          "ok": 3,
          "fail": 0,
          "total": 3,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 30394.0,
          "lat_ok_p90_ms": 34645.0,
          "lat_all_p50_ms": 30394.0,
          "bw_mbs": 0.267
        },
        {
          "t": "35s-40s",
          "ok": 2,
          "fail": 5,
          "total": 7,
          "success_pct": 28.6,
          "lat_ok_p50_ms": 38910.0,
          "lat_ok_p90_ms": 38910.0,
          "lat_all_p50_ms": 38874.0,
          "bw_mbs": 0.162
        },
        {
          "t": "40s-45s",
          "ok": 0,
          "fail": 10,
          "total": 10,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 40215.7,
          "bw_mbs": 0.0
        }
      ],
      "saturation": {
        "avg_http_time_ms": 17568.1,
        "avg_elapsed_ms": 17568.1,
        "cv_latency": 0.233,
        "peak_active": 1200,
        "peak_active_pct": 100.0,
        "avg_active_connections": 492.4,
        "bottleneck_diagnosis": "proxy sob pressão — latência elevada mas ainda funcional"
      },
      "cumulative_error_rate": [
        {
          "at_request": 120,
          "pct_complete": 10.0,
          "error_rate_pct": 5.8
        },
        {
          "at_request": 240,
          "pct_complete": 20.0,
          "error_rate_pct": 11.7
        },
        {
          "at_request": 360,
          "pct_complete": 30.0,
          "error_rate_pct": 9.2
        },
        {
          "at_request": 480,
          "pct_complete": 40.0,
          "error_rate_pct": 7.9
        },
        {
          "at_request": 600,
          "pct_complete": 50.0,
          "error_rate_pct": 7.0
        },
        {
          "at_request": 720,
          "pct_complete": 60.0,
          "error_rate_pct": 6.2
        },
        {
          "at_request": 840,
          "pct_complete": 70.0,
          "error_rate_pct": 6.0
        },
        {
          "at_request": 960,
          "pct_complete": 80.0,
          "error_rate_pct": 6.1
        },
        {
          "at_request": 1080,
          "pct_complete": 90.0,
          "error_rate_pct": 5.6
        },
        {
          "at_request": 1200,
          "pct_complete": 100.0,
          "error_rate_pct": 5.9
        }
      ]
    }
  }
}
```