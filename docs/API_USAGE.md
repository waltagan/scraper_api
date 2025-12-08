# 📡 Guia de Uso da API - B2B Flash Profiler

## Endpoint Principal

```
POST /analyze
```

### Autenticação

Requer header de API key:
```
Authorization: Bearer <sua-api-key>
```

---

## 📋 Parâmetros do Request

### Estrutura do Body (JSON)

```json
{
    "url": "https://exemplo.com.br",
    "razao_social": "Empresa Exemplo LTDA",
    "nome_fantasia": "Exemplo Corp",
    "cnpj": "12.345.678/0001-90",
    "email": "contato@exemplo.com.br",
    "municipio": "São Paulo",
    "cnaes": ["4751201", "4752100"]
}
```

### Campos Obrigatórios vs Opcionais

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `url` | string (URL) | ⚠️ Condicional* | URL direta do site da empresa |
| `razao_social` | string | ⚠️ Condicional* | Razão social da empresa |
| `nome_fantasia` | string | ⚠️ Condicional* | Nome fantasia da empresa |
| `cnpj` | string | ❌ Opcional | CNPJ formatado ou não |
| `email` | string | ❌ Opcional | Email de contato |
| `municipio` | string | ❌ Opcional | Cidade da empresa |
| `cnaes` | array[string] | ❌ Opcional | Lista de CNAEs |

> ⚠️ **Condicional**: Você deve fornecer **OU** a `url` diretamente **OU** ao menos um dos campos (`razao_social`, `nome_fantasia`, `cnpj`) para que a API faça o discovery automático.

---

## 🚀 Exemplos de Chamada

### 1. Com URL Direta (mais rápido)

Se você já sabe o site da empresa:

```bash
curl -X POST "http://localhost:8000/analyze" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sua-api-key" \
  -d '{
    "url": "https://www.magazineluiza.com.br"
  }'
```

**Tempo estimado:** ~20-40 segundos

---

### 2. Com Discovery Automático (dados cadastrais)

A API busca automaticamente o site oficial via Google:

```bash
curl -X POST "http://localhost:8000/analyze" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sua-api-key" \
  -d '{
    "razao_social": "MAGAZINE LUIZA S/A",
    "nome_fantasia": "Magazine Luiza",
    "cnpj": "47.960.950/0001-21"
  }'
```

**Tempo estimado:** ~30-60 segundos (inclui etapa de discovery)

---

### 3. Discovery com Dados Mínimos

Apenas o nome fantasia é suficiente para tentar o discovery:

```bash
curl -X POST "http://localhost:8000/analyze" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sua-api-key" \
  -d '{
    "nome_fantasia": "Mercado Livre"
  }'
```

---

### 4. Discovery Completo (maior precisão)

Quanto mais dados, maior a chance de encontrar o site correto:

```bash
curl -X POST "http://localhost:8000/analyze" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sua-api-key" \
  -d '{
    "razao_social": "DISTRIBUIDORA EXEMPLO LTDA",
    "nome_fantasia": "Distribuidora Exemplo",
    "cnpj": "12.345.678/0001-90",
    "email": "contato@exemplo.com.br",
    "municipio": "São Paulo",
    "cnaes": ["4751201", "4649410"]
  }'
```

---

## 📤 Estrutura do Response

### Sucesso (200 OK)

```json
{
  "identity": {
    "company_name": "Magazine Luiza",
    "cnpj": "47.960.950/0001-21",
    "tagline": "Vem ser feliz!",
    "description": "Varejista brasileiro líder em e-commerce e marketplace...",
    "founding_year": "1957",
    "employee_count_range": "40000+"
  },
  "classification": {
    "industry": "Varejo",
    "business_model": "B2C / Marketplace",
    "target_audience": "Consumidores finais",
    "geographic_coverage": "Nacional"
  },
  "team": {
    "size_range": "40000+",
    "key_roles": ["Vendedores", "Desenvolvedores", "Logística"],
    "team_certifications": []
  },
  "offerings": {
    "products": ["Eletrônicos", "Móveis", "Eletrodomésticos"],
    "product_categories": [
      {
        "category_name": "Eletrônicos",
        "items": ["Smartphones", "Notebooks", "TVs", "Tablets"]
      },
      {
        "category_name": "Eletrodomésticos",
        "items": ["Geladeiras", "Fogões", "Lavadoras", "Micro-ondas"]
      }
    ],
    "services": ["Marketplace", "Lu Conecta", "Cartão Luiza"],
    "service_details": [
      {
        "name": "Marketplace",
        "description": "Plataforma para vendedores terceiros",
        "methodology": null,
        "deliverables": [],
        "ideal_client_profile": "Lojistas e fabricantes"
      }
    ],
    "engagement_models": ["E-commerce", "Lojas físicas"],
    "key_differentiators": ["Maior e-commerce brasileiro", "Rede de lojas físicas"]
  },
  "reputation": {
    "certifications": ["ISO 9001"],
    "awards": ["Melhor E-commerce do Brasil"],
    "partnerships": ["Google", "Facebook", "Visa"],
    "client_list": [],
    "case_studies": []
  },
  "contact": {
    "emails": ["sac@magazineluiza.com.br"],
    "phones": ["0800 123 4567"],
    "linkedin_url": "https://linkedin.com/company/magazine-luiza",
    "website_url": "https://www.magazineluiza.com.br",
    "headquarters_address": "Franca, SP",
    "locations": ["São Paulo", "Franca", "Rio de Janeiro"]
  },
  "sources": [
    "https://www.magazineluiza.com.br",
    "https://www.magazineluiza.com.br/quem-somos/",
    "https://www.magazineluiza.com.br/contato/"
  ]
}
```

