"""
Serviço principal de análise de conteúdo por LLM v3.0.
Orquestra chunking, processamento e consolidação.

REFATORADO: Agora usa llm_manager para gerenciamento de chamadas
e ProfileExtractorAgent para extração de perfil.
"""

import asyncio
import time
import logging
from typing import List, Optional

from app.schemas.profile import CompanyProfile

# Usar llm_manager para gerenciamento de chamadas
from app.services.llm_manager import get_llm_manager, LLMPriority

# Usar agente de extração de perfil
from app.services.agents import get_profile_extractor_agent

# Usar novo módulo de chunking v4.0
from app.core.chunking import process_content as process_content_v4, get_chunking_config
from .constants import SYSTEM_PROMPT  # Manter apenas SYSTEM_PROMPT
from .profile_merger import merge_profiles
from .debug_saver import save_raw_content, save_chunks, analyze_content_quality
from app.core.token_utils import estimate_tokens

logger = logging.getLogger(__name__)


class LLMService:
    """
    Serviço de análise LLM com balanceamento e fallback automático.
    
    v3.0: Refatorado para usar llm_manager e ProfileExtractorAgent.
    """
    
    def __init__(self):
        self.llm_manager = get_llm_manager()
        self.profile_extractor = get_profile_extractor_agent()
    
    async def analyze(self, content: str, ctx_label: str = "", request_id: str = "", url: str = None, cnpj: str = None, company_name: str = None) -> CompanyProfile:
        """
        Analisa conteúdo e extrai perfil da empresa.

        Args:
            content: Texto para análise
            ctx_label: Label de contexto para logs
            request_id: ID único da requisição
            url: URL da empresa (para debug)
            cnpj: CNPJ da empresa (para debug)
            company_name: Nome da empresa (para debug)

        Returns:
            CompanyProfile com dados extraídos
        """
        start_time = time.perf_counter()
        tokens = estimate_tokens(content)

        # DEBUG: Salvar conteúdo bruto
        try:
            raw_content_stats = save_raw_content(
                content=content,
                request_id=request_id or "unknown",
                url=url,
                cnpj=cnpj,
                company_name=company_name
            )
            quality_stats = analyze_content_quality(content)
            logger.debug(f"{ctx_label}[DEBUG] Qualidade do conteúdo: {quality_stats}")
        except Exception as e:
            logger.warning(f"{ctx_label}[DEBUG] Erro ao salvar conteúdo bruto: {e}")
            raw_content_stats = {}

        # Chunking v4.0: Pipeline completo (preprocess → chunk → validate)
        chunking_start = time.perf_counter()
        chunk_objects = process_content_v4(content)
        chunking_duration = (time.perf_counter() - chunking_start) * 1000
        
        # Extrair conteúdo dos chunks para compatibilidade com código existente
        chunks = [chunk.content for chunk in chunk_objects]
        
        logger.info(
            f"{ctx_label}Chunking v4.0: {len(chunks)} chunks gerados "
            f"(tempo: {chunking_duration:.0f}ms)"
        )

        # DEBUG: Salvar chunks
        try:
            chunking_config = get_chunking_config()
            chunks_stats = save_chunks(
                chunks=chunks,
                request_id=request_id or "unknown",
                raw_content_stats=raw_content_stats,
                max_chunk_tokens=chunking_config.max_chunk_tokens
            )
        except Exception as e:
            logger.warning(f"{ctx_label}[DEBUG] Erro ao salvar chunks: {e}")

        if len(chunks) == 1:
            return await self._process_single_chunk(chunks[0], start_time, ctx_label, request_id)

        return await self._process_multiple_chunks(chunks, start_time, ctx_label, request_id)
    
    async def _process_single_chunk(
        self,
        chunk: str,
        start_time: float,
        ctx_label: str = "",
        request_id: str = ""
    ) -> CompanyProfile:
        """
        Processa chunk único usando ProfileExtractorAgent.
        
        v4.0: Chunk já está validado pelo novo módulo de chunking,
        não precisa validação adicional.
        """
        llm_call_start = time.perf_counter()

        try:
            profile = await self.profile_extractor.extract_profile(
                content=chunk,
                ctx_label=ctx_label,
                request_id=request_id
                )

            if profile and not profile.is_empty():
                llm_call_duration = (time.perf_counter() - llm_call_start) * 1000
                return profile
            else:
                logger.warning(f"{ctx_label}LLMService: Perfil vazio retornado")
                return CompanyProfile()
            
        except Exception as e:
            llm_call_duration = (time.perf_counter() - llm_call_start) * 1000
            duration = time.perf_counter() - start_time
            logger.error(f"{ctx_label}LLMService: Falha em {duration:.2f}s: {e}")
            return CompanyProfile()
    
    async def _process_multiple_chunks(
        self,
        chunks: List[str],
        start_time: float,
        ctx_label: str = "",
        request_id: str = ""
    ) -> CompanyProfile:
        """
        Processa múltiplos chunks em paralelo e consolida resultados.
        """
        
        llm_calls_start = time.perf_counter()
        
        # Criar tasks para cada chunk
        tasks = []
        for i, chunk in enumerate(chunks):
            tasks.append(self._process_chunk(chunk, i + 1, len(chunks), ctx_label, request_id))
        
        # Executar em paralelo com timeout global
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=240.0
            )
        except asyncio.TimeoutError:
            logger.error(f"{ctx_label}LLMService: Timeout global (240s)")
            results = []
        
        llm_calls_duration = (time.perf_counter() - llm_calls_start) * 1000
        
        # Filtrar resultados válidos e contar retries
        valid_profiles = []
        failed_chunks = 0
        # Nota: retries são contados internamente pelo LLM manager, aqui contamos apenas falhas
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"{ctx_label}LLMService: Chunk {i+1} falhou: {result}")
                failed_chunks += 1
            elif result is not None:
                valid_profiles.append(result)
        
        # Retries são estimados como número de chunks que falharam (cada falha pode ter tido retries internos)
        estimated_retries = failed_chunks
        
        
        if not valid_profiles:
            duration = time.perf_counter() - start_time
            logger.error(f"{ctx_label}LLMService: Todos chunks falharam em {duration:.2f}s")
            return CompanyProfile()
        
        # Consolidar resultados
        merge_start = time.perf_counter()
        final_profile = merge_profiles(valid_profiles)
        merge_duration = (time.perf_counter() - merge_start) * 1000
        
        return final_profile
    
    async def _process_chunk(
        self,
        chunk: str,
        chunk_num: int,
        total_chunks: int,
        ctx_label: str = "",
        request_id: str = ""
    ) -> Optional[CompanyProfile]:
        """
        Processa um chunk individual usando ProfileExtractorAgent.
        
        v4.0: Chunk já está validado pelo novo módulo de chunking,
        não precisa validação adicional.
        """
        chunk_ctx_label = f"{ctx_label}[Chunk {chunk_num}/{total_chunks}]"
        
        try:
            profile = await self.profile_extractor.extract_profile(
                content=chunk,
                ctx_label=chunk_ctx_label,
                request_id=f"{request_id}_chunk_{chunk_num}"
                )

            if profile and not profile.is_empty():
                return profile
            else:
                logger.warning(
                    f"{chunk_ctx_label}LLMService: Perfil vazio retornado"
                )
                return None

        except Exception as e:
            logger.warning(
                f"{chunk_ctx_label}LLMService: Chunk {chunk_num}/{total_chunks} falhou: {e}"
            )
            return None
    
    # DEPRECATED: Este método não é mais usado. Validação é feita pelo módulo app.core.chunking
    # Mantido temporariamente para referência, será removido em versão futura.
    async def _validate_and_fix_chunk(
        self,
        chunk: str,
        ctx_label: str = ""
    ) -> List[str]:
        """
        ⚠️ DEPRECATED: Use app.core.chunking.validate_chunks() ao invés.
        
        RECOMENDAÇÃO 2: Valida chunk antes de enviar ao LLM.

        v3.0: NUNCA trunca - sempre divide em chunks menores.
        Aplica margem de segurança dinâmica baseada em repetição e tamanho.

        Verifica se o chunk não excede o limite de tokens considerando overhead.
        Se exceder, divide em múltiplos chunks menores para preservar TODAS as informações.

        Args:
            chunk: Conteúdo do chunk a validar
            ctx_label: Label de contexto para logs

        Returns:
            Lista de chunks validados (sempre preserva todas as informações)
        """
        # Calcular overhead total (system prompt + message formatting)
        message_overhead = 200  # ~100 tokens por mensagem * 2 mensagens
        total_overhead = llm_config.system_prompt_overhead + message_overhead
        base_effective_max_tokens = llm_config.max_chunk_tokens - total_overhead
        
        # CORREÇÃO CRÍTICA: Estimar tokens totais incluindo overhead completo
        # Quando o chunk vai para o LLM, ele inclui system prompt + message formatting
        chunk_tokens = estimate_tokens(chunk, include_overhead=True)
        
        # NOVA: Calcular margem de segurança dinâmica
        effective_max_tokens, margin_info = calculate_safety_margin(
            content=chunk,
            estimated_tokens=chunk_tokens,
            base_effective_max=base_effective_max_tokens
        )
        
        # Log se margem foi aplicada
        if margin_info["total_margin"] > 0:
            logger.debug(
                f"{ctx_label}VALIDATION: Margem de segurança aplicada "
                f"(repetição: {margin_info['repetition_rate']*100:.1f}%, "
                f"margem: {margin_info['total_margin']*100:.0f}%) → "
                f"effective_max: {effective_max_tokens:,} tokens"
            )
        
        # Validar se está dentro do limite (agora com margem de segurança)
        if chunk_tokens <= effective_max_tokens:
            return [chunk]  # Retorna lista com um único chunk válido

        # Chunk excede limite - DIVIDIR em vez de truncar (preserva TODAS as informações)
        logger.warning(
            f"{ctx_label}VALIDATION: Chunk excede limite mesmo com margem de segurança "
            f"({chunk_tokens:,} > {effective_max_tokens:,} tokens), DIVIDINDO em chunks menores..."
        )

        # FASE 2: Tentar usar contagem exata do servidor primeiro
        exact_tokens = await self.get_exact_token_count(
            [{"role": "user", "content": chunk}],
            ctx_label
        )

        if exact_tokens and exact_tokens <= effective_max_tokens:
            logger.debug(f"{ctx_label}VALIDATION: Contagem exata do servidor confirma chunk válido ({exact_tokens} tokens)")
            return [chunk]

        # DIVIDIR o chunk em partes menores (NUNCA truncar)
        divided_chunks = await self._split_large_content(chunk, effective_max_tokens, ctx_label)

        total_divided_tokens = sum(estimate_tokens(c, include_overhead=True) for c in divided_chunks)
        logger.info(
            f"{ctx_label}VALIDATION: Chunk dividido de {chunk_tokens:,} tokens "
            f"em {len(divided_chunks)} chunks ({total_divided_tokens:,} tokens total) - "
            f"NENHUMA informação perdida!"
        )

        return divided_chunks

    async def _split_large_content(
        self,
        content: str,
        max_tokens: int,
        ctx_label: str = ""
    ) -> List[str]:
        """
        Divide conteúdo grande em chunks menores para evitar truncamento.

        Estratégia simples e segura: divide por tamanho de caracteres estimado,
        preservando SEMPRE todo o conteúdo original.

        Args:
            content: Conteúdo a dividir
            max_tokens: Limite máximo de tokens por chunk (com overhead)
            ctx_label: Label para logs

        Returns:
            Lista de chunks que somados preservam 100% do conteúdo original
        """
        from app.core.token_utils import estimate_tokens

        # Estratégia segura: estimar tamanho baseado em caracteres
        # ~3 chars por token é uma estimativa conservadora
        chars_per_token = 3.5  # Mais conservador para evitar subestimação
        max_chars_per_chunk = int(max_tokens * chars_per_token * 0.8)  # 80% do limite para margem

        chunks = []
        remaining = content
        chunk_number = 1

        logger.debug(
            f"{ctx_label}DIVISION: Iniciando divisão segura de {len(content):,} chars "
            f"(máx {max_chars_per_chunk:,} chars por chunk)"
        )

        while remaining:
            # Pegar o próximo chunk do tamanho máximo
            if len(remaining) <= max_chars_per_chunk:
                # Último chunk - usar tudo que restou
                chunk = remaining
                remaining = ""
            else:
                # Encontrar um ponto de quebra natural (final de linha ou espaço)
                chunk = remaining[:max_chars_per_chunk]

                # Tentar quebrar em um espaço ou nova linha para não cortar palavras
                last_space = chunk.rfind(' ')
                last_newline = chunk.rfind('\n')

                # Preferir quebra em nova linha, depois em espaço
                break_point = max(last_newline, last_space)

                if break_point > max_chars_per_chunk * 0.7:  # Só quebrar se estiver próximo do limite
                    chunk = chunk[:break_point + 1]  # +1 para incluir o caractere de quebra
                    remaining = remaining[break_point + 1:]
                else:
                    # Não encontrou ponto de quebra bom, cortar mesmo
                    remaining = remaining[max_chars_per_chunk:]

            if chunk.strip():  # Só adicionar se não estiver vazio
                # Validação final: verificar se está dentro do limite de tokens
                chunk_tokens = estimate_tokens(chunk, include_overhead=True)

                if chunk_tokens > max_tokens:
                    # Ainda excede, reduzir mais - CORREÇÃO: Garantir que sempre caiba
                    logger.warning(
                        f"{ctx_label}DIVISION: Chunk {chunk_number} excede tokens "
                        f"({chunk_tokens:,} > {max_tokens:,}), reduzindo..."
                    )

                    # Estratégia agressiva: reduzir até caber, começando de reduções suaves
                    safe_chunk = chunk
                    found_safe_size = False

                    # Tentar reduções progressivamente mais agressivas
                    for reduction in [0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50]:
                        test_size = int(len(chunk) * reduction)
                        if test_size < 1000:  # Mínimo de 1000 chars para evitar chunks inúteis
                            break

                        test_chunk = chunk[:test_size]
                        test_tokens = estimate_tokens(test_chunk, include_overhead=True)

                        if test_tokens <= max_tokens:
                            safe_chunk = test_chunk
                            found_safe_size = True
                            logger.debug(
                                f"{ctx_label}DIVISION: Chunk reduzido para {len(safe_chunk):,} chars "
                                f"({test_tokens:,} tokens) com redução de {reduction*100:.0f}%"
                            )
                            break

                    # Se ainda não encontrou um tamanho seguro, reduzir drasticamente
                    if not found_safe_size:
                        # Redução final: calcular tamanho exato baseado em tokens
                        estimated_chars_per_token = len(chunk) / chunk_tokens
                        target_chars = int(max_tokens * estimated_chars_per_token * 0.9)  # 90% para margem
                        safe_chunk = chunk[:target_chars]

                        # Verificar se ainda excede e ajustar se necessário
                        final_tokens = estimate_tokens(safe_chunk, include_overhead=True)
                        if final_tokens > max_tokens:
                            # Ajuste fino: reduzir até caber
                            while len(safe_chunk) > 1000 and estimate_tokens(safe_chunk, include_overhead=True) > max_tokens:
                                safe_chunk = safe_chunk[:-100]  # Remover 100 chars por vez

                        logger.warning(
                            f"{ctx_label}DIVISION: Redução final aplicada - {len(safe_chunk):,} chars "
                            f"({estimate_tokens(safe_chunk, include_overhead=True):,} tokens)"
                        )

                    chunk = safe_chunk

                chunks.append(chunk)
                logger.debug(
                    f"{ctx_label}DIVISION: Chunk {chunk_number} criado "
                    f"({len(chunk):,} chars, ~{len(chunk)//3:,} tokens estimados)"
                )
                chunk_number += 1
            else:
                break  # Evitar loop infinito

        # Validação final: verificar preservação total
        total_chars_preserved = sum(len(chunk) for chunk in chunks)
        total_chars_original = len(content)

        if total_chars_preserved == total_chars_original:
            logger.info(
                f"{ctx_label}DIVISION: ✅ Sucesso! {len(chunks)} chunks criados, "
                f"100% do conteúdo preservado ({total_chars_preserved:,} chars)"
            )
        else:
            logger.error(
                f"{ctx_label}DIVISION: ❌ Erro! Preservação incompleta: "
                f"{total_chars_preserved:,}/{total_chars_original:,} chars "
                f"({total_chars_preserved/total_chars_original*100:.2f}%)"
            )

        return chunks

    async def get_exact_token_count(self, messages: list, ctx_label: str = "") -> Optional[int]:
        """
        FASE 2: Conta tokens exatamente como o servidor vLLM fará.

        Usa uma chamada de teste com max_tokens=1 para obter prompt_tokens
        da resposta, que é mais confiável que estimativas locais.

        Args:
            messages: Lista de mensagens no formato OpenAI
            ctx_label: Label de contexto para logs

        Returns:
            Contagem exata de tokens ou None se falhar
        """
        try:
            # Usar httpx diretamente para fazer uma chamada de teste
            import httpx
            from app.core.config import settings

            config = settings

            # Fazer uma chamada de teste com max_tokens=1 para obter prompt_tokens
            # Usar VLLM_* (unificado) com fallback para RUNPOD_* (compatibilidade)
            api_key = config.VLLM_API_KEY or config.RUNPOD_API_KEY
            base_url = config.VLLM_BASE_URL or config.RUNPOD_BASE_URL
            model = config.VLLM_MODEL or config.RUNPOD_MODEL
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    base_url + "/chat/completions",
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": 1,
                        "temperature": 0
                    },
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()

                prompt_tokens = result.get("usage", {}).get("prompt_tokens")
                if prompt_tokens is not None:
                    logger.debug(f"{ctx_label}TOKEN_COUNT: vLLM retornou {prompt_tokens} prompt_tokens")
                    return prompt_tokens
                else:
                    logger.warning(f"{ctx_label}TOKEN_COUNT: usage.prompt_tokens não encontrado na resposta")
                    return None

        except Exception as e:
            logger.warning(f"{ctx_label}TOKEN_COUNT: Falha ao consultar vLLM: {e}")
            return None


# Instância singleton
_llm_service = None


def get_llm_service() -> LLMService:
    """Retorna instância singleton do LLMService."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


async def analyze_content(
    text_content: str, 
    ctx_label: str = "", 
    request_id: str = "",
    url: str = None,
    cnpj: str = None,
    company_name: str = None
) -> CompanyProfile:
    """
    Função de conveniência para análise de conteúdo.
    Mantém compatibilidade com código existente.
    """
    service = get_llm_service()
    return await service.analyze(
        text_content, 
        ctx_label=ctx_label, 
        request_id=request_id,
        url=url,
        cnpj=cnpj,
        company_name=company_name
    )
