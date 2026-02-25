# Stress Test Unificado — 711Proxy + Decodo + Evomi

**Data:** 2026-02-23 15:28:00
**Timeout:** 40s
**Níveis testados:** 800, 1200, 1500, 2000
**Fonte de URLs:** `busca_fornecedor.website_discovery` (discovery_status = 'alto')
**711Proxy:** 900 proxies
**Decodo:** 9999 proxies
**Evomi:** 10000 proxies

---


## Comparativo Geral entre Providers

### Taxa de Sucesso (%) por Nível

| Nível |   711Proxy   |    Decodo    |    Evomi     |
|-------|--------------|--------------|--------------|
| 800   |    78.0%     |    87.1%     |    96.0%     |
| 1200  |    92.2%     |    88.9%     |    96.1%     |
| 1500  |    77.5%     |    86.7%     |    77.7%     |
| 2000  |    52.8%     |    63.6%     |    57.0%     |

### Latência p50 (ms) por Nível

| Nível |   711Proxy   |    Decodo    |    Evomi     |
|-------|--------------|--------------|--------------|
| 800   |  14601.9ms   |   7240.1ms   |   9245.3ms   |
| 1200  |   8011.6ms   |   8296.2ms   |   9608.6ms   |
| 1500  |   9727.8ms   |   9650.4ms   |  13555.4ms   |
| 2000  |  10825.3ms   |  13648.2ms   |  15429.2ms   |

### Latência p90 (ms) por Nível

| Nível |   711Proxy   |    Decodo    |    Evomi     |
|-------|--------------|--------------|--------------|
| 800   |  20299.4ms   |  10588.3ms   |  12336.1ms   |
| 1200  |  22756.9ms   |  22560.7ms   |  23099.3ms   |
| 1500  |  24176.3ms   |  31001.3ms   |  28438.0ms   |
| 2000  |  25673.7ms   |  31022.6ms   |  29283.5ms   |

### Throughput (req/min) por Nível

| Nível |   711Proxy   |    Decodo    |    Evomi     |
|-------|--------------|--------------|--------------|
| 800   |    1186.1    |    2079.2    |    1187.9    |
| 1200  |    1791.6    |    1783.0    |    1391.5    |
| 1500  |    2230.8    |    1439.2    |    1867.5    |
| 2000  |    2951.8    |    2929.4    |    2941.5    |

### Coeficiente de Variação de Latência por Nível
(>1.0 = proxy instável/sobrecarregado | <0.5 = estável)

| Nível |   711Proxy   |    Decodo    |    Evomi     |
|-------|--------------|--------------|--------------|
| 800   |    0.409     |    0.402     |     0.45     |
| 1200  |     0.77     |    0.672     |    0.651     |
| 1500  |    0.761     |     0.74     |    0.602     |
| 2000  |    0.599     |    0.581     |    0.477     |

### Diagnóstico de Gargalo por Nível

| Nível | Provider | Diagnóstico |
|-------|----------|-------------|
| 800 | 711Proxy | proxy sob pressão — latência elevada mas ainda funcional |
| 800 | Decodo | proxy saudável — absorveu a carga sem degradação severa |
| 800 | Evomi | proxy saudável — absorveu a carga sem degradação severa |
| 1200 | 711Proxy | proxy saudável — absorveu a carga sem degradação severa |
| 1200 | Decodo | proxy saudável — absorveu a carga sem degradação severa |
| 1200 | Evomi | proxy saudável — absorveu a carga sem degradação severa |
| 1500 | 711Proxy | proxy sob pressão — latência elevada mas ainda funcional |
| 1500 | Decodo | proxy saudável — absorveu a carga sem degradação severa |
| 1500 | Evomi | proxy sob pressão — latência elevada mas ainda funcional |
| 2000 | 711Proxy | proxy sob pressão — latência elevada mas ainda funcional |
| 2000 | Decodo | proxy sob pressão — latência elevada mas ainda funcional |
| 2000 | Evomi | proxy lento — latência média alta; bandwidth ou capacidade do proxy esgotada |

### Ranking de Melhor Provider por Nível (por success rate)

| Nível | 1º | 2º | 3º |
|-------|-----|-----|-----|
| 800 | Evomi (96.0%) | Decodo (87.1%) | 711Proxy (78.0%) |
| 1200 | Evomi (96.1%) | 711Proxy (92.2%) | Decodo (88.9%) |
| 1500 | Decodo (86.7%) | Evomi (77.7%) | 711Proxy (77.5%) |
| 2000 | Decodo (63.6%) | Evomi (57.0%) | 711Proxy (52.8%) |


## Análise de Capacidade por Provider

### 711Proxy

- **Carga ideal** (success ≥90%, p90 ≤15s): **N/A** links
- **Carga máxima** (success ≥70%): **1500** links
- **Ponto de degradação** (success <80%): **800**

| Nível | Success% | p50ms | p90ms | p99ms | Erros | BW Mbps | Avaliação |
|-------|----------|-------|-------|-------|-------|---------|-----------|
| 800 | 78.0% | 14601.9 | 20299.4 | 24046.8 | 176 | 34.59 | 🔶 Degradado |
| 1200 | 92.2% | 8011.6 | 22756.9 | 38971.9 | 93 | 59.43 | ✅ Ótimo |
| 1500 | 77.5% | 9727.8 | 24176.3 | 38943.2 | 338 | 59.53 | 🔶 Degradado |
| 2000 | 52.8% | 10825.3 | 25673.7 | 39703.9 | 945 | 50.52 | ❌ Crítico |

### Decodo

- **Carga ideal** (success ≥90%, p90 ≤15s): **N/A** links
- **Carga máxima** (success ≥70%): **1500** links
- **Ponto de degradação** (success <80%): **2000**

| Nível | Success% | p50ms | p90ms | p99ms | Erros | BW Mbps | Avaliação |
|-------|----------|-------|-------|-------|-------|---------|-----------|
| 800 | 87.1% | 7240.1 | 10588.3 | 14599.0 | 103 | 61.52 | ⚠️ Aceitável |
| 1200 | 88.9% | 8296.2 | 22560.7 | 25601.6 | 133 | 56.63 | ⚠️ Aceitável |
| 1500 | 86.7% | 9650.4 | 31001.3 | 39015.7 | 199 | 43.15 | ⚠️ Aceitável |
| 2000 | 63.6% | 13648.2 | 31022.6 | 39394.8 | 728 | 65.85 | ❌ Crítico |

### Evomi

- **Carga ideal** (success ≥90%, p90 ≤15s): **800** links
- **Carga máxima** (success ≥70%): **1500** links
- **Ponto de degradação** (success <80%): **1500**

| Nível | Success% | p50ms | p90ms | p99ms | Erros | BW Mbps | Avaliação |
|-------|----------|-------|-------|-------|-------|---------|-----------|
| 800 | 96.0% | 9245.3 | 12336.1 | 16915.3 | 32 | 38.83 | ✅ Ótimo |
| 1200 | 96.1% | 9608.6 | 23099.3 | 31217.1 | 47 | 46.73 | ✅ Ótimo |
| 1500 | 77.7% | 13555.4 | 28438.0 | 37559.3 | 335 | 50.55 | 🔶 Degradado |
| 2000 | 57.0% | 15429.2 | 29283.5 | 37435.3 | 859 | 59.61 | ❌ Crítico |


## Gráfico: Taxa de Sucesso (%) por Nível de Carga

Nível    Provider         %  Barra
-----------------------------------------------------------------
800      711Proxy      78.0%  ███████████████████████░░░░░░░
800      Decodo        87.1%  ██████████████████████████░░░░
800      Evomi         96.0%  █████████████████████████████░

1200     711Proxy      92.2%  ████████████████████████████░░
1200     Decodo        88.9%  ███████████████████████████░░░
1200     Evomi         96.1%  █████████████████████████████░

1500     711Proxy      77.5%  ███████████████████████░░░░░░░
1500     Decodo        86.7%  ██████████████████████████░░░░
1500     Evomi         77.7%  ███████████████████████░░░░░░░

2000     711Proxy      52.8%  ████████████████░░░░░░░░░░░░░░
2000     Decodo        63.6%  ███████████████████░░░░░░░░░░░
2000     Evomi         57.0%  █████████████████░░░░░░░░░░░░░


## Gráfico: Latência p50 (ms) por Nível de Carga

Nível    Provider       p50ms  Barra
-----------------------------------------------------------------
800      711Proxy     14601.9ms  ████████████████████████████░░
800      Decodo        7240.1ms  ██████████████░░░░░░░░░░░░░░░░
800      Evomi         9245.3ms  ██████████████████░░░░░░░░░░░░

1200     711Proxy      8011.6ms  ████████████████░░░░░░░░░░░░░░
1200     Decodo        8296.2ms  ████████████████░░░░░░░░░░░░░░
1200     Evomi         9608.6ms  ███████████████████░░░░░░░░░░░

1500     711Proxy      9727.8ms  ███████████████████░░░░░░░░░░░
1500     Decodo        9650.4ms  ███████████████████░░░░░░░░░░░
1500     Evomi        13555.4ms  ██████████████████████████░░░░

2000     711Proxy     10825.3ms  █████████████████████░░░░░░░░░
2000     Decodo       13648.2ms  ███████████████████████████░░░
2000     Evomi        15429.2ms  ██████████████████████████████


## Gráfico: Throughput (req/min) por Nível de Carga

Nível    Provider      req/min  Barra
-----------------------------------------------------------------
800      711Proxy         1186  ████████████░░░░░░░░░░░░░░░░░░
800      Decodo           2079  █████████████████████░░░░░░░░░
800      Evomi            1188  ████████████░░░░░░░░░░░░░░░░░░

1200     711Proxy         1792  ██████████████████░░░░░░░░░░░░
1200     Decodo           1783  ██████████████████░░░░░░░░░░░░
1200     Evomi            1392  ██████████████░░░░░░░░░░░░░░░░

1500     711Proxy         2231  ███████████████████████░░░░░░░
1500     Decodo           1439  ███████████████░░░░░░░░░░░░░░░
1500     Evomi            1868  ███████████████████░░░░░░░░░░░

2000     711Proxy         2952  ██████████████████████████████
2000     Decodo           2929  ██████████████████████████████
2000     Evomi            2942  ██████████████████████████████


## Gráfico: Distribuição de Erros por Terço do Teste

(Mostra se os erros aumentam ao longo do tempo — indica degradação)

### Nível 800
Provider      1º terço  2º terço  3º terço  Tendência
-------------------------------------------------------
711Proxy            58        56        62  → estável
Decodo              35        31        37  → estável
Evomi               10        10        12  → estável

### Nível 1200
Provider      1º terço  2º terço  3º terço  Tendência
-------------------------------------------------------
711Proxy            33        29        31  → estável
Decodo              50        39        44  → estável
Evomi               20        11        16  → estável

### Nível 1500
Provider      1º terço  2º terço  3º terço  Tendência
-------------------------------------------------------
711Proxy            56        49       233  ↑ piora
Decodo              60        64        75  → estável
Evomi               14        18       303  ↑ piora

### Nível 2000
Provider      1º terço  2º terço  3º terço  Tendência
-------------------------------------------------------
711Proxy            97       191       657  ↑ piora
Decodo              64       162       502  ↑ piora
Evomi               39       265       555  ↑ piora


## Gráfico: Coeficiente de Variação de Latência (CV)

(CV = stdev/média | >1.0 = proxy muito instável | <0.5 = estável)

Nível    Provider         CV  Barra
-----------------------------------------------------------------
800      711Proxy      0.409  ██████░░░░░░░░░░░░░░░░░░░░░░░░
800      Decodo        0.402  ██████░░░░░░░░░░░░░░░░░░░░░░░░
800      Evomi         0.450  ███████░░░░░░░░░░░░░░░░░░░░░░░

1200     711Proxy      0.770  ████████████░░░░░░░░░░░░░░░░░░
1200     Decodo        0.672  ██████████░░░░░░░░░░░░░░░░░░░░
1200     Evomi         0.651  ██████████░░░░░░░░░░░░░░░░░░░░

1500     711Proxy      0.761  ███████████░░░░░░░░░░░░░░░░░░░
1500     Decodo        0.740  ███████████░░░░░░░░░░░░░░░░░░░
1500     Evomi         0.602  █████████░░░░░░░░░░░░░░░░░░░░░

2000     711Proxy      0.599  █████████░░░░░░░░░░░░░░░░░░░░░
2000     Decodo        0.581  █████████░░░░░░░░░░░░░░░░░░░░░
2000     Evomi         0.477  ███████░░░░░░░░░░░░░░░░░░░░░░░


## Gráfico: Bandwidth p50 (MB/s) por Nível

(Calculado a partir de amostras de 0.5s durante o teste)

Nível    Provider      p50 MB/s  Barra
-----------------------------------------------------------------
800      711Proxy         0.200  █░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
800      Decodo           1.300  ████████░░░░░░░░░░░░░░░░░░░░░░
800      Evomi            0.000  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░

1200     711Proxy         1.300  ████████░░░░░░░░░░░░░░░░░░░░░░
1200     Decodo           0.700  ████░░░░░░░░░░░░░░░░░░░░░░░░░░
1200     Evomi            0.300  ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░

1500     711Proxy         1.600  ██████████░░░░░░░░░░░░░░░░░░░░
1500     Decodo           0.700  ████░░░░░░░░░░░░░░░░░░░░░░░░░░
1500     Evomi            1.300  ████████░░░░░░░░░░░░░░░░░░░░░░

2000     711Proxy         1.800  ███████████░░░░░░░░░░░░░░░░░░░
2000     Decodo           4.800  ██████████████████████████████
2000     Evomi            3.300  █████████████████████░░░░░░░░░


---

## Detalhes por Nível de Carga

### Nível 800 links

#### 711Proxy — 800 links

- **Success:** 624 / 800 (78.0%)
- **Tempo total:** 40.5s
- **Throughput:** 1186.1 req/min
- **Bandwidth:** 34.59 Mbps | **Dados:** 174.96 MB
- **Peak connections:** 799
- **Ponto de degradação:** 10-15s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 12801.9 | 14601.9 | 18540.4 | 20299.4 | 20932.1 | 24046.8 | 36288.2 | 14511.2 | 5086.1 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 14603.0 | 34070.5 | 40110.2 | 40161.5 | 17347.3 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| connection | 155 |
| timeout | 11 |
| http_404 | 4 |
| http_403 | 3 |
| reset | 2 |
| http_526 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy sob pressão — latência elevada mas ainda funcional**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 15135.1ms | Tempo médio efetivo de rede |
| CV Latência | 0.409 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 800 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 249.7 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 14001.4 | 14601.9 | 18653.5 | 20537.2 | 21521.1 | 40056.8 | 40161.5 | 15135.1 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 0.2 | 4.5 | 17.5 | 30.8 | 48.7 | 4.9 | 9.9 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 0 | 3 | 3 | 100.0% |
| 3-6s | 79 | 13 | 92 | 14.1% |
| 6-10s | 28 | 1 | 29 | 3.4% |
| 10-15s | 235 | 82 | 317 | 25.9% |
| 15-20s | 201 | 44 | 245 | 18.0% |
| 20-30s | 80 | 10 | 90 | 11.1% |
| 30-40s | 1 | 12 | 13 | 92.3% |
| 40s+ | 0 | 11 | 11 | 100.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 43 | 13 | 76.8% | 4401.3 | 4433.3 | 0.23 |
| 5s-10s | 58 | 4 | 93.5% | 5822.6 | 7830.1 | 0.842 |
| 10s-15s | 222 | 77 | 74.2% | 14075.1 | 14587.8 | 5.065 |
| 15s-20s | 207 | 47 | 81.5% | 17435.6 | 19218.8 | 13.014 |
| 20s-25s | 88 | 12 | 88.0% | 20478.6 | 21490.0 | 14.71 |
| 25s-30s | 5 | 0 | 100.0% | 25307.8 | 27495.5 | 1.111 |
| 30s-35s | 0 | 6 | 0.0% | 0 | 0 | 0.0 |
| 35s-40s | 1 | 6 | 14.3% | 36288.2 | 36288.2 | 0.02 |
| 40s-45s | 0 | 11 | 0.0% | 0 | 0 | 0.0 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 80 | 10% | 31.2% |
| 160 | 20% | 24.4% |
| 240 | 30% | 21.2% |
| 320 | 40% | 21.2% |
| 400 | 50% | 19.8% |
| 480 | 60% | 20.8% |
| 560 | 70% | 21.2% |
| 640 | 80% | 22.0% |
| 720 | 90% | 22.2% |
| 800 | 100% | 22.0% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 58 | 56 | 62 | → estável |

#### Decodo — 800 links