---

### Erros Comuns

#### 400 Bad Request
```json
{
  "detail": "Deve fornecer URL ou dados da empresa (razao_social, nome_fantasia, cnpj)"
}
```
**Causa:** Nenhum dado foi enviado no request.

---

#### 404 Not Found
```json
{
  "detail": "Site oficial não encontrado com os dados fornecidos."
}
```
**Causa:** A etapa de discovery não conseguiu identificar o site oficial.

---

#### 504 Gateway Timeout
```json
{
  "detail": "Analysis timed out (exceeded 300s)"
}
```
**Causa:** Processamento excedeu 5 minutos (site muito grande ou lento).

---

## 💻 Exemplos em Linguagens

### Python

```python
import requests

url = "http://localhost:8000/analyze"
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer sua-api-key"
}
payload = {
    "nome_fantasia": "Magazine Luiza",
    "razao_social": "MAGAZINE LUIZA S/A",
    "cnpj": "47.960.950/0001-21"
}

response = requests.post(url, json=payload, headers=headers, timeout=300)

if response.status_code == 200:
    profile = response.json()
    print(f"Empresa: {profile['identity']['company_name']}")
    print(f"Indústria: {profile['classification']['industry']}")
    print(f"Produtos: {profile['offerings']['products']}")
else:
    print(f"Erro: {response.status_code} - {response.text}")
```

---

### JavaScript (Node.js)

```javascript
const fetch = require('node-fetch');

async function analyzeCompany() {
  const response = await fetch('http://localhost:8000/analyze', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer sua-api-key'
    },
    body: JSON.stringify({
      nome_fantasia: 'Magazine Luiza',
      razao_social: 'MAGAZINE LUIZA S/A'
    })
  });

  if (response.ok) {
    const profile = await response.json();
    console.log('Empresa:', profile.identity.company_name);
    console.log('Serviços:', profile.offerings.services);
  } else {
    console.error('Erro:', response.status, await response.text());
  }
}

analyzeCompany();
```

---

### TypeScript

```typescript
interface CompanyRequest {
  url?: string;
  razao_social?: string;
  nome_fantasia?: string;
  cnpj?: string;
  email?: string;
  municipio?: string;
  cnaes?: string[];
}

interface CompanyProfile {
  identity: {
    company_name: string | null;
    description: string | null;
    // ... outros campos
  };
  offerings: {
    products: string[];
    services: string[];
    // ... outros campos
  };
  // ... outras seções
}

async function analyzeCompany(request: CompanyRequest): Promise<CompanyProfile> {
  const response = await fetch('http://localhost:8000/analyze', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer sua-api-key'
    },
    body: JSON.stringify(request)
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${await response.text()}`);
  }

  return response.json();
}

// Uso
const profile = await analyzeCompany({
  nome_fantasia: 'Magazine Luiza'
});
```

---

## 🔄 Endpoints Auxiliares

### Health Check

```bash
GET /
```

Response:
```json
{
  "status": "ok",
  "service": "B2B Flash Profiler"
}
```

---

### Status do Sistema de Aprendizado

```bash
GET /learning/status
```

Response:
```json
{
  "total_analyses": 1523,
  "success_rate": 0.892,
  "current_config": {
    "scrape_timeout": 45,
    "max_subpages": 10
  }
}
```

---

### Forçar Otimização

```bash
POST /learning/optimize
```

Response:
```json
{
  "message": "Otimização executada",
  "status": { ... }
}
```

---

## ⚡ Dicas de Performance

1. **Use URL direta quando possível** - Pula a etapa de discovery (~10-15s a menos)

2. **Forneça o máximo de dados para discovery** - Maior precisão na busca

3. **Timeout adequado** - Configure timeout de pelo menos 120s no seu cliente

4. **Processamento em lote** - Para muitas empresas, processe em paralelo (máx 50 simultâneos recomendado)

---

## 📊 Taxas de Sucesso por Tipo de Input

| Tipo de Input | Taxa de Sucesso | Tempo Médio |
|---------------|-----------------|-------------|
| URL direta | 95%+ | ~25s |
| Nome fantasia + Razão social | 85% | ~45s |
| Apenas nome fantasia | 70% | ~50s |
| Dados completos (todos campos) | 90% | ~40s |

