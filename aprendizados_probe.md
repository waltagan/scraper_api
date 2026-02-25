# Aprendizados do Probe

## Contexto

Comparamos o comportamento do caminho de `probe_only` com um caminho de `stress_direct` usando:

- mesma amostra de URLs (`sample_id` fixo),
- mesma concorrência (3200),
- mesmo timeout (40s),
- mesmo ambiente (Railway).

## Resultado A/B observado

- `stress_direct`:
  - sucesso: 91.4%
  - tempo total: 41.4s
  - throughput: 4521.3 empresas/min
- `probe_only`:
  - sucesso: 37.0%
  - tempo total: 110.2s
  - throughput: 1698.5 empresas/min

Conclusão: o problema principal está no fluxo de probe atual, não na máquina do Railway.

## Causas prováveis já validadas

1. Fila em semáforos no caminho de probe
- O probe passa por semáforo de provider e semáforo por proxy.
- Sob carga alta, cresce o tempo de espera por slot, elevando latência efetiva e timeout.

2. Estratégia de proxy mais instável no probe_only
- `probe_only` usa `proxy_pool` (round-robin em 711/Decodo/Evomi).
- No período do teste, 711 e Decodo estavam significativamente piores que Evomi.
- Isso derruba o sucesso global do probe.

3. Critério de sucesso mais rígido no fluxo do probe
- O caminho do probe reprova status não-200.
- O stress direto aceita respostas 2xx/3xx com conteúdo.
- Esse detalhe aumenta a diferença de sucesso entre os dois testes.

4. Tentativa extra de `www` em casos de DNS
- Em parte das URLs, o probe faz fallback para `www`.
- Em cenário congestionado, isso aumenta custo/latência por URL.

## Evidências dos últimos runs de pipeline

- Em run com 3600 empresas:
  - sucesso final: 21.9%
  - falhas de probe: 2756
  - `probe:timeout`: 2553
- Em run com 1000 empresas:
  - sucesso final: 41.7%
  - falhas de probe: 568
  - `probe:timeout`: 435

Conclusão operacional: a falha dominante segue sendo `proxy_infra` na etapa de probe.

## Implicações para o próximo redesign

- Não assumir que "mais slots" melhora resultado no probe.
- Separar claramente:
  - teste de capacidade de transporte (stress direto),
  - teste de confiabilidade do fluxo de probe real.
- Medir explicitamente tempo em fila de semáforos e taxa por provider.
- Priorizar caminhos/proxies com melhor taxa de sucesso antes de escalar concorrência global.
