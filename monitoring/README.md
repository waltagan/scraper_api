# Monitoring do Endpoint Unificado

## Prometheus

- Arquivo de scrape: `monitoring/prometheus/prometheus.yml`
- Intervalo: 1 segundo (séries temporais finas para detectar exaustão de proxy).
- Endpoint alvo: `GET /metrics`.

## Grafana Dashboard

- Dashboard: `monitoring/grafana/dashboards/scrape_unified_dashboard.json`
- Painéis:
  - throughput por provider e etapa,
  - erros por provider/etapa/tipo,
  - taxa de sucesso da etapa 1 por provider,
  - latência p50/p90/p99 por etapa/provider e tempo total por empresa,
  - backlog/fila de persistência,
  - latência e tamanho do flush no banco,
  - duração do run batch por modo (`checkpoint`/`final_only`),
  - saturação do servidor (CPU, memória RSS, FD, event loop lag, load),
  - saturação HTTP (inflight e p95 por rota).

## Alertas recomendados

- Queda de sucesso por provider:
  - `sum(rate(scrape_unified_requests_total{status="success"}[2m])) / sum(rate(scrape_unified_requests_total[2m])) < 0.7`
- Timeout/erro em alta:
  - `sum(rate(scrape_unified_errors_total{error_type=~"TimeoutError|ReadTimeout|ConnectTimeout"}[2m])) > 5`
- Saturação:
  - `max(scrape_unified_inflight_requests) > 1100` por provider/etapa (ajustar ao cap operacional real).
- Event loop degradado:
  - `avg_over_time(scrape_server_event_loop_lag_seconds[2m]) > 0.05`
- CPU sustentada:
  - `avg_over_time(scrape_server_cpu_percent[5m]) > 85`
