# SGLang + Qwen2.5-3B-Instruct: Guia de Configuração e Otimização

Este documento analisa as configurações do servidor SGLang com o modelo Qwen/Qwen2.5-3B-Instruct e fornece recomendações de otimização para o Profile Builder.

---

## 📋 Índice

1. [Configuração Atual do Servidor](#1-configuração-atual-do-servidor)
2. [Parâmetros Críticos para Performance](#2-parâmetros-críticos-para-performance)
3. [Parâmetros de Structured Output (XGrammar)](#3-parâmetros-de-structured-output-xgrammar)
4. [Parâmetros de Memória e Batching](#4-parâmetros-de-memória-e-batching)
5. [Configuração do Profile Builder](#5-configuração-do-profile-builder)
6. [Recomendações de Otimização](#6-recomendações-de-otimização)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Configuração Atual do Servidor

### ServerArgs Completo (Extraído dos Logs)

```
model_path='Qwen/Qwen2.5-3B-Instruct'
context_length=32768
chunked_prefill_size=8192
max_prefill_tokens=16384
grammar_backend='xgrammar'
attention_backend='flashinfer'
sampling_backend='flashinfer'
mem_fraction_static=0.836
dtype='auto'
port=8000
```

---

## 2. Parâmetros Críticos para Performance

### 2.1 `context_length` (32768)

| Aspecto | Descrição |
|---------|-----------|
| **O que é** | Tamanho máximo da janela de contexto do modelo |
| **Valor atual** | 32.768 tokens |
| **Por que importa** | Define o tamanho máximo de entrada + saída combinados |
| **Impacto** | ↑ permite entradas maiores; ↓ economiza memória |

**Recomendação para Profile Builder:**
- Manter em 32768 (padrão do Qwen2.5-3B)
- Nosso `max_chunk_tokens` (12000) + `max_output_tokens` (4096) = 16k, bem abaixo do limite

### 2.2 `chunked_prefill_size` (8192)

| Aspecto | Descrição |
|---------|-----------|
| **O que é** | Tamanho máximo de tokens processados em cada chunk durante prefill |
| **Valor atual** | 8192 tokens |
| **Por que importa** | Controla uso de memória durante geração de KV cache |
| **Trade-off** | ↑ maior throughput para prompts longos; ↓ menor pico de memória |

**Recomendação:**
```bash
# Para GPU com 24GB (RTX 4090/A10):
--chunked-prefill-size 4096

# Para GPU com 16GB ou menos:
--chunked-prefill-size 2048

# Para GPU com 40GB+:
--chunked-prefill-size 8192  # (atual)
```

### 2.3 `max_prefill_tokens` (16384)

| Aspecto | Descrição |
|---------|-----------|
| **O que é** | Máximo de tokens em um batch de prefill |
| **Valor atual** | 16384 tokens |
| **Por que importa** | Limita pico de memória em requests concorrentes |

**Recomendação:**
- Para profile builder (requests grandes, baixa concorrência): pode aumentar para 24576
- Para alta concorrência: manter em 16384 ou reduzir para 8192

### 2.4 `mem_fraction_static` (0.836)

| Aspecto | Descrição |
|---------|-----------|
| **O que é** | Fração da VRAM alocada estaticamente (weights + KV cache pool) |
| **Valor atual** | 83.6% |
| **Por que importa** | Restante é para ativações dinâmicas |
| **Trade-off** | ↑ mais KV cache (throughput); ↓ mais margem para picos |

**Recomendação por GPU:**
```bash
# GPU com memória apertada (16GB):
--mem-fraction-static 0.75

# GPU confortável (24GB):
--mem-fraction-static 0.83  # (atual ok)

# GPU com folga (40GB+):
--mem-fraction-static 0.88
```

---

## 3. Parâmetros de Structured Output (XGrammar)

### 3.1 `grammar_backend` (xgrammar)

| Aspecto | Descrição |
|---------|-----------|
| **O que é** | Backend para geração estruturada |
| **Opções** | `xgrammar` (default), `outlines`, `llguidance`, `none` |
| **Por que importa** | Garante JSON válido durante geração |

**Comparação de Backends:**

| Backend | Velocidade | JSON Schema | Regex | EBNF |
|---------|------------|-------------|-------|------|
| **xgrammar** | ⚡ Mais rápido | ✅ | ✅ | ✅ |
| outlines | 🐢 Mais lento | ✅ | ✅ | ❌ |
| llguidance | 🐢 Médio | ✅ | ✅ | ✅ |

**Recomendação:** Manter `xgrammar` (já é o default e mais performático)

### 3.2 `constrained_json_whitespace_pattern` (None)

| Aspecto | Descrição |
|---------|-----------|
| **O que é** | Padrão regex para whitespace permitido no JSON |
| **Valor atual** | None (usa padrão) |
| **Por que importa** | Controla formatação do JSON gerado |

**Opções:**
```bash
# JSON compacto (sem espaços extras):
--constrained-json-disable-any-whitespace

# JSON com formatação mínima:
--constrained-json-whitespace-pattern "[\n\t ]*"
```

**Recomendação para Profile Builder:**
- Adicionar `--constrained-json-disable-any-whitespace` para JSON mais compacto
- Reduz tokens de saída em ~10-15%

### 3.3 Como Usar Structured Output no Cliente

```python
# No provider_manager.py, o response_format é enviado assim:
response_format = {
    "type": "json_schema",
    "json_schema": {
        "name": "company_profile_extraction",
        "schema": CompanyProfile.model_json_schema()  # ~9000 chars
    }
}
```

---

## 4. Parâmetros de Memória e Batching

### 4.1 `cuda_graph_max_bs` (256)

| Aspecto | Descrição |
|---------|-----------|
| **O que é** | Batch size máximo para CUDA graphs |
| **Valor atual** | 256 |
| **Por que importa** | CUDA graphs aceleram decode eliminando overhead de kernel launch |

**Recomendação:**
- Para uso com Profile Builder (baixa concorrência): `--cuda-graph-max-bs 32`
- Reduz memória usada por graphs pré-capturados

### 4.2 `max_running_requests` (Auto)

| Aspecto | Descrição |
|---------|-----------|
| **O que é** | Número máximo de requests rodando simultaneamente |
| **Valor atual** | Auto (baseado na memória) |
| **Por que importa** | Controla concorrência e latência |

**Recomendação para Profile Builder:**
```bash
# Limitar para reduzir latência e garantir qualidade:
--max-running-requests 8
```

### 4.3 `schedule_policy` (fcfs)

| Opção | Descrição |
|-------|-----------|
| **fcfs** | First Come First Serve (padrão) |
| lpm | Longest Prefix Match (melhor cache hit) |
| random | Aleatório |

**Recomendação:** Manter `fcfs` para Profile Builder

---

## 5. Configuração do Profile Builder

### 5.1 Configuração Atual (`profile_llm.json`)

```json
{
  "max_chunk_tokens": 12000,
  "system_prompt_overhead": 3000,
  "group_target_tokens": 8000,
  "use_structured_output": true,
  "structured_output_backend": "xgrammar",
  "recommended_temperature": 0.0
}
```

### 5.2 Análise de Alinhamento

| Parâmetro | Profile Builder | SGLang Server | Status |
|-----------|-----------------|---------------|--------|
| Context | 12k + 3k = 15k | 32k | ✅ OK (47% usado) |
| Temperature | 0.0 | - | ✅ Determinístico |
| Structured Output | json_schema | xgrammar | ✅ Alinhado |
| Max Output | 4096 (llm_limits) | - | ✅ OK |

### 5.3 Configuração Recomendada do Servidor para Profile Builder

```bash
python -m sglang.launch_server \
    --model-path Qwen/Qwen2.5-3B-Instruct \
    --port 8000 \
    --host 0.0.0.0 \
    --context-length 32768 \
    --chunked-prefill-size 8192 \
    --max-prefill-tokens 16384 \
    --grammar-backend xgrammar \
    --constrained-json-disable-any-whitespace \
    --max-running-requests 16 \
    --mem-fraction-static 0.83 \
    --cuda-graph-max-bs 64 \
    --log-level info
```

---

## 6. Recomendações de Otimização

### 6.1 Otimização de Latência (Priorizar TTFT)

```bash
# Adicionar ao comando de launch:
--schedule-policy fcfs \
--disable-radix-cache \           # Se não houver reuso de prefix
--chunked-prefill-size 4096       # Chunks menores = TTFT mais rápido
```

**Impacto:** ↓ TTFT em ~20-30%, ↑ throughput em ~5%

### 6.2 Otimização de Throughput (Priorizar Requests/s)

```bash
# Adicionar ao comando de launch:
--enable-mixed-chunk \
--chunked-prefill-size 16384 \    # Chunks maiores
--max-running-requests 32 \       # Mais concorrência
--mem-fraction-static 0.88        # Mais KV cache
```

**Impacto:** ↑ throughput em ~40%, ↑ latência em ~15%

### 6.3 Otimização de Qualidade (Priorizar JSON Válido)

```bash
# Adicionar ao comando de launch:
--grammar-backend xgrammar \
--constrained-json-disable-any-whitespace
```

**No cliente (profile_llm.json):**
```json
{
  "recommended_temperature": 0.0,
  "use_structured_output": true,
  "structured_output_backend": "xgrammar"
}
```

### 6.4 Otimização de Memória (GPU com 16GB)

```bash
python -m sglang.launch_server \
    --model-path Qwen/Qwen2.5-3B-Instruct \
    --mem-fraction-static 0.75 \
    --chunked-prefill-size 2048 \
    --max-prefill-tokens 8192 \
    --cuda-graph-max-bs 16 \
    --max-running-requests 4
```

---

## 7. Troubleshooting

### 7.1 Erro: "404 page not found"

**Causa:** Pod do RunPod não está rodando ou endpoint mudou.

**Solução:**
1. Verificar se o pod está ativo no dashboard RunPod
2. Verificar URL do proxy (muda após restart)
3. Atualizar `VLLM_ENDPOINT` no `.env`

```bash
# Testar endpoint:
curl https://SEU-POD-ID.proxy.runpod.net/v1/models
```

### 7.2 Erro: "Out of Memory"

**Causa:** Memória insuficiente para o batch atual.

**Solução:**
```bash
# Reduzir alocação estática:
--mem-fraction-static 0.75

# Reduzir tamanho de chunk:
--chunked-prefill-size 2048

# Limitar concorrência:
--max-running-requests 4
```

### 7.3 JSON Inválido Apesar de Structured Output

**Causa:** Schema muito complexo ou modelo não seguiu corretamente.

**Soluções:**
1. Verificar se `grammar_backend` é `xgrammar`
2. Usar `temperature: 0.0` para output determinístico
3. Simplificar schema se necessário
4. Verificar logs do servidor para erros de grammar

```bash
# No servidor:
--log-level debug
```

### 7.4 Latência Alta em Prompts Longos

**Causa:** Prefill está sendo fragmentado demais.

**Solução:**
```bash
# Aumentar tamanho de chunk:
--chunked-prefill-size 16384 \
--max-prefill-tokens 32768
```

---

## 📊 Matriz de Configuração por Cenário

| Cenário | mem_fraction | chunk_prefill | max_requests | cuda_graph_bs |
|---------|--------------|---------------|--------------|---------------|
| **Dev (16GB GPU)** | 0.75 | 2048 | 4 | 16 |
| **Prod Balanceado** | 0.83 | 8192 | 16 | 64 |
| **Alta Concorrência** | 0.88 | 4096 | 32 | 128 |
| **Baixa Latência** | 0.80 | 4096 | 8 | 32 |
| **Prompts Longos** | 0.85 | 16384 | 8 | 64 |

---

## 📝 Checklist de Deploy

- [ ] Pod SGLang rodando no RunPod
- [ ] Endpoint testado com `curl /v1/models`
- [ ] `VLLM_ENDPOINT` configurado no `.env`
- [ ] `VLLM_MODEL` = `Qwen/Qwen2.5-3B-Instruct`
- [ ] `profile_llm.json` com `use_structured_output: true`
- [ ] `llm_limits.json` com `supports_structured_output: true`
- [ ] Temperature = 0.0 para JSON determinístico

---

## 🔗 Referências

- [SGLang Documentation](https://docs.sglang.ai/)
- [Qwen Deployment Guide](https://qwen.readthedocs.io/en/latest/deployment/sglang.html)
- [XGrammar Paper](https://arxiv.org/abs/2411.15100)
- [SGLang ServerArgs Source](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/server_args.py)