- **Success:** 697 / 800 (87.1%)
- **Tempo total:** 23.1s
- **Throughput:** 2079.2 req/min
- **Bandwidth:** 61.52 Mbps | **Dados:** 177.54 MB
- **Peak connections:** 799
- **Ponto de degradação:** 3-6s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 5397.0 | 7240.1 | 8934.0 | 10588.3 | 11491.8 | 14599.0 | 23033.7 | 7195.6 | 2779.9 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 4948.0 | 6888.8 | 13917.8 | 15425.1 | 5243.6 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| connection | 78 |
| http_522 | 10 |
| other | 3 |
| http_404 | 3 |
| http_403 | 3 |
| http_500 | 2 |
| http_429 | 1 |
| http_530 | 1 |
| http_526 | 1 |
| http_503 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy saudável — absorveu a carga sem degradação severa**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 6944.3ms | Tempo médio efetivo de rede |
| CV Latência | 0.402 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 800 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 230 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 4948.0 | 6885.3 | 8741.2 | 10202.2 | 11478.5 | 14599.0 | 23033.7 | 6944.3 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 1.3 | 13.1 | 25.0 | 29.5 | 45.8 | 7.5 | 11.5 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 47 | 11 | 58 | 19.0% |
| 3-6s | 176 | 67 | 243 | 27.6% |
| 6-10s | 389 | 22 | 411 | 5.4% |
| 10-15s | 81 | 2 | 83 | 2.4% |
| 15-20s | 3 | 1 | 4 | 25.0% |
| 20-30s | 1 | 0 | 1 | 0.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 144 | 48 | 75.0% | 3336.2 | 4671.7 | 1.973 |
| 5s-10s | 462 | 52 | 89.9% | 7611.4 | 9364.5 | 21.034 |
| 10s-15s | 86 | 2 | 97.7% | 11252.0 | 12918.4 | 12.212 |
| 15s-20s | 4 | 1 | 80.0% | 18431.0 | 19762.7 | 0.261 |
| 20s-25s | 1 | 0 | 100.0% | 23033.7 | 23033.7 | 0.028 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 80 | 10% | 11.2% |
| 160 | 20% | 13.8% |
| 240 | 30% | 14.6% |
| 320 | 40% | 13.4% |
| 400 | 50% | 12.5% |
| 480 | 60% | 12.3% |
| 560 | 70% | 12.7% |
| 640 | 80% | 13.0% |
| 720 | 90% | 12.8% |
| 800 | 100% | 12.9% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 35 | 31 | 37 | → estável |

#### Evomi — 800 links

- **Success:** 768 / 800 (96.0%)
- **Tempo total:** 40.4s
- **Throughput:** 1187.9 req/min
- **Bandwidth:** 38.83 Mbps | **Dados:** 196.13 MB
- **Peak connections:** 799
- **Ponto de degradação:** não detectado

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 7784.3 | 9245.3 | 11167.2 | 12336.1 | 12918.8 | 16915.3 | 28509.9 | 9164.0 | 2991.8 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 7549.0 | 40123.0 | 40145.3 | 40145.3 | 13824.1 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| connection | 12 |
| http_404 | 6 |
| timeout | 6 |
| http_500 | 3 |
| other | 2 |
| http_403 | 1 |
| http_503 | 1 |
| http_502 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy saudável — absorveu a carga sem degradação severa**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 9350.4ms | Tempo médio efetivo de rede |
| CV Latência | 0.45 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 800 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 154.2 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 7653.4 | 9220.0 | 11170.6 | 12414.1 | 13149.9 | 28509.9 | 40145.3 | 9350.4 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 0.0 | 2.2 | 21.5 | 36.4 | 49.2 | 5.1 | 11.3 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 0 | 5 | 5 | 100.0% |
| 3-6s | 117 | 10 | 127 | 7.9% |
| 6-10s | 341 | 5 | 346 | 1.4% |
| 10-15s | 299 | 1 | 300 | 0.3% |
| 15-20s | 5 | 2 | 7 | 28.6% |
| 20-30s | 6 | 3 | 9 | 33.3% |
| 40s+ | 0 | 6 | 6 | 100.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 82 | 14 | 85.4% | 3754.7 | 4517.8 | 0.715 |
| 5s-10s | 362 | 6 | 98.4% | 8195.1 | 9448.7 | 12.003 |
| 10s-15s | 313 | 1 | 99.7% | 11307.2 | 12855.9 | 25.097 |
| 15s-20s | 4 | 2 | 66.7% | 16595.0 | 16915.3 | 0.782 |
| 20s-25s | 6 | 1 | 85.7% | 22963.0 | 24590.5 | 0.624 |
| 25s-30s | 1 | 2 | 33.3% | 28509.9 | 28509.9 | 0.005 |
| 40s-45s | 0 | 6 | 0.0% | 0 | 0 | 0.0 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 80 | 10% | 3.8% |
| 160 | 20% | 3.8% |
| 240 | 30% | 3.8% |
| 320 | 40% | 4.1% |
| 400 | 50% | 4.2% |
| 480 | 60% | 4.0% |
| 560 | 70% | 4.3% |
| 640 | 80% | 3.8% |
| 720 | 90% | 3.8% |
| 800 | 100% | 4.0% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 10 | 10 | 12 | → estável |

---

### Nível 1200 links

#### 711Proxy — 1200 links

- **Success:** 1107 / 1200 (92.2%)
- **Tempo total:** 40.2s
- **Throughput:** 1791.6 req/min
- **Bandwidth:** 59.43 Mbps | **Dados:** 298.54 MB
- **Peak connections:** 1199
- **Ponto de degradação:** 15-20s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 6310.2 | 8011.6 | 12738.0 | 22756.9 | 24654.2 | 38971.9 | 39695.7 | 11092.1 | 8271.2 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 8986.3 | 40042.0 | 40064.3 | 40064.3 | 15592.6 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| connection | 65 |
| timeout | 10 |
| http_404 | 9 |
| http_403 | 6 |
| http_500 | 2 |
| http_530 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy saudável — absorveu a carga sem degradação severa**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 11440.9ms | Tempo médio efetivo de rede |
| CV Latência | 0.77 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 1200 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 336.4 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 6225.5 | 8039.9 | 13648.7 | 22896.0 | 31348.6 | 39599.8 | 40064.3 | 11440.9 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 1.3 | 8.4 | 30.9 | 39.2 | 46.8 | 7.5 | 12.5 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 87 | 7 | 94 | 7.4% |
| 3-6s | 154 | 18 | 172 | 10.5% |
| 6-10s | 513 | 25 | 538 | 4.6% |
| 10-15s | 101 | 6 | 107 | 5.6% |
| 15-20s | 11 | 6 | 17 | 35.3% |
| 20-30s | 200 | 10 | 210 | 4.8% |
| 30-40s | 41 | 11 | 52 | 21.2% |
| 40s+ | 0 | 10 | 10 | 100.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 172 | 19 | 90.1% | 2999.6 | 4737.2 | 1.699 |
| 5s-10s | 561 | 30 | 94.9% | 7367.4 | 8835.5 | 28.276 |
| 10s-15s | 121 | 7 | 94.5% | 10528.2 | 13498.7 | 17.95 |
| 15s-20s | 12 | 6 | 66.7% | 16171.4 | 17807.9 | 1.203 |
| 20s-25s | 188 | 10 | 94.9% | 22098.7 | 23520.4 | 8.165 |
| 25s-30s | 12 | 0 | 100.0% | 25895.5 | 26909.0 | 0.325 |
| 30s-35s | 1 | 7 | 12.5% | 30228.6 | 30228.6 | 0.026 |
| 35s-40s | 40 | 4 | 90.9% | 38181.7 | 39372.0 | 2.064 |
| 40s-45s | 0 | 10 | 0.0% | 0 | 0 | 0.0 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 120 | 10% | 10.8% |
| 240 | 20% | 9.6% |
| 360 | 30% | 8.6% |
| 480 | 40% | 9.0% |
| 600 | 50% | 8.2% |
| 720 | 60% | 7.5% |
| 840 | 70% | 7.7% |
| 960 | 80% | 7.7% |
| 1080 | 90% | 7.2% |
| 1200 | 100% | 7.8% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 33 | 29 | 31 | → estável |

#### Decodo — 1200 links

- **Success:** 1067 / 1200 (88.9%)
- **Tempo total:** 40.4s
- **Throughput:** 1783.0 req/min
- **Bandwidth:** 56.63 Mbps | **Dados:** 285.86 MB
- **Peak connections:** 1199
- **Ponto de degradação:** 0-3s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 6537.9 | 8296.2 | 12268.8 | 22560.7 | 23283.4 | 25601.6 | 38336.0 | 10770.1 | 6838.8 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 5742.2 | 23151.2 | 40211.9 | 40212.1 | 9866.6 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| connection | 99 |
| http_522 | 11 |
| timeout | 5 |
| http_500 | 4 |
| other | 3 |
| http_404 | 3 |
| http_502 | 2 |
| http_503 | 2 |
| http_526 | 1 |
| http_403 | 1 |
| http_307 | 1 |
| http_530 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy saudável — absorveu a carga sem degradação severa**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 10670.0ms | Tempo médio efetivo de rede |
| CV Latência | 0.672 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 1200 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 306.4 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 6035.0 | 8040.5 | 12689.7 | 22658.9 | 23412.1 | 26082.1 | 40212.1 | 10670.0 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 0.7 | 8.7 | 24.9 | 36.9 | 57.2 | 7.1 | 12.6 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 61 | 22 | 83 | 26.5% |
| 3-6s | 153 | 59 | 212 | 27.8% |
| 6-10s | 472 | 14 | 486 | 2.9% |
| 10-15s | 141 | 8 | 149 | 5.4% |
| 15-20s | 13 | 3 | 16 | 18.8% |
| 20-30s | 224 | 22 | 246 | 8.9% |
| 30-40s | 3 | 0 | 3 | 0.0% |
| 40s+ | 0 | 5 | 5 | 100.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 154 | 30 | 83.7% | 3253.5 | 4201.8 | 2.821 |
| 5s-10s | 525 | 65 | 89.0% | 7316.1 | 9378.8 | 23.5 |
| 10s-15s | 148 | 8 | 94.9% | 10847.4 | 13599.1 | 17.92 |
| 15s-20s | 13 | 2 | 86.7% | 15753.7 | 17725.1 | 1.555 |
| 20s-25s | 212 | 21 | 91.0% | 22367.0 | 23792.1 | 10.734 |
| 25s-30s | 12 | 2 | 85.7% | 25677.3 | 26796.6 | 0.457 |
| 30s-35s | 1 | 0 | 100.0% | 33884.6 | 33884.6 | 0.092 |
| 35s-40s | 2 | 0 | 100.0% | 38336.0 | 38336.0 | 0.094 |
| 40s-45s | 0 | 5 | 0.0% | 0 | 0 | 0.0 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 120 | 10% | 15.0% |
| 240 | 20% | 13.3% |
| 360 | 30% | 11.4% |
| 480 | 40% | 12.3% |
| 600 | 50% | 12.7% |
| 720 | 60% | 11.7% |
| 840 | 70% | 11.1% |
| 960 | 80% | 11.2% |
| 1080 | 90% | 10.9% |
| 1200 | 100% | 11.1% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 50 | 39 | 44 | → estável |

#### Evomi — 1200 links

- **Success:** 1153 / 1200 (96.1%)
- **Tempo total:** 51.7s
- **Throughput:** 1391.5 req/min
- **Bandwidth:** 46.73 Mbps | **Dados:** 302.28 MB
- **Peak connections:** 1199
- **Ponto de degradação:** 0-3s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 7290.7 | 9608.6 | 13629.1 | 23099.3 | 29020.3 | 31217.1 | 34636.1 | 12183.2 | 7535.8 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 8007.7 | 40212.6 | 51640.3 | 51640.3 | 16446.7 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| connection | 16 |
| timeout | 8 |
| http_500 | 7 |
| http_404 | 7 |
| http_403 | 3 |
| http_307 | 1 |
| other | 1 |
| http_526 | 1 |
| http_502 | 1 |
| http_503 | 1 |
| http_530 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy saudável — absorveu a carga sem degradação severa**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 12350.2ms | Tempo médio efetivo de rede |
| CV Latência | 0.651 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 1200 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 267.8 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 7178.3 | 9582.2 | 14131.2 | 23980.7 | 29210.7 | 33235.2 | 51640.3 | 12350.2 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 0.3 | 6.8 | 22.7 | 29.1 | 47.9 | 6.0 | 10.8 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 35 | 13 | 48 | 27.1% |
| 3-6s | 128 | 8 | 136 | 5.9% |
| 6-10s | 448 | 6 | 454 | 1.3% |
| 10-15s | 272 | 0 | 272 | 0.0% |
| 15-20s | 11 | 0 | 11 | 0.0% |
| 20-30s | 232 | 11 | 243 | 4.5% |
| 30-40s | 27 | 1 | 28 | 3.6% |
| 40s+ | 0 | 8 | 8 | 100.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 134 | 20 | 87.0% | 3532.1 | 4294.5 | 1.495 |
| 5s-10s | 474 | 7 | 98.5% | 7747.6 | 9395.9 | 16.45 |
| 10s-15s | 275 | 0 | 100.0% | 11644.2 | 13508.2 | 27.08 |
| 15s-20s | 11 | 0 | 100.0% | 16290.8 | 18749.1 | 0.935 |
| 20s-25s | 163 | 3 | 98.2% | 22182.3 | 23193.7 | 8.254 |
| 25s-30s | 66 | 8 | 89.2% | 28976.8 | 29610.3 | 2.853 |
| 30s-35s | 30 | 0 | 100.0% | 31073.7 | 33235.2 | 3.389 |
| 35s-40s | 0 | 1 | 0.0% | 0 | 0 | 0.0 |
| 40s-45s | 0 | 7 | 0.0% | 0 | 0 | 0.0 |
| 50s-55s | 0 | 1 | 0.0% | 0 | 0 | 0.0 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 120 | 10% | 7.5% |
| 240 | 20% | 5.8% |
| 360 | 30% | 5.0% |
| 480 | 40% | 4.2% |
| 600 | 50% | 3.7% |
| 720 | 60% | 3.9% |
| 840 | 70% | 4.0% |
| 960 | 80% | 4.1% |
| 1080 | 90% | 3.8% |
| 1200 | 100% | 3.9% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 20 | 11 | 16 | → estável |

---

### Nível 1500 links

#### 711Proxy — 1500 links

- **Success:** 1162 / 1500 (77.5%)
- **Tempo total:** 40.3s
- **Throughput:** 2230.8 req/min
- **Bandwidth:** 59.53 Mbps | **Dados:** 300.19 MB
- **Peak connections:** 1499
- **Ponto de degradação:** 40s+

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 7241.8 | 9727.8 | 21171.8 | 24176.3 | 38203.7 | 38943.2 | 39910.0 | 13449.6 | 9750.6 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 40102.4 | 40156.2 | 40163.0 | 40173.3 | 30642.5 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| timeout | 231 |
| connection | 88 |
| http_403 | 8 |
| http_404 | 5 |
| http_503 | 2 |
| http_307 | 1 |
| http_500 | 1 |
| http_521 | 1 |
| http_530 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy sob pressão — latência elevada mas ainda funcional**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 17323.8ms | Tempo médio efetivo de rede |
| CV Latência | 0.761 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 1500 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 641.2 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 7876.6 | 10686.0 | 23397.2 | 40110.9 | 40140.7 | 40161.3 | 40173.3 | 17323.8 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 1.6 | 9.7 | 27.0 | 42.3 | 50.6 | 7.6 | 12.3 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 74 | 18 | 92 | 19.6% |
| 3-6s | 119 | 13 | 132 | 9.8% |
| 6-10s | 415 | 41 | 456 | 9.0% |
| 10-15s | 209 | 19 | 228 | 8.3% |
| 15-20s | 21 | 1 | 22 | 4.5% |
| 20-30s | 225 | 8 | 233 | 3.4% |
| 30-40s | 99 | 7 | 106 | 6.6% |
| 40s+ | 0 | 231 | 231 | 100.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 151 | 25 | 85.8% | 3085.3 | 3681.8 | 1.802 |
| 5s-10s | 450 | 47 | 90.5% | 8173.1 | 9554.9 | 16.958 |
| 10s-15s | 215 | 18 | 92.3% | 11071.1 | 13317.1 | 24.11 |
| 15s-20s | 22 | 2 | 91.7% | 15521.8 | 18075.2 | 2.117 |
| 20s-25s | 213 | 8 | 96.4% | 21882.4 | 23468.6 | 9.826 |
| 25s-30s | 12 | 0 | 100.0% | 25578.1 | 27447.8 | 0.244 |
| 30s-35s | 1 | 5 | 16.7% | 33942.6 | 33942.6 | 0.028 |
| 35s-40s | 97 | 2 | 98.0% | 38205.6 | 39016.5 | 4.753 |
| 40s-45s | 1 | 231 | 0.4% | 39910.0 | 39910.0 | 0.2 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 150 | 10% | 12.0% |
| 300 | 20% | 12.0% |
| 450 | 30% | 12.2% |
| 600 | 40% | 11.0% |
| 750 | 50% | 10.9% |
| 900 | 60% | 10.8% |
| 1050 | 70% | 10.2% |
| 1200 | 80% | 17.0% |
| 1350 | 90% | 24.2% |
| 1500 | 100% | 22.5% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 56 | 49 | 233 | ↑ piora ao longo do tempo |

#### Decodo — 1500 links

- **Success:** 1301 / 1500 (86.7%)
- **Tempo total:** 62.5s
- **Throughput:** 1439.2 req/min
- **Bandwidth:** 43.15 Mbps | **Dados:** 337.26 MB
- **Peak connections:** 1499
- **Ponto de degradação:** 0-3s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 6567.0 | 9650.4 | 22575.5 | 31001.3 | 35966.9 | 39015.7 | 40138.2 | 14426.8 | 10326.7 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 6811.4 | 39905.9 | 40280.1 | 62406.4 | 15308.5 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| connection | 142 |
| http_522 | 18 |
| timeout | 17 |
| http_404 | 7 |
| ssl | 3 |
| other | 3 |
| http_502 | 3 |
| http_403 | 2 |
| http_526 | 1 |
| http_503 | 1 |
| http_530 | 1 |
| http_307 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy saudável — absorveu a carga sem degradação severa**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 14543.8ms | Tempo médio efetivo de rede |
| CV Latência | 0.74 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 1500 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 338.1 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 6280.5 | 9565.0 | 22669.5 | 32568.2 | 37061.1 | 40244.4 | 62406.4 | 14543.8 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 0.7 | 5.9 | 18.8 | 26.3 | 53.1 | 5.4 | 9.4 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 40 | 21 | 61 | 34.4% |
| 3-6s | 215 | 63 | 278 | 22.7% |
| 6-10s | 421 | 28 | 449 | 6.2% |
| 10-15s | 159 | 6 | 165 | 3.6% |
| 15-20s | 19 | 3 | 22 | 13.6% |
| 20-30s | 300 | 44 | 344 | 12.8% |
| 30-40s | 145 | 15 | 160 | 9.4% |
| 40s+ | 2 | 19 | 21 | 90.5% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 188 | 28 | 87.0% | 3621.6 | 4322.0 | 3.14 |
| 5s-10s | 483 | 84 | 85.2% | 7554.4 | 9320.7 | 20.032 |
| 10s-15s | 164 | 6 | 96.5% | 11320.0 | 13992.5 | 20.315 |
| 15s-20s | 19 | 2 | 90.5% | 16113.9 | 18610.8 | 1.199 |
| 20s-25s | 252 | 37 | 87.2% | 22605.8 | 24129.5 | 12.509 |
| 25s-30s | 47 | 8 | 85.5% | 28103.7 | 29713.3 | 1.547 |
| 30s-35s | 73 | 5 | 93.6% | 32853.5 | 34365.5 | 4.379 |
| 35s-40s | 73 | 9 | 89.0% | 37722.8 | 39203.0 | 4.081 |
| 40s-45s | 2 | 19 | 9.5% | 40138.2 | 40138.2 | 0.251 |
| 60s-65s | 0 | 1 | 0.0% | 0 | 0 | 0.0 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 150 | 10% | 15.3% |
| 300 | 20% | 12.0% |
| 450 | 30% | 11.6% |
| 600 | 40% | 11.7% |
| 750 | 50% | 11.6% |
| 900 | 60% | 12.3% |
| 1050 | 70% | 12.9% |
| 1200 | 80% | 12.9% |
| 1350 | 90% | 12.8% |
| 1500 | 100% | 13.3% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 60 | 64 | 75 | → estável |

#### Evomi — 1500 links

- **Success:** 1165 / 1500 (77.7%)
- **Tempo total:** 48.2s
- **Throughput:** 1867.5 req/min
- **Bandwidth:** 50.55 Mbps | **Dados:** 304.54 MB
- **Peak connections:** 1499
- **Ponto de degradação:** 0-3s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 10447.3 | 13555.4 | 18449.6 | 28438.0 | 30561.5 | 37559.3 | 39121.1 | 15751.3 | 7871.5 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 41747.3 | 42051.3 | 42066.5 | 48168.1 | 39036.1 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| timeout | 304 |
| connection | 14 |
| http_404 | 7 |
| http_500 | 3 |
| http_403 | 3 |
| http_502 | 1 |
| other | 1 |
| http_530 | 1 |
| http_307 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy sob pressão — latência elevada mas ainda funcional**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 20951.5ms | Tempo médio efetivo de rede |
| CV Latência | 0.602 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 1500 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 652.7 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 10981.8 | 16041.7 | 30074.6 | 42000.5 | 42026.0 | 42062.6 | 48168.1 | 20951.5 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.0 | 1.3 | 8.3 | 20.5 | 30.2 | 53.3 | 6.5 | 10.6 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 8 | 4 | 12 | 33.3% |
| 3-6s | 43 | 7 | 50 | 14.0% |
| 6-10s | 211 | 5 | 216 | 2.3% |
| 10-15s | 444 | 3 | 447 | 0.7% |
| 15-20s | 190 | 2 | 192 | 1.0% |
| 20-30s | 197 | 8 | 205 | 3.9% |
| 30-40s | 72 | 2 | 74 | 2.7% |
| 40s+ | 0 | 304 | 304 | 100.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 40 | 10 | 80.0% | 3798.9 | 4570.9 | 0.159 |
| 5s-10s | 219 | 6 | 97.3% | 8278.0 | 9629.1 | 4.813 |
| 10s-15s | 437 | 2 | 99.5% | 12404.9 | 14383.4 | 17.534 |
| 15s-20s | 200 | 2 | 99.0% | 17046.2 | 18603.5 | 25.112 |
| 20s-25s | 63 | 2 | 96.9% | 21791.2 | 23396.1 | 3.807 |
| 25s-30s | 129 | 7 | 94.9% | 27963.1 | 29628.9 | 6.197 |
| 30s-35s | 49 | 0 | 100.0% | 30701.0 | 34000.7 | 2.368 |
| 35s-40s | 28 | 1 | 96.6% | 37345.3 | 38031.9 | 0.918 |
| 40s-45s | 0 | 304 | 0.0% | 0 | 0 | 0.0 |
| 45s-50s | 0 | 1 | 0.0% | 0 | 0 | 0.0 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 150 | 10% | 4.0% |
| 300 | 20% | 2.7% |
| 450 | 30% | 2.9% |
| 600 | 40% | 3.3% |
| 750 | 50% | 3.2% |
| 900 | 60% | 3.1% |
| 1050 | 70% | 3.1% |
| 1200 | 80% | 5.2% |
| 1350 | 90% | 15.6% |
| 1500 | 100% | 22.3% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 14 | 18 | 303 | ↑ piora ao longo do tempo |

---

### Nível 2000 links

#### 711Proxy — 2000 links

- **Success:** 1055 / 2000 (52.8%)
- **Tempo total:** 40.7s
- **Throughput:** 2951.8 req/min
- **Bandwidth:** 50.52 Mbps | **Dados:** 256.71 MB
- **Peak connections:** 1999
- **Ponto de degradação:** 0-3s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 7954.3 | 10825.3 | 21454.4 | 25673.7 | 38177.1 | 39703.9 | 40084.4 | 14328.0 | 9531.9 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 40303.9 | 40437.7 | 40465.7 | 40468.6 | 36199.0 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| timeout | 805 |
| connection | 123 |
| http_403 | 7 |
| http_404 | 5 |
| http_500 | 2 |
| http_530 | 1 |
| http_503 | 1 |
| http_526 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy sob pressão — latência elevada mas ainda funcional**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 24662.0ms | Tempo médio efetivo de rede |
| CV Latência | 0.599 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 2000 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 1212.1 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 10185.2 | 23798.2 | 40294.3 | 40400.5 | 40436.0 | 40462.4 | 40468.6 | 24662.0 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.1 | 1.8 | 9.4 | 19.7 | 29.9 | 51.4 | 6.5 | 10.4 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 20 | 9 | 29 | 31.0% |
| 3-6s | 106 | 16 | 122 | 13.1% |
| 6-10s | 287 | 29 | 316 | 9.2% |
| 10-15s | 336 | 64 | 400 | 16.0% |
| 15-20s | 19 | 1 | 20 | 5.0% |
| 20-30s | 199 | 8 | 207 | 3.9% |
| 30-40s | 86 | 13 | 99 | 13.1% |
| 40s+ | 2 | 805 | 807 | 99.8% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 100 | 18 | 84.7% | 3763.7 | 4429.5 | 0.7 |
| 5s-10s | 309 | 35 | 89.8% | 7919.4 | 9415.7 | 7.528 |
| 10s-15s | 340 | 65 | 84.0% | 11264.2 | 13739.0 | 26.5 |
| 15s-20s | 19 | 1 | 95.0% | 16131.6 | 18307.4 | 2.738 |
| 20s-25s | 157 | 6 | 96.3% | 23363.5 | 24549.4 | 4.485 |
| 25s-30s | 42 | 2 | 95.5% | 25418.5 | 26929.1 | 5.022 |
| 30s-35s | 8 | 7 | 53.3% | 31735.7 | 33159.0 | 0.482 |
| 35s-40s | 76 | 6 | 92.7% | 39241.7 | 39652.8 | 3.807 |
| 40s-45s | 4 | 805 | 0.5% | 40061.9 | 40084.4 | 0.08 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 200 | 10% | 14.5% |
| 400 | 20% | 14.8% |
| 600 | 30% | 14.5% |
| 800 | 40% | 15.0% |
| 1000 | 50% | 14.6% |
| 1200 | 60% | 14.8% |
| 1400 | 70% | 25.4% |
| 1600 | 80% | 34.3% |
| 1800 | 90% | 41.5% |
| 2000 | 100% | 47.2% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 97 | 191 | 657 | ↑ piora ao longo do tempo |

#### Decodo — 2000 links

- **Success:** 1272 / 2000 (63.6%)
- **Tempo total:** 41.0s
- **Throughput:** 2929.4 req/min
- **Bandwidth:** 65.85 Mbps | **Dados:** 337.18 MB
- **Peak connections:** 1999
- **Ponto de degradação:** 0-3s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 9665.8 | 13648.2 | 23490.3 | 31022.6 | 35470.9 | 39394.8 | 40275.3 | 16436.2 | 9085.9 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 40427.0 | 40533.9 | 40557.2 | 40762.7 | 35302.2 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| timeout | 585 |
| connection | 114 |
| http_522 | 9 |
| http_404 | 6 |
| other | 4 |
| http_403 | 3 |
| ssl | 2 |
| http_502 | 2 |
| http_503 | 1 |
| http_307 | 1 |
| http_500 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy sob pressão — latência elevada mas ainda funcional**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 23303.4ms | Tempo médio efetivo de rede |
| CV Latência | 0.581 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 2000 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 1115.7 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 10789.2 | 22739.4 | 40370.1 | 40481.2 | 40524.2 | 40552.9 | 40762.7 | 23303.4 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 1.0 | 4.8 | 12.1 | 27.0 | 31.1 | 57.0 | 8.4 | 10.6 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 0-3s | 2 | 21 | 23 | 91.3% |
| 3-6s | 102 | 10 | 112 | 8.9% |
| 6-10s | 244 | 47 | 291 | 16.2% |
| 10-15s | 394 | 12 | 406 | 3.0% |
| 15-20s | 112 | 4 | 116 | 3.4% |
| 20-30s | 274 | 30 | 304 | 9.9% |
| 30-40s | 139 | 18 | 157 | 11.5% |
| 40s+ | 5 | 586 | 591 | 99.2% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 80 | 27 | 74.8% | 4282.2 | 4746.2 | 0.764 |
| 5s-10s | 261 | 51 | 83.7% | 8346.3 | 9638.0 | 6.687 |
| 10s-15s | 385 | 12 | 97.0% | 12477.7 | 14741.2 | 21.051 |
| 15s-20s | 128 | 4 | 97.0% | 16053.4 | 18077.2 | 14.886 |
| 20s-25s | 198 | 25 | 88.8% | 23488.5 | 24489.4 | 10.98 |
| 25s-30s | 76 | 5 | 93.8% | 25753.1 | 28113.1 | 4.106 |
| 30s-35s | 76 | 10 | 88.4% | 31811.3 | 34051.1 | 3.244 |
| 35s-40s | 61 | 8 | 88.4% | 37231.8 | 39312.5 | 5.506 |
| 40s-45s | 7 | 586 | 1.2% | 40200.9 | 40275.3 | 0.21 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 200 | 10% | 9.0% |
| 400 | 20% | 9.0% |
| 600 | 30% | 9.7% |
| 800 | 40% | 10.4% |
| 1000 | 50% | 10.5% |
| 1200 | 60% | 10.5% |
| 1400 | 70% | 20.6% |
| 1600 | 80% | 29.7% |
| 1800 | 90% | 31.6% |
| 2000 | 100% | 36.4% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 64 | 162 | 502 | ↑ piora ao longo do tempo |

#### Evomi — 2000 links

- **Success:** 1141 / 2000 (57.0%)
- **Tempo total:** 40.8s
- **Throughput:** 2941.5 req/min
- **Bandwidth:** 59.61 Mbps | **Dados:** 303.99 MB
- **Peak connections:** 1999
- **Ponto de degradação:** 3-6s

**Latência OK (ms):**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-----|-------|
| 12119.1 | 15429.2 | 21754.6 | 29283.5 | 31003.0 | 37435.3 | 39773.7 | 17405.1 | 7339.6 |

**Latência FAIL (ms):**

| p50 | p90 | p99 | max | avg |
|-----|-----|-----|-----|-----|
| 40409.6 | 40540.8 | 40569.7 | 40572.5 | 38785.8 |

**Breakdown de Erros:**

| Tipo | Quantidade |
|------|------------|
| timeout | 803 |
| connection | 37 |
| http_404 | 6 |
| http_500 | 5 |
| http_403 | 2 |
| http_504 | 1 |
| http_526 | 1 |
| ssl | 1 |
| http_307 | 1 |
| other | 1 |
| http_530 | 1 |

**Diagnóstico sob Carga Total:**

> **proxy lento — latência média alta; bandwidth ou capacidade do proxy esgotada**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Avg HTTP Time | 26588.1ms | Tempo médio efetivo de rede |
| CV Latência | 0.477 | Instabilidade (>1.0 = muito instável) |
| Peak Ativo | 2000 (100.0%) | Pico de conexões ativas simultâneas |
| Média Ativo | 1296.8 | Média de conexões ativas (amostras 0.5s) |

**Tempo HTTP Efetivo (ms) — sem tempo em fila:**

| p25 | p50 | p75 | p90 | p95 | p99 | max | avg |
|-----|-----|-----|-----|-----|-----|-----|-----|
| 14017.1 | 25219.0 | 40378.5 | 40498.1 | 40535.6 | 40566.0 | 40572.5 | 26588.1 |

**Bandwidth Série Temporal (MB/s, amostras de 0.5s):**

| p25 | p50 | p75 | p90 | p95 | max | avg | stdev |
|-----|-----|-----|-----|-----|-----|-----|-------|
| 0.3 | 3.3 | 11.1 | 22.2 | 28.1 | 57.4 | 7.6 | 10.7 |

**Histograma de Tempo:**

| Bucket | OK | FAIL | Total | FAIL% |
|--------|-----|------|-------|-------|
| 3-6s | 19 | 8 | 27 | 29.6% |
| 6-10s | 117 | 6 | 123 | 4.9% |
| 10-15s | 406 | 19 | 425 | 4.5% |
| 15-20s | 247 | 8 | 255 | 3.1% |
| 20-30s | 277 | 11 | 288 | 3.8% |
| 30-40s | 75 | 4 | 79 | 5.1% |
| 40s+ | 0 | 803 | 803 | 100.0% |

**Timeline Granular (janelas de 5s):**

| Janela | OK | Fail | Success% | lat_p50ms | lat_p90ms | BW MB/s |
|--------|-----|------|----------|-----------|-----------|---------|
| 0s-5s | 11 | 7 | 61.1% | 3792.6 | 3976.8 | 0.013 |
| 5s-10s | 118 | 7 | 94.4% | 8661.3 | 9787.3 | 2.249 |
| 10s-15s | 407 | 19 | 95.5% | 12492.2 | 14213.6 | 13.12 |
| 15s-20s | 243 | 8 | 96.8% | 17515.5 | 19452.1 | 20.333 |
| 20s-25s | 166 | 5 | 97.1% | 21871.5 | 24126.5 | 16.593 |
| 25s-30s | 110 | 6 | 94.8% | 28280.2 | 29580.1 | 5.29 |
| 30s-35s | 67 | 4 | 94.4% | 31367.8 | 34121.5 | 2.611 |
| 35s-40s | 19 | 0 | 100.0% | 37678.3 | 38959.4 | 0.589 |
| 40s-45s | 0 | 803 | 0.0% | 0 | 0 | 0.0 |

**Taxa de Erro Acumulada ao Longo do Teste:**

| Req completadas | % do total | Taxa de erro |
|-----------------|------------|--------------|
| 200 | 10% | 4.0% |
| 400 | 20% | 4.0% |
| 600 | 30% | 6.0% |
| 800 | 40% | 5.8% |
| 1000 | 50% | 5.9% |
| 1200 | 60% | 14.8% |
| 1400 | 70% | 25.9% |
| 1600 | 80% | 30.1% |
| 1800 | 90% | 37.3% |
| 2000 | 100% | 43.0% |

**Erros por Terço do Teste:**

| 1º terço | 2º terço | 3º terço | Tendência |
|----------|----------|----------|-----------|
| 39 | 265 | 555 | ↑ piora ao longo do tempo |

---


## Dados Brutos (JSON)

```json
{
  "800": {
    "711proxy": {
      "provider": "711proxy",
      "concurrency": 800,
      "total_urls": 800,
      "total_time_s": 40.5,
      "throughput_per_min": 1186.1,
      "success": 624,
      "fail": 176,
      "success_rate_pct": 78.0,
      "latency_all_ms": {
        "min": 1742.6,
        "p25": 14001.4,
        "p50": 14601.9,
        "p75": 18653.5,
        "p90": 20537.2,
        "p95": 21521.1,
        "p99": 40056.8,
        "max": 40161.5,
        "avg": 15135.1,
        "stdev": 6195.5
      },
      "latency_ok_ms": {
        "min": 4014.7,
        "p25": 12801.9,
        "p50": 14601.9,
        "p75": 18540.4,
        "p90": 20299.4,
        "p95": 20932.1,
        "p99": 24046.8,
        "max": 36288.2,
        "avg": 14511.2,
        "stdev": 5086.1
      },
      "latency_fail_ms": {
        "min": 1742.6,
        "p25": 14104.7,
        "p50": 14603.0,
        "p75": 18754.3,
        "p90": 34070.5,
        "p95": 40053.5,
        "p99": 40110.2,
        "max": 40161.5,
        "avg": 17347.3,
        "stdev": 8766.3
      },
      "http_time_ms": {
        "min": 1742.6,
        "p25": 14001.4,
        "p50": 14601.9,
        "p75": 18653.5,
        "p90": 20537.2,
        "p95": 21521.1,
        "p99": 40056.8,
        "max": 40161.5,
        "avg": 15135.1,
        "stdev": 6195.5
      },
      "error_breakdown": {
        "connection": 155,
        "timeout": 11,
        "http_404": 4,
        "http_403": 3,
        "reset": 2,
        "http_526": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 41209,
        "p50": 114173,
        "p75": 265130,
        "p90": 712979,
        "p95": 1114697,
        "p99": 2219342,
        "max": 10784560,
        "avg": 280319.5,
        "stdev": 598182.5
      },
      "total_data_mb": 174.96,
      "bandwidth_mbps": 34.59,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 0.2,
        "p75": 4.5,
        "p90": 17.5,
        "p95": 30.8,
        "p99": 48.7,
        "max": 48.7,
        "avg": 4.9,
        "stdev": 9.9
      },
      "connections": {
        "peak": 799,
        "samples": {
          "min": 0,
          "p25": 24,
          "p50": 35,
          "p75": 628,
          "p90": 719,
          "p95": 799,
          "p99": 800,
          "max": 800,
          "avg": 249.7,
          "stdev": 299.9
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 0,
          "fail": 3
        },
        "3-6s": {
          "ok": 79,
          "fail": 13
        },
        "6-10s": {
          "ok": 28,
          "fail": 1
        },
        "10-15s": {
          "ok": 235,
          "fail": 82
        },
        "15-20s": {
          "ok": 201,
          "fail": 44
        },
        "20-30s": {
          "ok": 80,
          "fail": 10
        },
        "30-40s": {
          "ok": 1,
          "fail": 12
        },
        "40s+": {
          "ok": 0,
          "fail": 11
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 58,
        "t2_mid_third": 56,
        "t3_last_third": 62
      },
      "degradation_point": "10-15s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 43,
          "fail": 13,
          "total": 56,
          "success_pct": 76.8,
          "lat_ok_p50_ms": 4401.3,
          "lat_ok_p90_ms": 4433.3,
          "lat_all_p50_ms": 4401.3,
          "bw_mbs": 0.23
        },
        {
          "t": "5s-10s",
          "ok": 58,
          "fail": 4,
          "total": 62,
          "success_pct": 93.5,
          "lat_ok_p50_ms": 5822.6,
          "lat_ok_p90_ms": 7830.1,
          "lat_all_p50_ms": 5768.3,
          "bw_mbs": 0.842
        },
        {
          "t": "10s-15s",
          "ok": 222,
          "fail": 77,
          "total": 299,
          "success_pct": 74.2,
          "lat_ok_p50_ms": 14075.1,
          "lat_ok_p90_ms": 14587.8,
          "lat_all_p50_ms": 14099.7,
          "bw_mbs": 5.065
        },
        {
          "t": "15s-20s",
          "ok": 207,
          "fail": 47,
          "total": 254,
          "success_pct": 81.5,
          "lat_ok_p50_ms": 17435.6,
          "lat_ok_p90_ms": 19218.8,
          "lat_all_p50_ms": 17400.2,
          "bw_mbs": 13.014
        },
        {
          "t": "20s-25s",
          "ok": 88,
          "fail": 12,
          "total": 100,
          "success_pct": 88.0,
          "lat_ok_p50_ms": 20478.6,
          "lat_ok_p90_ms": 21490.0,
          "lat_all_p50_ms": 20543.8,
          "bw_mbs": 14.71
        },
        {
          "t": "25s-30s",
          "ok": 5,
          "fail": 0,
          "total": 5,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 25307.8,
          "lat_ok_p90_ms": 27495.5,
          "lat_all_p50_ms": 25307.8,
          "bw_mbs": 1.111
        },
        {
          "t": "30s-35s",
          "ok": 0,
          "fail": 6,
          "total": 6,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 32396.0,
          "bw_mbs": 0.0
        },
        {
          "t": "35s-40s",
          "ok": 1,
          "fail": 6,
          "total": 7,
          "success_pct": 14.3,
          "lat_ok_p50_ms": 36288.2,
          "lat_ok_p90_ms": 36288.2,
          "lat_all_p50_ms": 35847.4,
          "bw_mbs": 0.02
        },
        {
          "t": "40s-45s",
          "ok": 0,
          "fail": 11,
          "total": 11,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 40060.2,
          "bw_mbs": 0.0
        }
      ],
      "saturation": {
        "avg_http_time_ms": 15135.1,
        "avg_elapsed_ms": 15135.1,
        "cv_latency": 0.409,
        "peak_active": 800,
        "peak_active_pct": 100.0,
        "avg_active_connections": 249.7,
        "bottleneck_diagnosis": "proxy sob pressão — latência elevada mas ainda funcional"
      },
      "cumulative_error_rate": [
        {
          "at_request": 80,
          "pct_complete": 10.0,
          "error_rate_pct": 31.2
        },
        {
          "at_request": 160,
          "pct_complete": 20.0,
          "error_rate_pct": 24.4
        },
        {
          "at_request": 240,
          "pct_complete": 30.0,
          "error_rate_pct": 21.2
        },
        {
          "at_request": 320,
          "pct_complete": 40.0,
          "error_rate_pct": 21.2
        },
        {
          "at_request": 400,
          "pct_complete": 50.0,
          "error_rate_pct": 19.8
        },
        {
          "at_request": 480,
          "pct_complete": 60.0,
          "error_rate_pct": 20.8
        },
        {
          "at_request": 560,
          "pct_complete": 70.0,
          "error_rate_pct": 21.2
        },
        {
          "at_request": 640,
          "pct_complete": 80.0,
          "error_rate_pct": 22.0
        },
        {
          "at_request": 720,
          "pct_complete": 90.0,
          "error_rate_pct": 22.2
        },
        {
          "at_request": 800,
          "pct_complete": 100.0,
          "error_rate_pct": 22.0
        }
      ]
    },
    "decodo": {
      "provider": "decodo",
      "concurrency": 800,
      "total_urls": 800,
      "total_time_s": 23.1,
      "throughput_per_min": 2079.2,
      "success": 697,
      "fail": 103,
      "success_rate_pct": 87.1,
      "latency_all_ms": {
        "min": 750.2,
        "p25": 4948.0,
        "p50": 6885.3,
        "p75": 8741.2,
        "p90": 10202.2,
        "p95": 11478.5,
        "p99": 14599.0,
        "max": 23033.7,
        "avg": 6944.3,
        "stdev": 2794.2
      },
      "latency_ok_ms": {
        "min": 1578.9,
        "p25": 5397.0,
        "p50": 7240.1,
        "p75": 8934.0,
        "p90": 10588.3,
        "p95": 11491.8,
        "p99": 14599.0,
        "max": 23033.7,
        "avg": 7195.6,
        "stdev": 2779.9
      },
      "latency_fail_ms": {
        "min": 750.2,
        "p25": 4721.3,
        "p50": 4948.0,
        "p75": 5955.1,
        "p90": 6888.8,
        "p95": 8345.2,
        "p99": 13917.8,
        "max": 15425.1,
        "avg": 5243.6,
        "stdev": 2253.0
      },
      "http_time_ms": {
        "min": 750.2,
        "p25": 4948.0,
        "p50": 6885.3,
        "p75": 8741.2,
        "p90": 10202.2,
        "p95": 11478.5,
        "p99": 14599.0,
        "max": 23033.7,
        "avg": 6944.3,
        "stdev": 2794.2
      },
      "error_breakdown": {
        "connection": 78,
        "http_522": 10,
        "other": 3,
        "http_404": 3,
        "http_403": 3,
        "http_500": 2,
        "http_429": 1,
        "http_530": 1,
        "http_526": 1,
        "http_503": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 43292,
        "p50": 120408,
        "p75": 253752,
        "p90": 625982,
        "p95": 910203,
        "p99": 2034217,
        "max": 7834755,
        "avg": 254978.6,
        "stdev": 475335.3
      },
      "total_data_mb": 177.54,
      "bandwidth_mbps": 61.52,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 1.3,
        "p75": 13.1,
        "p90": 25.0,
        "p95": 29.5,
        "p99": 45.8,
        "max": 45.8,
        "avg": 7.5,
        "stdev": 11.5
      },
      "connections": {
        "peak": 799,
        "samples": {
          "min": 0,
          "p25": 3,
          "p50": 28,
          "p75": 511,
          "p90": 764,
          "p95": 794,
          "p99": 800,
          "max": 800,
          "avg": 230,
          "stdev": 301.6
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 47,
          "fail": 11
        },
        "3-6s": {
          "ok": 176,
          "fail": 67
        },
        "6-10s": {
          "ok": 389,
          "fail": 22
        },
        "10-15s": {
          "ok": 81,
          "fail": 2
        },
        "15-20s": {
          "ok": 3,
          "fail": 1
        },
        "20-30s": {
          "ok": 1,
          "fail": 0
        },
        "30-40s": {
          "ok": 0,
          "fail": 0
        },
        "40s+": {
          "ok": 0,
          "fail": 0
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 35,
        "t2_mid_third": 31,
        "t3_last_third": 37
      },
      "degradation_point": "3-6s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 144,
          "fail": 48,
          "total": 192,
          "success_pct": 75.0,
          "lat_ok_p50_ms": 3336.2,
          "lat_ok_p90_ms": 4671.7,
          "lat_all_p50_ms": 3500.9,
          "bw_mbs": 1.973
        },
        {
          "t": "5s-10s",
          "ok": 462,
          "fail": 52,
          "total": 514,
          "success_pct": 89.9,
          "lat_ok_p50_ms": 7611.4,
          "lat_ok_p90_ms": 9364.5,
          "lat_all_p50_ms": 7440.1,
          "bw_mbs": 21.034
        },
        {
          "t": "10s-15s",
          "ok": 86,
          "fail": 2,
          "total": 88,
          "success_pct": 97.7,
          "lat_ok_p50_ms": 11252.0,
          "lat_ok_p90_ms": 12918.4,
          "lat_all_p50_ms": 11270.7,
          "bw_mbs": 12.212
        },
        {
          "t": "15s-20s",
          "ok": 4,
          "fail": 1,
          "total": 5,
          "success_pct": 80.0,
          "lat_ok_p50_ms": 18431.0,
          "lat_ok_p90_ms": 19762.7,
          "lat_all_p50_ms": 16388.4,
          "bw_mbs": 0.261
        },
        {
          "t": "20s-25s",
          "ok": 1,
          "fail": 0,
          "total": 1,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 23033.7,
          "lat_ok_p90_ms": 23033.7,
          "lat_all_p50_ms": 23033.7,
          "bw_mbs": 0.028
        }
      ],
      "saturation": {
        "avg_http_time_ms": 6944.3,
        "avg_elapsed_ms": 6944.3,
        "cv_latency": 0.402,
        "peak_active": 800,
        "peak_active_pct": 100.0,
        "avg_active_connections": 230,
        "bottleneck_diagnosis": "proxy saudável — absorveu a carga sem degradação severa"
      },
      "cumulative_error_rate": [
        {
          "at_request": 80,
          "pct_complete": 10.0,
          "error_rate_pct": 11.2
        },
        {
          "at_request": 160,
          "pct_complete": 20.0,
          "error_rate_pct": 13.8
        },
        {
          "at_request": 240,
          "pct_complete": 30.0,
          "error_rate_pct": 14.6
        },
        {
          "at_request": 320,
          "pct_complete": 40.0,
          "error_rate_pct": 13.4
        },
        {
          "at_request": 400,
          "pct_complete": 50.0,
          "error_rate_pct": 12.5
        },
        {
          "at_request": 480,
          "pct_complete": 60.0,
          "error_rate_pct": 12.3
        },
        {
          "at_request": 560,
          "pct_complete": 70.0,
          "error_rate_pct": 12.7
        },
        {
          "at_request": 640,
          "pct_complete": 80.0,
          "error_rate_pct": 13.0
        },
        {
          "at_request": 720,
          "pct_complete": 90.0,
          "error_rate_pct": 12.8
        },
        {
          "at_request": 800,
          "pct_complete": 100.0,
          "error_rate_pct": 12.9
        }
      ]
    },
    "evomi": {
      "provider": "evomi",
      "concurrency": 800,
      "total_urls": 800,
      "total_time_s": 40.4,
      "throughput_per_min": 1187.9,
      "success": 768,
      "fail": 32,
      "success_rate_pct": 96.0,
      "latency_all_ms": {
        "min": 954.7,
        "p25": 7653.4,
        "p50": 9220.0,
        "p75": 11170.6,
        "p90": 12414.1,
        "p95": 13149.9,
        "p99": 28509.9,
        "max": 40145.3,
        "avg": 9350.4,
        "stdev": 4209.4
      },
      "latency_ok_ms": {
        "min": 3016.9,
        "p25": 7784.3,
        "p50": 9245.3,
        "p75": 11167.2,
        "p90": 12336.1,
        "p95": 12918.8,
        "p99": 16915.3,
        "max": 28509.9,
        "avg": 9164.0,
        "stdev": 2991.8
      },
      "latency_fail_ms": {
        "min": 954.7,
        "p25": 3163.3,
        "p50": 7549.0,
        "p75": 25897.3,
        "p90": 40123.0,
        "p95": 40143.7,
        "p99": 40145.3,
        "max": 40145.3,
        "avg": 13824.1,
        "stdev": 14618.4
      },
      "http_time_ms": {
        "min": 954.7,
        "p25": 7653.4,
        "p50": 9220.0,
        "p75": 11170.6,
        "p90": 12414.1,
        "p95": 13149.9,
        "p99": 28509.9,
        "max": 40145.3,
        "avg": 9350.4,
        "stdev": 4209.4
      },
      "error_breakdown": {
        "connection": 12,
        "http_404": 6,
        "timeout": 6,
        "http_500": 3,
        "other": 2,
        "http_403": 1,
        "http_503": 1,
        "http_502": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 47271,
        "p50": 119411,
        "p75": 243870,
        "p90": 626895,
        "p95": 1001819,
        "p99": 1968655,
        "max": 7834755,
        "avg": 255609.1,
        "stdev": 467918.4
      },
      "total_data_mb": 196.13,
      "bandwidth_mbps": 38.83,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 0.0,
        "p75": 2.2,
        "p90": 21.5,
        "p95": 36.4,
        "p99": 49.2,
        "max": 49.2,
        "avg": 5.1,
        "stdev": 11.3
      },
      "connections": {
        "peak": 799,
        "samples": {
          "min": 0,
          "p25": 6,
          "p50": 13,
          "p75": 121,
          "p90": 682,
          "p95": 748,
          "p99": 800,
          "max": 800,
          "avg": 154.2,
          "stdev": 263.3
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 0,
          "fail": 5
        },
        "3-6s": {
          "ok": 117,
          "fail": 10
        },
        "6-10s": {
          "ok": 341,
          "fail": 5
        },
        "10-15s": {
          "ok": 299,
          "fail": 1
        },
        "15-20s": {
          "ok": 5,
          "fail": 2
        },
        "20-30s": {
          "ok": 6,
          "fail": 3
        },
        "30-40s": {
          "ok": 0,
          "fail": 0
        },
        "40s+": {
          "ok": 0,
          "fail": 6
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 10,
        "t2_mid_third": 10,
        "t3_last_third": 12
      },
      "degradation_point": null,
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 82,
          "fail": 14,
          "total": 96,
          "success_pct": 85.4,
          "lat_ok_p50_ms": 3754.7,
          "lat_ok_p90_ms": 4517.8,
          "lat_all_p50_ms": 3673.8,
          "bw_mbs": 0.715
        },
        {
          "t": "5s-10s",
          "ok": 362,
          "fail": 6,
          "total": 368,
          "success_pct": 98.4,
          "lat_ok_p50_ms": 8195.1,
          "lat_ok_p90_ms": 9448.7,
          "lat_all_p50_ms": 8188.5,
          "bw_mbs": 12.003
        },
        {
          "t": "10s-15s",
          "ok": 313,
          "fail": 1,
          "total": 314,
          "success_pct": 99.7,
          "lat_ok_p50_ms": 11307.2,
          "lat_ok_p90_ms": 12855.9,
          "lat_all_p50_ms": 11309.2,
          "bw_mbs": 25.097
        },
        {
          "t": "15s-20s",
          "ok": 4,
          "fail": 2,
          "total": 6,
          "success_pct": 66.7,
          "lat_ok_p50_ms": 16595.0,
          "lat_ok_p90_ms": 16915.3,
          "lat_all_p50_ms": 16595.0,
          "bw_mbs": 0.782
        },
        {
          "t": "20s-25s",
          "ok": 6,
          "fail": 1,
          "total": 7,
          "success_pct": 85.7,
          "lat_ok_p50_ms": 22963.0,
          "lat_ok_p90_ms": 24590.5,
          "lat_all_p50_ms": 22805.0,
          "bw_mbs": 0.624
        },
        {
          "t": "25s-30s",
          "ok": 1,
          "fail": 2,
          "total": 3,
          "success_pct": 33.3,
          "lat_ok_p50_ms": 28509.9,
          "lat_ok_p90_ms": 28509.9,
          "lat_all_p50_ms": 28509.9,
          "bw_mbs": 0.005
        },
        {
          "t": "40s-45s",
          "ok": 0,
          "fail": 6,
          "total": 6,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 40140.8,
          "bw_mbs": 0.0
        }
      ],
      "saturation": {
        "avg_http_time_ms": 9350.4,
        "avg_elapsed_ms": 9350.4,
        "cv_latency": 0.45,
        "peak_active": 800,
        "peak_active_pct": 100.0,
        "avg_active_connections": 154.2,
        "bottleneck_diagnosis": "proxy saudável — absorveu a carga sem degradação severa"
      },
      "cumulative_error_rate": [
        {
          "at_request": 80,
          "pct_complete": 10.0,
          "error_rate_pct": 3.8
        },
        {
          "at_request": 160,
          "pct_complete": 20.0,
          "error_rate_pct": 3.8
        },
        {
          "at_request": 240,
          "pct_complete": 30.0,
          "error_rate_pct": 3.8
        },
        {
          "at_request": 320,
          "pct_complete": 40.0,
          "error_rate_pct": 4.1
        },
        {
          "at_request": 400,
          "pct_complete": 50.0,
          "error_rate_pct": 4.2
        },
        {
          "at_request": 480,
          "pct_complete": 60.0,
          "error_rate_pct": 4.0
        },
        {
          "at_request": 560,
          "pct_complete": 70.0,
          "error_rate_pct": 4.3
        },
        {
          "at_request": 640,
          "pct_complete": 80.0,
          "error_rate_pct": 3.8
        },
        {
          "at_request": 720,
          "pct_complete": 90.0,
          "error_rate_pct": 3.8
        },
        {
          "at_request": 800,
          "pct_complete": 100.0,
          "error_rate_pct": 4.0
        }
      ]
    }
  },
  "1200": {
    "711proxy": {
      "provider": "711proxy",
      "concurrency": 1200,
      "total_urls": 1200,
      "total_time_s": 40.2,
      "throughput_per_min": 1791.6,
      "success": 1107,
      "fail": 93,
      "success_rate_pct": 92.2,
      "latency_all_ms": {
        "min": 1286.0,
        "p25": 6225.5,
        "p50": 8039.9,
        "p75": 13648.7,
        "p90": 22896.0,
        "p95": 31348.6,
        "p99": 39599.8,
        "max": 40064.3,
        "avg": 11440.9,
        "stdev": 8809.5
      },
      "latency_ok_ms": {
        "min": 1286.0,
        "p25": 6310.2,
        "p50": 8011.6,
        "p75": 12738.0,
        "p90": 22756.9,
        "p95": 24654.2,
        "p99": 38971.9,
        "max": 39695.7,
        "avg": 11092.1,
        "stdev": 8271.2
      },
      "latency_fail_ms": {
        "min": 1362.7,
        "p25": 5697.5,
        "p50": 8986.3,
        "p75": 22467.8,
        "p90": 40042.0,
        "p95": 40045.2,
        "p99": 40064.3,
        "max": 40064.3,
        "avg": 15592.6,
        "stdev": 13042.6
      },
      "http_time_ms": {
        "min": 1286.0,
        "p25": 6225.5,
        "p50": 8039.9,
        "p75": 13648.7,
        "p90": 22896.0,
        "p95": 31348.6,
        "p99": 39599.8,
        "max": 40064.3,
        "avg": 11440.9,
        "stdev": 8809.5
      },
      "error_breakdown": {
        "connection": 65,
        "timeout": 10,
        "http_404": 9,
        "http_403": 6,
        "http_500": 2,
        "http_530": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 43817,
        "p50": 115697,
        "p75": 250228,
        "p90": 626895,
        "p95": 1026905,
        "p99": 2034217,
        "max": 10784560,
        "avg": 270115.3,
        "stdev": 584644.6
      },
      "total_data_mb": 298.54,
      "bandwidth_mbps": 59.43,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 1.3,
        "p75": 8.4,
        "p90": 30.9,
        "p95": 39.2,
        "p99": 46.8,
        "max": 46.8,
        "avg": 7.5,
        "stdev": 12.5
      },
      "connections": {
        "peak": 1199,
        "samples": {
          "min": 0,
          "p25": 62,
          "p50": 272,
          "p75": 392,
          "p90": 1059,
          "p95": 1191,
          "p99": 1200,
          "max": 1200,
          "avg": 336.4,
          "stdev": 367.8
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 87,
          "fail": 7
        },
        "3-6s": {
          "ok": 154,
          "fail": 18
        },
        "6-10s": {
          "ok": 513,
          "fail": 25
        },
        "10-15s": {
          "ok": 101,
          "fail": 6
        },
        "15-20s": {
          "ok": 11,
          "fail": 6
        },
        "20-30s": {
          "ok": 200,
          "fail": 10
        },
        "30-40s": {
          "ok": 41,
          "fail": 11
        },
        "40s+": {
          "ok": 0,
          "fail": 10
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 33,
        "t2_mid_third": 29,
        "t3_last_third": 31
      },
      "degradation_point": "15-20s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 172,
          "fail": 19,
          "total": 191,
          "success_pct": 90.1,
          "lat_ok_p50_ms": 2999.6,
          "lat_ok_p90_ms": 4737.2,
          "lat_all_p50_ms": 3023.8,
          "bw_mbs": 1.699
        },
        {
          "t": "5s-10s",
          "ok": 561,
          "fail": 30,
          "total": 591,
          "success_pct": 94.9,
          "lat_ok_p50_ms": 7367.4,
          "lat_ok_p90_ms": 8835.5,
          "lat_all_p50_ms": 7346.3,
          "bw_mbs": 28.276
        },
        {
          "t": "10s-15s",
          "ok": 121,
          "fail": 7,
          "total": 128,
          "success_pct": 94.5,
          "lat_ok_p50_ms": 10528.2,
          "lat_ok_p90_ms": 13498.7,
          "lat_all_p50_ms": 10493.5,
          "bw_mbs": 17.95
        },
        {
          "t": "15s-20s",
          "ok": 12,
          "fail": 6,
          "total": 18,
          "success_pct": 66.7,
          "lat_ok_p50_ms": 16171.4,
          "lat_ok_p90_ms": 17807.9,
          "lat_all_p50_ms": 16865.2,
          "bw_mbs": 1.203
        },
        {
          "t": "20s-25s",
          "ok": 188,
          "fail": 10,
          "total": 198,
          "success_pct": 94.9,
          "lat_ok_p50_ms": 22098.7,
          "lat_ok_p90_ms": 23520.4,
          "lat_all_p50_ms": 22054.9,
          "bw_mbs": 8.165
        },
        {
          "t": "25s-30s",
          "ok": 12,
          "fail": 0,
          "total": 12,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 25895.5,
          "lat_ok_p90_ms": 26909.0,
          "lat_all_p50_ms": 25895.5,
          "bw_mbs": 0.325
        },
        {
          "t": "30s-35s",
          "ok": 1,
          "fail": 7,
          "total": 8,
          "success_pct": 12.5,
          "lat_ok_p50_ms": 30228.6,
          "lat_ok_p90_ms": 30228.6,
          "lat_all_p50_ms": 32642.4,
          "bw_mbs": 0.026
        },
        {
          "t": "35s-40s",
          "ok": 40,
          "fail": 4,
          "total": 44,
          "success_pct": 90.9,
          "lat_ok_p50_ms": 38181.7,
          "lat_ok_p90_ms": 39372.0,
          "lat_all_p50_ms": 38149.5,
          "bw_mbs": 2.064
        },
        {
          "t": "40s-45s",
          "ok": 0,
          "fail": 10,
          "total": 10,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 40045.2,
          "bw_mbs": 0.0
        }
      ],
      "saturation": {
        "avg_http_time_ms": 11440.9,
        "avg_elapsed_ms": 11440.9,
        "cv_latency": 0.77,
        "peak_active": 1200,
        "peak_active_pct": 100.0,
        "avg_active_connections": 336.4,
        "bottleneck_diagnosis": "proxy saudável — absorveu a carga sem degradação severa"
      },
      "cumulative_error_rate": [
        {
          "at_request": 120,
          "pct_complete": 10.0,
          "error_rate_pct": 10.8
        },
        {
          "at_request": 240,
          "pct_complete": 20.0,
          "error_rate_pct": 9.6
        },
        {
          "at_request": 360,
          "pct_complete": 30.0,
          "error_rate_pct": 8.6
        },
        {
          "at_request": 480,
          "pct_complete": 40.0,
          "error_rate_pct": 9.0
        },
        {
          "at_request": 600,
          "pct_complete": 50.0,
          "error_rate_pct": 8.2
        },
        {
          "at_request": 720,
          "pct_complete": 60.0,
          "error_rate_pct": 7.5
        },
        {
          "at_request": 840,
          "pct_complete": 70.0,
          "error_rate_pct": 7.7
        },
        {
          "at_request": 960,
          "pct_complete": 80.0,
          "error_rate_pct": 7.7
        },
        {
          "at_request": 1080,
          "pct_complete": 90.0,
          "error_rate_pct": 7.2
        },
        {
          "at_request": 1200,
          "pct_complete": 100.0,
          "error_rate_pct": 7.8
        }
      ]
    },
    "decodo": {
      "provider": "decodo",
      "concurrency": 1200,
      "total_urls": 1200,
      "total_time_s": 40.4,
      "throughput_per_min": 1783.0,
      "success": 1067,
      "fail": 133,
      "success_rate_pct": 88.9,
      "latency_all_ms": {
        "min": 954.9,
        "p25": 6035.0,
        "p50": 8040.5,
        "p75": 12689.7,
        "p90": 22658.9,
        "p95": 23412.1,
        "p99": 26082.1,
        "max": 40212.1,
        "avg": 10670.0,
        "stdev": 7172.4
      },
      "latency_ok_ms": {
        "min": 1647.6,
        "p25": 6537.9,
        "p50": 8296.2,
        "p75": 12268.8,
        "p90": 22560.7,
        "p95": 23283.4,
        "p99": 25601.6,
        "max": 38336.0,
        "avg": 10770.1,
        "stdev": 6838.8
      },
      "latency_fail_ms": {
        "min": 954.9,
        "p25": 5030.5,
        "p50": 5742.2,
        "p75": 13548.6,
        "p90": 23151.2,
        "p95": 25027.2,
        "p99": 40211.9,
        "max": 40212.1,
        "avg": 9866.6,
        "stdev": 9425.8
      },
      "http_time_ms": {
        "min": 954.9,
        "p25": 6035.0,
        "p50": 8040.5,
        "p75": 12689.7,
        "p90": 22658.9,
        "p95": 23412.1,
        "p99": 26082.1,
        "max": 40212.1,
        "avg": 10670.0,
        "stdev": 7172.4
      },
      "error_breakdown": {
        "connection": 99,
        "http_522": 11,
        "timeout": 5,
        "http_500": 4,
        "other": 3,
        "http_404": 3,
        "http_502": 2,
        "http_503": 2,
        "http_526": 1,
        "http_403": 1,
        "http_307": 1,
        "http_530": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 44170,
        "p50": 123688,
        "p75": 251319,
        "p90": 629578,
        "p95": 1028540,
        "p99": 1974528,
        "max": 10784554,
        "avg": 268119.1,
        "stdev": 575458.8
      },
      "total_data_mb": 285.86,
      "bandwidth_mbps": 56.63,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 0.7,
        "p75": 8.7,
        "p90": 24.9,
        "p95": 36.9,
        "p99": 57.2,
        "max": 57.2,
        "avg": 7.1,
        "stdev": 12.6
      },
      "connections": {
        "peak": 1199,
        "samples": {
          "min": 0,
          "p25": 8,
          "p50": 250,
          "p75": 363,
          "p90": 1032,
          "p95": 1146,
          "p99": 1200,
          "max": 1200,
          "avg": 306.4,
          "stdev": 378.3
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 61,
          "fail": 22
        },
        "3-6s": {
          "ok": 153,
          "fail": 59
        },
        "6-10s": {
          "ok": 472,
          "fail": 14
        },
        "10-15s": {
          "ok": 141,
          "fail": 8
        },
        "15-20s": {
          "ok": 13,
          "fail": 3
        },
        "20-30s": {
          "ok": 224,
          "fail": 22
        },
        "30-40s": {
          "ok": 3,
          "fail": 0
        },
        "40s+": {
          "ok": 0,
          "fail": 5
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 50,
        "t2_mid_third": 39,
        "t3_last_third": 44
      },
      "degradation_point": "0-3s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 154,
          "fail": 30,
          "total": 184,
          "success_pct": 83.7,
          "lat_ok_p50_ms": 3253.5,
          "lat_ok_p90_ms": 4201.8,
          "lat_all_p50_ms": 3176.1,
          "bw_mbs": 2.821
        },
        {
          "t": "5s-10s",
          "ok": 525,
          "fail": 65,
          "total": 590,
          "success_pct": 89.0,
          "lat_ok_p50_ms": 7316.1,
          "lat_ok_p90_ms": 9378.8,
          "lat_all_p50_ms": 7159.7,
          "bw_mbs": 23.5
        },
        {
          "t": "10s-15s",
          "ok": 148,
          "fail": 8,
          "total": 156,
          "success_pct": 94.9,
          "lat_ok_p50_ms": 10847.4,
          "lat_ok_p90_ms": 13599.1,
          "lat_all_p50_ms": 10934.1,
          "bw_mbs": 17.92
        },
        {
          "t": "15s-20s",
          "ok": 13,
          "fail": 2,
          "total": 15,
          "success_pct": 86.7,
          "lat_ok_p50_ms": 15753.7,
          "lat_ok_p90_ms": 17725.1,
          "lat_all_p50_ms": 15753.7,
          "bw_mbs": 1.555
        },
        {
          "t": "20s-25s",
          "ok": 212,
          "fail": 21,
          "total": 233,
          "success_pct": 91.0,
          "lat_ok_p50_ms": 22367.0,
          "lat_ok_p90_ms": 23792.1,
          "lat_all_p50_ms": 22404.6,
          "bw_mbs": 10.734
        },
        {
          "t": "25s-30s",
          "ok": 12,
          "fail": 2,
          "total": 14,
          "success_pct": 85.7,
          "lat_ok_p50_ms": 25677.3,
          "lat_ok_p90_ms": 26796.6,
          "lat_all_p50_ms": 25677.3,
          "bw_mbs": 0.457
        },
        {
          "t": "30s-35s",
          "ok": 1,
          "fail": 0,
          "total": 1,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 33884.6,
          "lat_ok_p90_ms": 33884.6,
          "lat_all_p50_ms": 33884.6,
          "bw_mbs": 0.092
        },
        {
          "t": "35s-40s",
          "ok": 2,
          "fail": 0,
          "total": 2,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 38336.0,
          "lat_ok_p90_ms": 38336.0,
          "lat_all_p50_ms": 38336.0,
          "bw_mbs": 0.094
        },
        {
          "t": "40s-45s",
          "ok": 0,
          "fail": 5,
          "total": 5,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 40204.2,
          "bw_mbs": 0.0
        }
      ],
      "saturation": {
        "avg_http_time_ms": 10670.0,
        "avg_elapsed_ms": 10670.0,
        "cv_latency": 0.672,
        "peak_active": 1200,
        "peak_active_pct": 100.0,
        "avg_active_connections": 306.4,
        "bottleneck_diagnosis": "proxy saudável — absorveu a carga sem degradação severa"
      },
      "cumulative_error_rate": [
        {
          "at_request": 120,
          "pct_complete": 10.0,
          "error_rate_pct": 15.0
        },
        {
          "at_request": 240,
          "pct_complete": 20.0,
          "error_rate_pct": 13.3
        },
        {
          "at_request": 360,
          "pct_complete": 30.0,
          "error_rate_pct": 11.4
        },
        {
          "at_request": 480,
          "pct_complete": 40.0,
          "error_rate_pct": 12.3
        },
        {
          "at_request": 600,
          "pct_complete": 50.0,
          "error_rate_pct": 12.7
        },
        {
          "at_request": 720,
          "pct_complete": 60.0,
          "error_rate_pct": 11.7
        },
        {
          "at_request": 840,
          "pct_complete": 70.0,
          "error_rate_pct": 11.1
        },
        {
          "at_request": 960,
          "pct_complete": 80.0,
          "error_rate_pct": 11.2
        },
        {
          "at_request": 1080,
          "pct_complete": 90.0,
          "error_rate_pct": 10.9
        },
        {
          "at_request": 1200,
          "pct_complete": 100.0,
          "error_rate_pct": 11.1
        }
      ]
    },
    "evomi": {
      "provider": "evomi",
      "concurrency": 1200,
      "total_urls": 1200,
      "total_time_s": 51.7,
      "throughput_per_min": 1391.5,
      "success": 1153,
      "fail": 47,
      "success_rate_pct": 96.1,
      "latency_all_ms": {
        "min": 1349.3,
        "p25": 7178.3,
        "p50": 9582.2,
        "p75": 14131.2,
        "p90": 23980.7,
        "p95": 29210.7,
        "p99": 33235.2,
        "max": 51640.3,
        "avg": 12350.2,
        "stdev": 8034.2
      },
      "latency_ok_ms": {
        "min": 2632.2,
        "p25": 7290.7,
        "p50": 9608.6,
        "p75": 13629.1,
        "p90": 23099.3,
        "p95": 29020.3,
        "p99": 31217.1,
        "max": 34636.1,
        "avg": 12183.2,
        "stdev": 7535.8
      },
      "latency_fail_ms": {
        "min": 1349.3,
        "p25": 2860.0,
        "p50": 8007.7,
        "p75": 28859.6,
        "p90": 40212.6,
        "p95": 40215.5,
        "p99": 51640.3,
        "max": 51640.3,
        "avg": 16446.7,
        "stdev": 15571.0
      },
      "http_time_ms": {
        "min": 1349.3,
        "p25": 7178.3,
        "p50": 9582.2,
        "p75": 14131.2,
        "p90": 23980.7,
        "p95": 29210.7,
        "p99": 33235.2,
        "max": 51640.3,
        "avg": 12350.2,
        "stdev": 8034.2
      },
      "error_breakdown": {
        "connection": 16,
        "timeout": 8,
        "http_500": 7,
        "http_404": 7,
        "http_403": 3,
        "http_307": 1,
        "other": 1,
        "http_526": 1,
        "http_502": 1,
        "http_503": 1,
        "http_530": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 46635,
        "p50": 118740,
        "p75": 253752,
        "p90": 613305,
        "p95": 1000664,
        "p99": 2004691,
        "max": 10784560,
        "avg": 262321.4,
        "stdev": 526382.8
      },
      "total_data_mb": 302.28,
      "bandwidth_mbps": 46.73,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 0.3,
        "p75": 6.8,
        "p90": 22.7,
        "p95": 29.1,
        "p99": 45.7,
        "max": 47.9,
        "avg": 6.0,
        "stdev": 10.8
      },
      "connections": {
        "peak": 1199,
        "samples": {
          "min": 0,
          "p25": 8,
          "p50": 99,
          "p75": 297,
          "p90": 1007,
          "p95": 1098,
          "p99": 1200,
          "max": 1200,
          "avg": 267.8,
          "stdev": 364.7
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 35,
          "fail": 13
        },
        "3-6s": {
          "ok": 128,
          "fail": 8
        },
        "6-10s": {
          "ok": 448,
          "fail": 6
        },
        "10-15s": {
          "ok": 272,
          "fail": 0
        },
        "15-20s": {
          "ok": 11,
          "fail": 0
        },
        "20-30s": {
          "ok": 232,
          "fail": 11
        },
        "30-40s": {
          "ok": 27,
          "fail": 1
        },
        "40s+": {
          "ok": 0,
          "fail": 8
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 20,
        "t2_mid_third": 11,
        "t3_last_third": 16
      },
      "degradation_point": "0-3s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 134,
          "fail": 20,
          "total": 154,
          "success_pct": 87.0,
          "lat_ok_p50_ms": 3532.1,
          "lat_ok_p90_ms": 4294.5,
          "lat_all_p50_ms": 3372.5,
          "bw_mbs": 1.495
        },
        {
          "t": "5s-10s",
          "ok": 474,
          "fail": 7,
          "total": 481,
          "success_pct": 98.5,
          "lat_ok_p50_ms": 7747.6,
          "lat_ok_p90_ms": 9395.9,
          "lat_all_p50_ms": 7747.6,
          "bw_mbs": 16.45
        },
        {
          "t": "10s-15s",
          "ok": 275,
          "fail": 0,
          "total": 275,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 11644.2,
          "lat_ok_p90_ms": 13508.2,
          "lat_all_p50_ms": 11644.2,
          "bw_mbs": 27.08
        },
        {
          "t": "15s-20s",
          "ok": 11,
          "fail": 0,
          "total": 11,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 16290.8,
          "lat_ok_p90_ms": 18749.1,
          "lat_all_p50_ms": 16290.8,
          "bw_mbs": 0.935
        },
        {
          "t": "20s-25s",
          "ok": 163,
          "fail": 3,
          "total": 166,
          "success_pct": 98.2,
          "lat_ok_p50_ms": 22182.3,
          "lat_ok_p90_ms": 23193.7,
          "lat_all_p50_ms": 22182.3,
          "bw_mbs": 8.254
        },
        {
          "t": "25s-30s",
          "ok": 66,
          "fail": 8,
          "total": 74,
          "success_pct": 89.2,
          "lat_ok_p50_ms": 28976.8,
          "lat_ok_p90_ms": 29610.3,
          "lat_all_p50_ms": 28927.1,
          "bw_mbs": 2.853
        },
        {
          "t": "30s-35s",
          "ok": 30,
          "fail": 0,
          "total": 30,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 31073.7,
          "lat_ok_p90_ms": 33235.2,
          "lat_all_p50_ms": 31073.7,
          "bw_mbs": 3.389
        },
        {
          "t": "35s-40s",
          "ok": 0,
          "fail": 1,
          "total": 1,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 37236.1,
          "bw_mbs": 0.0
        },
        {
          "t": "40s-45s",
          "ok": 0,
          "fail": 7,
          "total": 7,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 40212.6,
          "bw_mbs": 0.0
        },
        {
          "t": "50s-55s",
          "ok": 0,
          "fail": 1,
          "total": 1,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 51640.3,
          "bw_mbs": 0.0
        }
      ],
      "saturation": {
        "avg_http_time_ms": 12350.2,
        "avg_elapsed_ms": 12350.2,
        "cv_latency": 0.651,
        "peak_active": 1200,
        "peak_active_pct": 100.0,
        "avg_active_connections": 267.8,
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
          "error_rate_pct": 5.8
        },
        {
          "at_request": 360,
          "pct_complete": 30.0,
          "error_rate_pct": 5.0
        },
        {
          "at_request": 480,
          "pct_complete": 40.0,
          "error_rate_pct": 4.2
        },
        {
          "at_request": 600,
          "pct_complete": 50.0,
          "error_rate_pct": 3.7
        },
        {
          "at_request": 720,
          "pct_complete": 60.0,
          "error_rate_pct": 3.9
        },
        {
          "at_request": 840,
          "pct_complete": 70.0,
          "error_rate_pct": 4.0
        },
        {
          "at_request": 960,
          "pct_complete": 80.0,
          "error_rate_pct": 4.1
        },
        {
          "at_request": 1080,
          "pct_complete": 90.0,
          "error_rate_pct": 3.8
        },
        {
          "at_request": 1200,
          "pct_complete": 100.0,
          "error_rate_pct": 3.9
        }
      ]
    }
  },
  "1500": {
    "711proxy": {
      "provider": "711proxy",
      "concurrency": 1500,
      "total_urls": 1500,
      "total_time_s": 40.3,
      "throughput_per_min": 2230.8,
      "success": 1162,
      "fail": 338,
      "success_rate_pct": 77.5,
      "latency_all_ms": {
        "min": 1237.0,
        "p25": 7876.6,
        "p50": 10686.0,
        "p75": 23397.2,
        "p90": 40110.9,
        "p95": 40140.7,
        "p99": 40161.3,
        "max": 40173.3,
        "avg": 17323.8,
        "stdev": 13177.4
      },
      "latency_ok_ms": {
        "min": 1800.8,
        "p25": 7241.8,
        "p50": 9727.8,
        "p75": 21171.8,
        "p90": 24176.3,
        "p95": 38203.7,
        "p99": 38943.2,
        "max": 39910.0,
        "avg": 13449.6,
        "stdev": 9750.6
      },
      "latency_fail_ms": {
        "min": 1237.0,
        "p25": 10840.9,
        "p50": 40102.4,
        "p75": 40137.0,
        "p90": 40156.2,
        "p95": 40160.7,
        "p99": 40163.0,
        "max": 40173.3,
        "avg": 30642.5,
        "stdev": 14668.8
      },
      "http_time_ms": {
        "min": 1237.0,
        "p25": 7876.6,
        "p50": 10686.0,
        "p75": 23397.2,
        "p90": 40110.9,
        "p95": 40140.7,
        "p99": 40161.3,
        "max": 40173.3,
        "avg": 17323.8,
        "stdev": 13177.4
      },
      "error_breakdown": {
        "timeout": 231,
        "connection": 88,
        "http_403": 8,
        "http_404": 5,
        "http_503": 2,
        "http_307": 1,
        "http_500": 1,
        "http_521": 1,
        "http_530": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 42594,
        "p50": 116928,
        "p75": 245863,
        "p90": 704228,
        "p95": 1026905,
        "p99": 2004691,
        "max": 10784560,
        "avg": 258699.9,
        "stdev": 494008.7
      },
      "total_data_mb": 300.19,
      "bandwidth_mbps": 59.53,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 1.6,
        "p75": 9.7,
        "p90": 27.0,
        "p95": 42.3,
        "p99": 50.6,
        "max": 50.6,
        "avg": 7.6,
        "stdev": 12.3
      },
      "connections": {
        "peak": 1499,
        "samples": {
          "min": 0,
          "p25": 337,
          "p50": 570,
          "p75": 820,
          "p90": 1334,
          "p95": 1485,
          "p99": 1500,
          "max": 1500,
          "avg": 641.2,
          "stdev": 398.3
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 74,
          "fail": 18
        },
        "3-6s": {
          "ok": 119,
          "fail": 13
        },
        "6-10s": {
          "ok": 415,
          "fail": 41
        },
        "10-15s": {
          "ok": 209,
          "fail": 19
        },
        "15-20s": {
          "ok": 21,
          "fail": 1
        },
        "20-30s": {
          "ok": 225,
          "fail": 8
        },
        "30-40s": {
          "ok": 99,
          "fail": 7
        },
        "40s+": {
          "ok": 0,
          "fail": 231
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 56,
        "t2_mid_third": 49,
        "t3_last_third": 233
      },
      "degradation_point": "40s+",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 151,
          "fail": 25,
          "total": 176,
          "success_pct": 85.8,
          "lat_ok_p50_ms": 3085.3,
          "lat_ok_p90_ms": 3681.8,
          "lat_all_p50_ms": 2931.5,
          "bw_mbs": 1.802
        },
        {
          "t": "5s-10s",
          "ok": 450,
          "fail": 47,
          "total": 497,
          "success_pct": 90.5,
          "lat_ok_p50_ms": 8173.1,
          "lat_ok_p90_ms": 9554.9,
          "lat_all_p50_ms": 8209.9,
          "bw_mbs": 16.958
        },
        {
          "t": "10s-15s",
          "ok": 215,
          "fail": 18,
          "total": 233,
          "success_pct": 92.3,
          "lat_ok_p50_ms": 11071.1,
          "lat_ok_p90_ms": 13317.1,
          "lat_all_p50_ms": 11034.9,
          "bw_mbs": 24.11
        },
        {
          "t": "15s-20s",
          "ok": 22,
          "fail": 2,
          "total": 24,
          "success_pct": 91.7,
          "lat_ok_p50_ms": 15521.8,
          "lat_ok_p90_ms": 18075.2,
          "lat_all_p50_ms": 15521.8,
          "bw_mbs": 2.117
        },
        {
          "t": "20s-25s",
          "ok": 213,
          "fail": 8,
          "total": 221,
          "success_pct": 96.4,
          "lat_ok_p50_ms": 21882.4,
          "lat_ok_p90_ms": 23468.6,
          "lat_all_p50_ms": 21882.4,
          "bw_mbs": 9.826
        },
        {
          "t": "25s-30s",
          "ok": 12,
          "fail": 0,
          "total": 12,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 25578.1,
          "lat_ok_p90_ms": 27447.8,
          "lat_all_p50_ms": 25578.1,
          "bw_mbs": 0.244
        },
        {
          "t": "30s-35s",
          "ok": 1,
          "fail": 5,
          "total": 6,
          "success_pct": 16.7,
          "lat_ok_p50_ms": 33942.6,
          "lat_ok_p90_ms": 33942.6,
          "lat_all_p50_ms": 31839.2,
          "bw_mbs": 0.028
        },
        {
          "t": "35s-40s",
          "ok": 97,
          "fail": 2,
          "total": 99,
          "success_pct": 98.0,
          "lat_ok_p50_ms": 38205.6,
          "lat_ok_p90_ms": 39016.5,
          "lat_all_p50_ms": 38205.8,
          "bw_mbs": 4.753
        },
        {
          "t": "40s-45s",
          "ok": 1,
          "fail": 231,
          "total": 232,
          "success_pct": 0.4,
          "lat_ok_p50_ms": 39910.0,
          "lat_ok_p90_ms": 39910.0,
          "lat_all_p50_ms": 40125.4,
          "bw_mbs": 0.2
        }
      ],
      "saturation": {
        "avg_http_time_ms": 17323.8,
        "avg_elapsed_ms": 17323.8,
        "cv_latency": 0.761,
        "peak_active": 1500,
        "peak_active_pct": 100.0,
        "avg_active_connections": 641.2,
        "bottleneck_diagnosis": "proxy sob pressão — latência elevada mas ainda funcional"
      },
      "cumulative_error_rate": [
        {
          "at_request": 150,
          "pct_complete": 10.0,
          "error_rate_pct": 12.0
        },
        {
          "at_request": 300,
          "pct_complete": 20.0,
          "error_rate_pct": 12.0
        },
        {
          "at_request": 450,
          "pct_complete": 30.0,
          "error_rate_pct": 12.2
        },
        {
          "at_request": 600,
          "pct_complete": 40.0,
          "error_rate_pct": 11.0
        },
        {
          "at_request": 750,
          "pct_complete": 50.0,
          "error_rate_pct": 10.9
        },
        {
          "at_request": 900,
          "pct_complete": 60.0,
          "error_rate_pct": 10.8
        },
        {
          "at_request": 1050,
          "pct_complete": 70.0,
          "error_rate_pct": 10.2
        },
        {
          "at_request": 1200,
          "pct_complete": 80.0,
          "error_rate_pct": 17.0
        },
        {
          "at_request": 1350,
          "pct_complete": 90.0,
          "error_rate_pct": 24.2
        },
        {
          "at_request": 1500,
          "pct_complete": 100.0,
          "error_rate_pct": 22.5
        }
      ]
    },
    "decodo": {
      "provider": "decodo",
      "concurrency": 1500,
      "total_urls": 1500,
      "total_time_s": 62.5,
      "throughput_per_min": 1439.2,
      "success": 1301,
      "fail": 199,
      "success_rate_pct": 86.7,
      "latency_all_ms": {
        "min": 1364.9,
        "p25": 6280.5,
        "p50": 9565.0,
        "p75": 22669.5,
        "p90": 32568.2,
        "p95": 37061.1,
        "p99": 40244.4,
        "max": 62406.4,
        "avg": 14543.8,
        "stdev": 10767.2
      },
      "latency_ok_ms": {
        "min": 2146.1,
        "p25": 6567.0,
        "p50": 9650.4,
        "p75": 22575.5,
        "p90": 31001.3,
        "p95": 35966.9,
        "p99": 39015.7,
        "max": 40138.2,
        "avg": 14426.8,
        "stdev": 10326.7
      },
      "latency_fail_ms": {
        "min": 1364.9,
        "p25": 5361.9,
        "p50": 6811.4,
        "p75": 24013.0,
        "p90": 39905.9,
        "p95": 40267.0,
        "p99": 40280.1,
        "max": 62406.4,
        "avg": 15308.5,
        "stdev": 13298.4
      },
      "http_time_ms": {
        "min": 1364.9,
        "p25": 6280.5,
        "p50": 9565.0,
        "p75": 22669.5,
        "p90": 32568.2,
        "p95": 37061.1,
        "p99": 40244.4,
        "max": 62406.4,
        "avg": 14543.8,
        "stdev": 10767.2
      },
      "error_breakdown": {
        "connection": 142,
        "http_522": 18,
        "timeout": 17,
        "http_404": 7,
        "ssl": 3,
        "other": 3,
        "http_502": 3,
        "http_403": 2,
        "http_526": 1,
        "http_503": 1,
        "http_530": 1,
        "http_307": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 45953,
        "p50": 124548,
        "p75": 274995,
        "p90": 677232,
        "p95": 1017489,
        "p99": 1971333,
        "max": 6730743,
        "avg": 259556.8,
        "stdev": 425988.8
      },
      "total_data_mb": 337.26,
      "bandwidth_mbps": 43.15,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 0.7,
        "p75": 5.9,
        "p90": 18.8,
        "p95": 26.3,
        "p99": 34.6,
        "max": 53.1,
        "avg": 5.4,
        "stdev": 9.4
      },
      "connections": {
        "peak": 1499,
        "samples": {
          "min": 0,
          "p25": 1,
          "p50": 157,
          "p75": 537,
          "p90": 1079,
          "p95": 1393,
          "p99": 1500,
          "max": 1500,
          "avg": 338.1,
          "stdev": 435.0
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 40,
          "fail": 21
        },
        "3-6s": {
          "ok": 215,
          "fail": 63
        },
        "6-10s": {
          "ok": 421,
          "fail": 28
        },
        "10-15s": {
          "ok": 159,
          "fail": 6
        },
        "15-20s": {
          "ok": 19,
          "fail": 3
        },
        "20-30s": {
          "ok": 300,
          "fail": 44
        },
        "30-40s": {
          "ok": 145,
          "fail": 15
        },
        "40s+": {
          "ok": 2,
          "fail": 19
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 60,
        "t2_mid_third": 64,
        "t3_last_third": 75
      },
      "degradation_point": "0-3s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 188,
          "fail": 28,
          "total": 216,
          "success_pct": 87.0,
          "lat_ok_p50_ms": 3621.6,
          "lat_ok_p90_ms": 4322.0,
          "lat_all_p50_ms": 3557.5,
          "bw_mbs": 3.14
        },
        {
          "t": "5s-10s",
          "ok": 483,
          "fail": 84,
          "total": 567,
          "success_pct": 85.2,
          "lat_ok_p50_ms": 7554.4,
          "lat_ok_p90_ms": 9320.7,
          "lat_all_p50_ms": 7299.3,
          "bw_mbs": 20.032
        },
        {
          "t": "10s-15s",
          "ok": 164,
          "fail": 6,
          "total": 170,
          "success_pct": 96.5,
          "lat_ok_p50_ms": 11320.0,
          "lat_ok_p90_ms": 13992.5,
          "lat_all_p50_ms": 11879.1,
          "bw_mbs": 20.315
        },
        {
          "t": "15s-20s",
          "ok": 19,
          "fail": 2,
          "total": 21,
          "success_pct": 90.5,
          "lat_ok_p50_ms": 16113.9,
          "lat_ok_p90_ms": 18610.8,
          "lat_all_p50_ms": 16093.9,
          "bw_mbs": 1.199
        },
        {
          "t": "20s-25s",
          "ok": 252,
          "fail": 37,
          "total": 289,
          "success_pct": 87.2,
          "lat_ok_p50_ms": 22605.8,
          "lat_ok_p90_ms": 24129.5,
          "lat_all_p50_ms": 22624.2,
          "bw_mbs": 12.509
        },
        {
          "t": "25s-30s",
          "ok": 47,
          "fail": 8,
          "total": 55,
          "success_pct": 85.5,
          "lat_ok_p50_ms": 28103.7,
          "lat_ok_p90_ms": 29713.3,
          "lat_all_p50_ms": 27649.6,
          "bw_mbs": 1.547
        },
        {
          "t": "30s-35s",
          "ok": 73,
          "fail": 5,
          "total": 78,
          "success_pct": 93.6,
          "lat_ok_p50_ms": 32853.5,
          "lat_ok_p90_ms": 34365.5,
          "lat_all_p50_ms": 32949.6,
          "bw_mbs": 4.379
        },
        {
          "t": "35s-40s",
          "ok": 73,
          "fail": 9,
          "total": 82,
          "success_pct": 89.0,
          "lat_ok_p50_ms": 37722.8,
          "lat_ok_p90_ms": 39203.0,
          "lat_all_p50_ms": 37679.2,
          "bw_mbs": 4.081
        },
        {
          "t": "40s-45s",
          "ok": 2,
          "fail": 19,
          "total": 21,
          "success_pct": 9.5,
          "lat_ok_p50_ms": 40138.2,
          "lat_ok_p90_ms": 40138.2,
          "lat_all_p50_ms": 40263.7,
          "bw_mbs": 0.251
        },
        {
          "t": "60s-65s",
          "ok": 0,
          "fail": 1,
          "total": 1,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 62406.4,
          "bw_mbs": 0.0
        }
      ],
      "saturation": {
        "avg_http_time_ms": 14543.8,
        "avg_elapsed_ms": 14543.8,
        "cv_latency": 0.74,
        "peak_active": 1500,
        "peak_active_pct": 100.0,
        "avg_active_connections": 338.1,
        "bottleneck_diagnosis": "proxy saudável — absorveu a carga sem degradação severa"
      },
      "cumulative_error_rate": [
        {
          "at_request": 150,
          "pct_complete": 10.0,
          "error_rate_pct": 15.3
        },
        {
          "at_request": 300,
          "pct_complete": 20.0,
          "error_rate_pct": 12.0
        },
        {
          "at_request": 450,
          "pct_complete": 30.0,
          "error_rate_pct": 11.6
        },
        {
          "at_request": 600,
          "pct_complete": 40.0,
          "error_rate_pct": 11.7
        },
        {
          "at_request": 750,
          "pct_complete": 50.0,
          "error_rate_pct": 11.6
        },
        {
          "at_request": 900,
          "pct_complete": 60.0,
          "error_rate_pct": 12.3
        },
        {
          "at_request": 1050,
          "pct_complete": 70.0,
          "error_rate_pct": 12.9
        },
        {
          "at_request": 1200,
          "pct_complete": 80.0,
          "error_rate_pct": 12.9
        },
        {
          "at_request": 1350,
          "pct_complete": 90.0,
          "error_rate_pct": 12.8
        },
        {
          "at_request": 1500,
          "pct_complete": 100.0,
          "error_rate_pct": 13.3
        }
      ]
    },
    "evomi": {
      "provider": "evomi",
      "concurrency": 1500,
      "total_urls": 1500,
      "total_time_s": 48.2,
      "throughput_per_min": 1867.5,
      "success": 1165,
      "fail": 335,
      "success_rate_pct": 77.7,
      "latency_all_ms": {
        "min": 1765.7,
        "p25": 10981.8,
        "p50": 16041.7,
        "p75": 30074.6,
        "p90": 42000.5,
        "p95": 42026.0,
        "p99": 42062.6,
        "max": 48168.1,
        "avg": 20951.5,
        "stdev": 12605.7
      },
      "latency_ok_ms": {
        "min": 2032.6,
        "p25": 10447.3,
        "p50": 13555.4,
        "p75": 18449.6,
        "p90": 28438.0,
        "p95": 30561.5,
        "p99": 37559.3,
        "max": 39121.1,
        "avg": 15751.3,
        "stdev": 7871.5
      },
      "latency_fail_ms": {
        "min": 1765.7,
        "p25": 40976.4,
        "p50": 41747.3,
        "p75": 42022.8,
        "p90": 42051.3,
        "p95": 42061.8,
        "p99": 42066.5,
        "max": 48168.1,
        "avg": 39036.1,
        "stdev": 8652.8
      },
      "http_time_ms": {
        "min": 1765.7,
        "p25": 10981.8,
        "p50": 16041.7,
        "p75": 30074.6,
        "p90": 42000.5,
        "p95": 42026.0,
        "p99": 42062.6,
        "max": 48168.1,
        "avg": 20951.5,
        "stdev": 12605.7
      },
      "error_breakdown": {
        "timeout": 304,
        "connection": 14,
        "http_404": 7,
        "http_500": 3,
        "http_403": 3,
        "http_502": 1,
        "other": 1,
        "http_530": 1,
        "http_307": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 52402,
        "p50": 123689,
        "p75": 267287,
        "p90": 626895,
        "p95": 1017489,
        "p99": 1968655,
        "max": 7834755,
        "avg": 261795.3,
        "stdev": 471901.9
      },
      "total_data_mb": 304.54,
      "bandwidth_mbps": 50.55,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.0,
        "p50": 1.3,
        "p75": 8.3,
        "p90": 20.5,
        "p95": 30.2,
        "p99": 53.3,
        "max": 53.3,
        "avg": 6.5,
        "stdev": 10.6
      },
      "connections": {
        "peak": 1499,
        "samples": {
          "min": 0,
          "p25": 332,
          "p50": 523,
          "p75": 1026,
          "p90": 1442,
          "p95": 1489,
          "p99": 1500,
          "max": 1500,
          "avg": 652.7,
          "stdev": 478.4
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 8,
          "fail": 4
        },
        "3-6s": {
          "ok": 43,
          "fail": 7
        },
        "6-10s": {
          "ok": 211,
          "fail": 5
        },
        "10-15s": {
          "ok": 444,
          "fail": 3
        },
        "15-20s": {
          "ok": 190,
          "fail": 2
        },
        "20-30s": {
          "ok": 197,
          "fail": 8
        },
        "30-40s": {
          "ok": 72,
          "fail": 2
        },
        "40s+": {
          "ok": 0,
          "fail": 304
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 14,
        "t2_mid_third": 18,
        "t3_last_third": 303
      },
      "degradation_point": "0-3s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 40,
          "fail": 10,
          "total": 50,
          "success_pct": 80.0,
          "lat_ok_p50_ms": 3798.9,
          "lat_ok_p90_ms": 4570.9,
          "lat_all_p50_ms": 3661.8,
          "bw_mbs": 0.159
        },
        {
          "t": "5s-10s",
          "ok": 219,
          "fail": 6,
          "total": 225,
          "success_pct": 97.3,
          "lat_ok_p50_ms": 8278.0,
          "lat_ok_p90_ms": 9629.1,
          "lat_all_p50_ms": 8231.0,
          "bw_mbs": 4.813
        },
        {
          "t": "10s-15s",
          "ok": 437,
          "fail": 2,
          "total": 439,
          "success_pct": 99.5,
          "lat_ok_p50_ms": 12404.9,
          "lat_ok_p90_ms": 14383.4,
          "lat_all_p50_ms": 12406.8,
          "bw_mbs": 17.534
        },
        {
          "t": "15s-20s",
          "ok": 200,
          "fail": 2,
          "total": 202,
          "success_pct": 99.0,
          "lat_ok_p50_ms": 17046.2,
          "lat_ok_p90_ms": 18603.5,
          "lat_all_p50_ms": 17043.7,
          "bw_mbs": 25.112
        },
        {
          "t": "20s-25s",
          "ok": 63,
          "fail": 2,
          "total": 65,
          "success_pct": 96.9,
          "lat_ok_p50_ms": 21791.2,
          "lat_ok_p90_ms": 23396.1,
          "lat_all_p50_ms": 21791.2,
          "bw_mbs": 3.807
        },
        {
          "t": "25s-30s",
          "ok": 129,
          "fail": 7,
          "total": 136,
          "success_pct": 94.9,
          "lat_ok_p50_ms": 27963.1,
          "lat_ok_p90_ms": 29628.9,
          "lat_all_p50_ms": 27970.9,
          "bw_mbs": 6.197
        },
        {
          "t": "30s-35s",
          "ok": 49,
          "fail": 0,
          "total": 49,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 30701.0,
          "lat_ok_p90_ms": 34000.7,
          "lat_all_p50_ms": 30701.0,
          "bw_mbs": 2.368
        },
        {
          "t": "35s-40s",
          "ok": 28,
          "fail": 1,
          "total": 29,
          "success_pct": 96.6,
          "lat_ok_p50_ms": 37345.3,
          "lat_ok_p90_ms": 38031.9,
          "lat_all_p50_ms": 37341.5,
          "bw_mbs": 0.918
        },
        {
          "t": "40s-45s",
          "ok": 0,
          "fail": 304,
          "total": 304,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 41987.7,
          "bw_mbs": 0.0
        },
        {
          "t": "45s-50s",
          "ok": 0,
          "fail": 1,
          "total": 1,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 48168.1,
          "bw_mbs": 0.0
        }
      ],
      "saturation": {
        "avg_http_time_ms": 20951.5,
        "avg_elapsed_ms": 20951.5,
        "cv_latency": 0.602,
        "peak_active": 1500,
        "peak_active_pct": 100.0,
        "avg_active_connections": 652.7,
        "bottleneck_diagnosis": "proxy sob pressão — latência elevada mas ainda funcional"
      },
      "cumulative_error_rate": [
        {
          "at_request": 150,
          "pct_complete": 10.0,
          "error_rate_pct": 4.0
        },
        {
          "at_request": 300,
          "pct_complete": 20.0,
          "error_rate_pct": 2.7
        },
        {
          "at_request": 450,
          "pct_complete": 30.0,
          "error_rate_pct": 2.9
        },
        {
          "at_request": 600,
          "pct_complete": 40.0,
          "error_rate_pct": 3.3
        },
        {
          "at_request": 750,
          "pct_complete": 50.0,
          "error_rate_pct": 3.2
        },
        {
          "at_request": 900,
          "pct_complete": 60.0,
          "error_rate_pct": 3.1
        },
        {
          "at_request": 1050,
          "pct_complete": 70.0,
          "error_rate_pct": 3.1
        },
        {
          "at_request": 1200,
          "pct_complete": 80.0,
          "error_rate_pct": 5.2
        },
        {
          "at_request": 1350,
          "pct_complete": 90.0,
          "error_rate_pct": 15.6
        },
        {
          "at_request": 1500,
          "pct_complete": 100.0,
          "error_rate_pct": 22.3
        }
      ]
    }
  },
  "2000": {
    "711proxy": {
      "provider": "711proxy",
      "concurrency": 2000,
      "total_urls": 2000,
      "total_time_s": 40.7,
      "throughput_per_min": 2951.8,
      "success": 1055,
      "fail": 945,
      "success_rate_pct": 52.8,
      "latency_all_ms": {
        "min": 1541.3,
        "p25": 10185.2,
        "p50": 23798.2,
        "p75": 40294.3,
        "p90": 40400.5,
        "p95": 40436.0,
        "p99": 40462.4,
        "max": 40468.6,
        "avg": 24662.0,
        "stdev": 14783.7
      },
      "latency_ok_ms": {
        "min": 1884.4,
        "p25": 7954.3,
        "p50": 10825.3,
        "p75": 21454.4,
        "p90": 25673.7,
        "p95": 38177.1,
        "p99": 39703.9,
        "max": 40084.4,
        "avg": 14328.0,
        "stdev": 9531.9
      },
      "latency_fail_ms": {
        "min": 1541.3,
        "p25": 40210.1,
        "p50": 40303.9,
        "p75": 40387.8,
        "p90": 40437.7,
        "p95": 40453.1,
        "p99": 40465.7,
        "max": 40468.6,
        "avg": 36199.0,
        "stdev": 10429.8
      },
      "http_time_ms": {
        "min": 1541.3,
        "p25": 10185.2,
        "p50": 23798.2,
        "p75": 40294.3,
        "p90": 40400.5,
        "p95": 40436.0,
        "p99": 40462.4,
        "max": 40468.6,
        "avg": 24662.0,
        "stdev": 14783.7
      },
      "error_breakdown": {
        "timeout": 805,
        "connection": 123,
        "http_403": 7,
        "http_404": 5,
        "http_500": 2,
        "http_530": 1,
        "http_503": 1,
        "http_526": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 38071,
        "p50": 111357,
        "p75": 253752,
        "p90": 590866,
        "p95": 1001439,
        "p99": 1927123,
        "max": 7834755,
        "avg": 243462.2,
        "stdev": 435994.1
      },
      "total_data_mb": 256.71,
      "bandwidth_mbps": 50.52,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.1,
        "p50": 1.8,
        "p75": 9.4,
        "p90": 19.7,
        "p95": 29.9,
        "p99": 51.4,
        "max": 51.4,
        "avg": 6.5,
        "stdev": 10.4
      },
      "connections": {
        "peak": 1999,
        "samples": {
          "min": 0,
          "p25": 905,
          "p50": 1113,
          "p75": 1519,
          "p90": 1925,
          "p95": 1995,
          "p99": 2000,
          "max": 2000,
          "avg": 1212.1,
          "stdev": 412.3
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 20,
          "fail": 9
        },
        "3-6s": {
          "ok": 106,
          "fail": 16
        },
        "6-10s": {
          "ok": 287,
          "fail": 29
        },
        "10-15s": {
          "ok": 336,
          "fail": 64
        },
        "15-20s": {
          "ok": 19,
          "fail": 1
        },
        "20-30s": {
          "ok": 199,
          "fail": 8
        },
        "30-40s": {
          "ok": 86,
          "fail": 13
        },
        "40s+": {
          "ok": 2,
          "fail": 805
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 97,
        "t2_mid_third": 191,
        "t3_last_third": 657
      },
      "degradation_point": "0-3s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 100,
          "fail": 18,
          "total": 118,
          "success_pct": 84.7,
          "lat_ok_p50_ms": 3763.7,
          "lat_ok_p90_ms": 4429.5,
          "lat_all_p50_ms": 3758.0,
          "bw_mbs": 0.7
        },
        {
          "t": "5s-10s",
          "ok": 309,
          "fail": 35,
          "total": 344,
          "success_pct": 89.8,
          "lat_ok_p50_ms": 7919.4,
          "lat_ok_p90_ms": 9415.7,
          "lat_all_p50_ms": 7940.0,
          "bw_mbs": 7.528
        },
        {
          "t": "10s-15s",
          "ok": 340,
          "fail": 65,
          "total": 405,
          "success_pct": 84.0,
          "lat_ok_p50_ms": 11264.2,
          "lat_ok_p90_ms": 13739.0,
          "lat_all_p50_ms": 11263.3,
          "bw_mbs": 26.5
        },
        {
          "t": "15s-20s",
          "ok": 19,
          "fail": 1,
          "total": 20,
          "success_pct": 95.0,
          "lat_ok_p50_ms": 16131.6,
          "lat_ok_p90_ms": 18307.4,
          "lat_all_p50_ms": 16131.6,
          "bw_mbs": 2.738
        },
        {
          "t": "20s-25s",
          "ok": 157,
          "fail": 6,
          "total": 163,
          "success_pct": 96.3,
          "lat_ok_p50_ms": 23363.5,
          "lat_ok_p90_ms": 24549.4,
          "lat_all_p50_ms": 23331.3,
          "bw_mbs": 4.485
        },
        {
          "t": "25s-30s",
          "ok": 42,
          "fail": 2,
          "total": 44,
          "success_pct": 95.5,
          "lat_ok_p50_ms": 25418.5,
          "lat_ok_p90_ms": 26929.1,
          "lat_all_p50_ms": 25592.4,
          "bw_mbs": 5.022
        },
        {
          "t": "30s-35s",
          "ok": 8,
          "fail": 7,
          "total": 15,
          "success_pct": 53.3,
          "lat_ok_p50_ms": 31735.7,
          "lat_ok_p90_ms": 33159.0,
          "lat_all_p50_ms": 31932.7,
          "bw_mbs": 0.482
        },
        {
          "t": "35s-40s",
          "ok": 76,
          "fail": 6,
          "total": 82,
          "success_pct": 92.7,
          "lat_ok_p50_ms": 39241.7,
          "lat_ok_p90_ms": 39652.8,
          "lat_all_p50_ms": 39241.5,
          "bw_mbs": 3.807
        },
        {
          "t": "40s-45s",
          "ok": 4,
          "fail": 805,
          "total": 809,
          "success_pct": 0.5,
          "lat_ok_p50_ms": 40061.9,
          "lat_ok_p90_ms": 40084.4,
          "lat_all_p50_ms": 40327.8,
          "bw_mbs": 0.08
        }
      ],
      "saturation": {
        "avg_http_time_ms": 24662.0,
        "avg_elapsed_ms": 24662.0,
        "cv_latency": 0.599,
        "peak_active": 2000,
        "peak_active_pct": 100.0,
        "avg_active_connections": 1212.1,
        "bottleneck_diagnosis": "proxy sob pressão — latência elevada mas ainda funcional"
      },
      "cumulative_error_rate": [
        {
          "at_request": 200,
          "pct_complete": 10.0,
          "error_rate_pct": 14.5
        },
        {
          "at_request": 400,
          "pct_complete": 20.0,
          "error_rate_pct": 14.8
        },
        {
          "at_request": 600,
          "pct_complete": 30.0,
          "error_rate_pct": 14.5
        },
        {
          "at_request": 800,
          "pct_complete": 40.0,
          "error_rate_pct": 15.0
        },
        {
          "at_request": 1000,
          "pct_complete": 50.0,
          "error_rate_pct": 14.6
        },
        {
          "at_request": 1200,
          "pct_complete": 60.0,
          "error_rate_pct": 14.8
        },
        {
          "at_request": 1400,
          "pct_complete": 70.0,
          "error_rate_pct": 25.4
        },
        {
          "at_request": 1600,
          "pct_complete": 80.0,
          "error_rate_pct": 34.3
        },
        {
          "at_request": 1800,
          "pct_complete": 90.0,
          "error_rate_pct": 41.5
        },
        {
          "at_request": 2000,
          "pct_complete": 100.0,
          "error_rate_pct": 47.2
        }
      ]
    },
    "decodo": {
      "provider": "decodo",
      "concurrency": 2000,
      "total_urls": 2000,
      "total_time_s": 41.0,
      "throughput_per_min": 2929.4,
      "success": 1272,
      "fail": 728,
      "success_rate_pct": 63.6,
      "latency_all_ms": {
        "min": 2066.3,
        "p25": 10789.2,
        "p50": 22739.4,
        "p75": 40370.1,
        "p90": 40481.2,
        "p95": 40524.2,
        "p99": 40552.9,
        "max": 40762.7,
        "avg": 23303.4,
        "stdev": 13535.2
      },
      "latency_ok_ms": {
        "min": 2527.5,
        "p25": 9665.8,
        "p50": 13648.2,
        "p75": 23490.3,
        "p90": 31022.6,
        "p95": 35470.9,
        "p99": 39394.8,
        "max": 40275.3,
        "avg": 16436.2,
        "stdev": 9085.9
      },
      "latency_fail_ms": {
        "min": 2066.3,
        "p25": 40341.9,
        "p50": 40427.0,
        "p75": 40487.2,
        "p90": 40533.9,
        "p95": 40547.1,
        "p99": 40557.2,
        "max": 40762.7,
        "avg": 35302.2,
        "stdev": 11521.0
      },
      "http_time_ms": {
        "min": 2066.3,
        "p25": 10789.2,
        "p50": 22739.4,
        "p75": 40370.1,
        "p90": 40481.2,
        "p95": 40524.2,
        "p99": 40552.9,
        "max": 40762.7,
        "avg": 23303.4,
        "stdev": 13535.2
      },
      "error_breakdown": {
        "timeout": 585,
        "connection": 114,
        "http_522": 9,
        "http_404": 6,
        "other": 4,
        "http_403": 3,
        "ssl": 2,
        "http_502": 2,
        "http_503": 1,
        "http_307": 1,
        "http_500": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 51303,
        "p50": 124540,
        "p75": 260221,
        "p90": 619588,
        "p95": 1052460,
        "p99": 2004691,
        "max": 7834761,
        "avg": 265217.6,
        "stdev": 480047.7
      },
      "total_data_mb": 337.18,
      "bandwidth_mbps": 65.85,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 1.0,
        "p50": 4.8,
        "p75": 12.1,
        "p90": 27.0,
        "p95": 31.1,
        "p99": 57.0,
        "max": 57.0,
        "avg": 8.4,
        "stdev": 10.6
      },
      "connections": {
        "peak": 1999,
        "samples": {
          "min": 0,
          "p25": 739,
          "p50": 1050,
          "p75": 1533,
          "p90": 1921,
          "p95": 1983,
          "p99": 2000,
          "max": 2000,
          "avg": 1115.7,
          "stdev": 493.8
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 2,
          "fail": 21
        },
        "3-6s": {
          "ok": 102,
          "fail": 10
        },
        "6-10s": {
          "ok": 244,
          "fail": 47
        },
        "10-15s": {
          "ok": 394,
          "fail": 12
        },
        "15-20s": {
          "ok": 112,
          "fail": 4
        },
        "20-30s": {
          "ok": 274,
          "fail": 30
        },
        "30-40s": {
          "ok": 139,
          "fail": 18
        },
        "40s+": {
          "ok": 5,
          "fail": 586
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 64,
        "t2_mid_third": 162,
        "t3_last_third": 502
      },
      "degradation_point": "0-3s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 80,
          "fail": 27,
          "total": 107,
          "success_pct": 74.8,
          "lat_ok_p50_ms": 4282.2,
          "lat_ok_p90_ms": 4746.2,
          "lat_all_p50_ms": 3980.6,
          "bw_mbs": 0.764
        },
        {
          "t": "5s-10s",
          "ok": 261,
          "fail": 51,
          "total": 312,
          "success_pct": 83.7,
          "lat_ok_p50_ms": 8346.3,
          "lat_ok_p90_ms": 9638.0,
          "lat_all_p50_ms": 8104.0,
          "bw_mbs": 6.687
        },
        {
          "t": "10s-15s",
          "ok": 385,
          "fail": 12,
          "total": 397,
          "success_pct": 97.0,
          "lat_ok_p50_ms": 12477.7,
          "lat_ok_p90_ms": 14741.2,
          "lat_all_p50_ms": 12558.1,
          "bw_mbs": 21.051
        },
        {
          "t": "15s-20s",
          "ok": 128,
          "fail": 4,
          "total": 132,
          "success_pct": 97.0,
          "lat_ok_p50_ms": 16053.4,
          "lat_ok_p90_ms": 18077.2,
          "lat_all_p50_ms": 16054.5,
          "bw_mbs": 14.886
        },
        {
          "t": "20s-25s",
          "ok": 198,
          "fail": 25,
          "total": 223,
          "success_pct": 88.8,
          "lat_ok_p50_ms": 23488.5,
          "lat_ok_p90_ms": 24489.4,
          "lat_all_p50_ms": 23490.4,
          "bw_mbs": 10.98
        },
        {
          "t": "25s-30s",
          "ok": 76,
          "fail": 5,
          "total": 81,
          "success_pct": 93.8,
          "lat_ok_p50_ms": 25753.1,
          "lat_ok_p90_ms": 28113.1,
          "lat_all_p50_ms": 25779.7,
          "bw_mbs": 4.106
        },
        {
          "t": "30s-35s",
          "ok": 76,
          "fail": 10,
          "total": 86,
          "success_pct": 88.4,
          "lat_ok_p50_ms": 31811.3,
          "lat_ok_p90_ms": 34051.1,
          "lat_all_p50_ms": 32040.0,
          "bw_mbs": 3.244
        },
        {
          "t": "35s-40s",
          "ok": 61,
          "fail": 8,
          "total": 69,
          "success_pct": 88.4,
          "lat_ok_p50_ms": 37231.8,
          "lat_ok_p90_ms": 39312.5,
          "lat_all_p50_ms": 37231.8,
          "bw_mbs": 5.506
        },
        {
          "t": "40s-45s",
          "ok": 7,
          "fail": 586,
          "total": 593,
          "success_pct": 1.2,
          "lat_ok_p50_ms": 40200.9,
          "lat_ok_p90_ms": 40275.3,
          "lat_all_p50_ms": 40452.6,
          "bw_mbs": 0.21
        }
      ],
      "saturation": {
        "avg_http_time_ms": 23303.4,
        "avg_elapsed_ms": 23303.4,
        "cv_latency": 0.581,
        "peak_active": 2000,
        "peak_active_pct": 100.0,
        "avg_active_connections": 1115.7,
        "bottleneck_diagnosis": "proxy sob pressão — latência elevada mas ainda funcional"
      },
      "cumulative_error_rate": [
        {
          "at_request": 200,
          "pct_complete": 10.0,
          "error_rate_pct": 9.0
        },
        {
          "at_request": 400,
          "pct_complete": 20.0,
          "error_rate_pct": 9.0
        },
        {
          "at_request": 600,
          "pct_complete": 30.0,
          "error_rate_pct": 9.7
        },
        {
          "at_request": 800,
          "pct_complete": 40.0,
          "error_rate_pct": 10.4
        },
        {
          "at_request": 1000,
          "pct_complete": 50.0,
          "error_rate_pct": 10.5
        },
        {
          "at_request": 1200,
          "pct_complete": 60.0,
          "error_rate_pct": 10.5
        },
        {
          "at_request": 1400,
          "pct_complete": 70.0,
          "error_rate_pct": 20.6
        },
        {
          "at_request": 1600,
          "pct_complete": 80.0,
          "error_rate_pct": 29.7
        },
        {
          "at_request": 1800,
          "pct_complete": 90.0,
          "error_rate_pct": 31.6
        },
        {
          "at_request": 2000,
          "pct_complete": 100.0,
          "error_rate_pct": 36.4
        }
      ]
    },
    "evomi": {
      "provider": "evomi",
      "concurrency": 2000,
      "total_urls": 2000,
      "total_time_s": 40.8,
      "throughput_per_min": 2941.5,
      "success": 1141,
      "fail": 859,
      "success_rate_pct": 57.0,
      "latency_all_ms": {
        "min": 3292.6,
        "p25": 14017.1,
        "p50": 25219.0,
        "p75": 40378.5,
        "p90": 40498.1,
        "p95": 40535.6,
        "p99": 40566.0,
        "max": 40572.5,
        "avg": 26588.1,
        "stdev": 12692.5
      },
      "latency_ok_ms": {
        "min": 3519.0,
        "p25": 12119.1,
        "p50": 15429.2,
        "p75": 21754.6,
        "p90": 29283.5,
        "p95": 31003.0,
        "p99": 37435.3,
        "max": 39773.7,
        "avg": 17405.1,
        "stdev": 7339.6
      },
      "latency_fail_ms": {
        "min": 3292.6,
        "p25": 40324.5,
        "p50": 40409.6,
        "p75": 40492.4,
        "p90": 40540.8,
        "p95": 40557.7,
        "p99": 40569.7,
        "max": 40572.5,
        "avg": 38785.8,
        "stdev": 6531.5
      },
      "http_time_ms": {
        "min": 3292.6,
        "p25": 14017.1,
        "p50": 25219.0,
        "p75": 40378.5,
        "p90": 40498.1,
        "p95": 40535.6,
        "p99": 40566.0,
        "max": 40572.5,
        "avg": 26588.1,
        "stdev": 12692.5
      },
      "error_breakdown": {
        "timeout": 803,
        "connection": 37,
        "http_404": 6,
        "http_500": 5,
        "http_403": 2,
        "http_504": 1,
        "http_526": 1,
        "ssl": 1,
        "http_307": 1,
        "other": 1,
        "http_530": 1
      },
      "content_size_bytes": {
        "min": 151,
        "p25": 46416,
        "p50": 120168,
        "p75": 248318,
        "p90": 625982,
        "p95": 1005938,
        "p99": 2013588,
        "max": 10784560,
        "avg": 266598.6,
        "stdev": 570389.6
      },
      "total_data_mb": 303.99,
      "bandwidth_mbps": 59.61,
      "bandwidth_series_mbs": {
        "min": 0.0,
        "p25": 0.3,
        "p50": 3.3,
        "p75": 11.1,
        "p90": 22.2,
        "p95": 28.1,
        "p99": 57.4,
        "max": 57.4,
        "avg": 7.6,
        "stdev": 10.7
      },
      "connections": {
        "peak": 1999,
        "samples": {
          "min": 0,
          "p25": 869,
          "p50": 1159,
          "p75": 1849,
          "p90": 1984,
          "p95": 2000,
          "p99": 2000,
          "max": 2000,
          "avg": 1296.8,
          "stdev": 476.4
        }
      },
      "time_histogram": {
        "0-3s": {
          "ok": 0,
          "fail": 0
        },
        "3-6s": {
          "ok": 19,
          "fail": 8
        },
        "6-10s": {
          "ok": 117,
          "fail": 6
        },
        "10-15s": {
          "ok": 406,
          "fail": 19
        },
        "15-20s": {
          "ok": 247,
          "fail": 8
        },
        "20-30s": {
          "ok": 277,
          "fail": 11
        },
        "30-40s": {
          "ok": 75,
          "fail": 4
        },
        "40s+": {
          "ok": 0,
          "fail": 803
        }
      },
      "error_distribution_thirds": {
        "t1_first_third": 39,
        "t2_mid_third": 265,
        "t3_last_third": 555
      },
      "degradation_point": "3-6s",
      "timeline_5s": [
        {
          "t": "0s-5s",
          "ok": 11,
          "fail": 7,
          "total": 18,
          "success_pct": 61.1,
          "lat_ok_p50_ms": 3792.6,
          "lat_ok_p90_ms": 3976.8,
          "lat_all_p50_ms": 3591.4,
          "bw_mbs": 0.013
        },
        {
          "t": "5s-10s",
          "ok": 118,
          "fail": 7,
          "total": 125,
          "success_pct": 94.4,
          "lat_ok_p50_ms": 8661.3,
          "lat_ok_p90_ms": 9787.3,
          "lat_all_p50_ms": 8654.1,
          "bw_mbs": 2.249
        },
        {
          "t": "10s-15s",
          "ok": 407,
          "fail": 19,
          "total": 426,
          "success_pct": 95.5,
          "lat_ok_p50_ms": 12492.2,
          "lat_ok_p90_ms": 14213.6,
          "lat_all_p50_ms": 12518.2,
          "bw_mbs": 13.12
        },
        {
          "t": "15s-20s",
          "ok": 243,
          "fail": 8,
          "total": 251,
          "success_pct": 96.8,
          "lat_ok_p50_ms": 17515.5,
          "lat_ok_p90_ms": 19452.1,
          "lat_all_p50_ms": 17568.5,
          "bw_mbs": 20.333
        },
        {
          "t": "20s-25s",
          "ok": 166,
          "fail": 5,
          "total": 171,
          "success_pct": 97.1,
          "lat_ok_p50_ms": 21871.5,
          "lat_ok_p90_ms": 24126.5,
          "lat_all_p50_ms": 21864.1,
          "bw_mbs": 16.593
        },
        {
          "t": "25s-30s",
          "ok": 110,
          "fail": 6,
          "total": 116,
          "success_pct": 94.8,
          "lat_ok_p50_ms": 28280.2,
          "lat_ok_p90_ms": 29580.1,
          "lat_all_p50_ms": 28280.2,
          "bw_mbs": 5.29
        },
        {
          "t": "30s-35s",
          "ok": 67,
          "fail": 4,
          "total": 71,
          "success_pct": 94.4,
          "lat_ok_p50_ms": 31367.8,
          "lat_ok_p90_ms": 34121.5,
          "lat_all_p50_ms": 31146.1,
          "bw_mbs": 2.611
        },
        {
          "t": "35s-40s",
          "ok": 19,
          "fail": 0,
          "total": 19,
          "success_pct": 100.0,
          "lat_ok_p50_ms": 37678.3,
          "lat_ok_p90_ms": 38959.4,
          "lat_all_p50_ms": 37678.3,
          "bw_mbs": 0.589
        },
        {
          "t": "40s-45s",
          "ok": 0,
          "fail": 803,
          "total": 803,
          "success_pct": 0.0,
          "lat_ok_p50_ms": 0,
          "lat_ok_p90_ms": 0,
          "lat_all_p50_ms": 40418.2,
          "bw_mbs": 0.0
        }
      ],
      "saturation": {
        "avg_http_time_ms": 26588.1,
        "avg_elapsed_ms": 26588.1,
        "cv_latency": 0.477,
        "peak_active": 2000,
        "peak_active_pct": 100.0,
        "avg_active_connections": 1296.8,
        "bottleneck_diagnosis": "proxy lento — latência média alta; bandwidth ou capacidade do proxy esgotada"
      },
      "cumulative_error_rate": [
        {
          "at_request": 200,
          "pct_complete": 10.0,
          "error_rate_pct": 4.0
        },
        {
          "at_request": 400,
          "pct_complete": 20.0,
          "error_rate_pct": 4.0
        },
        {
          "at_request": 600,
          "pct_complete": 30.0,
          "error_rate_pct": 6.0
        },
        {
          "at_request": 800,
          "pct_complete": 40.0,
          "error_rate_pct": 5.8
        },
        {
          "at_request": 1000,
          "pct_complete": 50.0,
          "error_rate_pct": 5.9
        },
        {
          "at_request": 1200,
          "pct_complete": 60.0,
          "error_rate_pct": 14.8
        },
        {
          "at_request": 1400,
          "pct_complete": 70.0,
          "error_rate_pct": 25.9
        },
        {
          "at_request": 1600,
          "pct_complete": 80.0,
          "error_rate_pct": 30.1
        },
        {
          "at_request": 1800,
          "pct_complete": 90.0,
          "error_rate_pct": 37.3
        },
        {
          "at_request": 2000,
          "pct_complete": 100.0,
          "error_rate_pct": 43.0
        }
      ]
    }
  }
}
```