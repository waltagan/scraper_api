"""
Chunker - Divisão inteligente de conteúdo em chunks.

Responsável por dividir conteúdo grande em chunks menores respeitando
rigorosamente os limites de tokens configurados.

Estratégia:
1. Dividir por páginas (marcador --- PAGE START:)
2. Validar tamanho de cada página
3. Dividir páginas grandes em sub-chunks
4. Agrupar páginas pequenas respeitando limite
5. Validar todos os chunks antes de retornar
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.core.token_utils import estimate_tokens

from .config import ChunkingConfig

logger = logging.getLogger(__name__)

# Marcador de páginas
PAGE_START_MARKER = "--- PAGE START:"
PAGE_END_MARKER = "--- PAGE END ---"


@dataclass
class Chunk:
    """
    Representa um chunk de conteúdo com metadados.
    
    Atributos:
        content: Conteúdo do chunk
        tokens: Número de tokens estimados
        index: Índice do chunk (1-based)
        total_chunks: Total de chunks gerados
        pages_included: Lista de URLs das páginas incluídas
    """
    
    content: str
    tokens: int
    index: int
    total_chunks: int
    pages_included: List[str] = None
    
    def __post_init__(self):
        if self.pages_included is None:
            self.pages_included = []
    
    def __str__(self) -> str:
        return (
            f"Chunk({self.index}/{self.total_chunks}, "
            f"{self.tokens:,} tokens, {len(self.pages_included)} páginas)"
        )


class SmartChunker:
    """
    Chunker inteligente que divide conteúdo respeitando limites de tokens.
    """
    
    def __init__(self, config: ChunkingConfig):
        """
        Inicializa o chunker.
        
        Args:
            config: Configuração de chunking
        """
        self.config = config
        self.effective_max_tokens = config.effective_max_tokens
    
    def _count_tokens(self, text: str) -> int:
        """
        Conta tokens em um texto.
        
        Usa estimate_tokens do token_utils que já tem suporte a mistral-common.
        
        Args:
            text: Texto para contar tokens
        
        Returns:
            Número de tokens estimados
        """
        return estimate_tokens(text, include_overhead=False)
    
    def _split_by_pages(self, content: str) -> List[str]:
        """
        Divide conteúdo por marcadores de página.
        
        Args:
            content: Conteúdo completo
        
        Returns:
            Lista de páginas (cada uma com seu marcador)
        """
        # Dividir por marcador de página
        parts = content.split(PAGE_START_MARKER)
        pages = []
        
        for i, part in enumerate(parts):
            if i == 0:
                # Primeira parte (antes do primeiro marcador)
                if part.strip():
                    pages.append(part)
            else:
                # Partes seguintes (após marcadores)
                # Adicionar o marcador de volta
                page = PAGE_START_MARKER + part
                pages.append(page)
        
        logger.debug(f"Dividido em {len(pages)} páginas por marcador '{PAGE_START_MARKER}'")
        return pages
    
    def _extract_page_url(self, page_content: str) -> Optional[str]:
        """
        Extrai URL de uma página do marcador.
        
        Args:
            page_content: Conteúdo da página com marcador
        
        Returns:
            URL extraída ou None
        """
        # Procurar padrão: --- PAGE START: <url> ---
        match = re.search(rf"{re.escape(PAGE_START_MARKER)}\s*([^\n]+)", page_content)
        if match:
            return match.group(1).strip()
        return None
    
    def _split_large_page(self, page_content: str, max_tokens: int) -> List[str]:
        """
        Divide uma página muito grande em múltiplos chunks menores.
        
        Estratégia progressiva:
        1. Tentar dividir por parágrafos (\n\n)
        2. Se necessário, dividir por linhas (\n)
        3. Como último recurso, dividir por caracteres
        
        Args:
            page_content: Conteúdo da página
            max_tokens: Limite máximo de tokens por chunk
        
        Returns:
            Lista de sub-chunks da página
        """
        chunks = []
        current_chunk = ""
        current_tokens = 0
        
        # Tentar dividir por parágrafos primeiro
        paragraphs = page_content.split('\n\n')
        
        # Se não há parágrafos (texto sem quebras), usar linhas
        if len(paragraphs) == 1:
            paragraphs = page_content.split('\n')
        
        for para in paragraphs:
            # Adicionar separador de volta (exceto para último)
            para_with_sep = para + ('\n\n' if '\n\n' in page_content else '\n')
            para_tokens = self._count_tokens(para_with_sep)
            
            # Se parágrafo sozinho excede limite, dividir por linhas
            if para_tokens > max_tokens:
                logger.debug(f"Parágrafo muito grande ({para_tokens} tokens), dividindo por linhas...")
                line_chunks = self._split_by_lines(para, max_tokens)
                chunks.extend(line_chunks)
                current_chunk = ""
                current_tokens = 0
                continue
            
            # Verificar se adicionar parágrafo excederia limite
            if current_tokens + para_tokens > max_tokens and current_chunk:
                # Salvar chunk atual e começar novo
                chunks.append(current_chunk)
                current_chunk = para_with_sep
                current_tokens = para_tokens
            else:
                # Adicionar ao chunk atual
                current_chunk += para_with_sep
                current_tokens += para_tokens
        
        # Adicionar último chunk se houver
        if current_chunk:
            chunks.append(current_chunk)
        
        if len(chunks) > 1:
            logger.info(f"Página dividida em {len(chunks)} sub-chunks")
        
        return chunks
    
    def _split_by_lines(self, content: str, max_tokens: int) -> List[str]:
        """
        Divide conteúdo por linhas quando parágrafos não funcionam.
        
        Args:
            content: Conteúdo para dividir
            max_tokens: Limite máximo de tokens
        
        Returns:
            Lista de chunks
        """
        chunks = []
        lines = content.split('\n')
        current_chunk = ""
        current_tokens = 0
        
        for line in lines:
            line_with_newline = line + '\n'
            line_tokens = self._count_tokens(line_with_newline)
            
            # Se linha sozinha excede limite, dividir por caracteres
            if line_tokens > max_tokens:
                logger.warning(f"Linha muito grande ({line_tokens} tokens), dividindo por caracteres...")
                char_chunks = self._split_by_chars(line, max_tokens)
                chunks.extend(char_chunks)
                current_chunk = ""
                current_tokens = 0
                continue
            
            # Verificar se adicionar linha excederia limite
            if current_tokens + line_tokens > max_tokens and current_chunk:
                chunks.append(current_chunk)
                current_chunk = line_with_newline
                current_tokens = line_tokens
            else:
                current_chunk += line_with_newline
                current_tokens += line_tokens
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    def _split_by_chars(self, content: str, max_tokens: int) -> List[str]:
        """
        Divide conteúdo por caracteres como último recurso.
        
        Calcula a razao real chars/token do conteudo para evitar
        chunks que ainda excedem o limite de tokens.
        """
        from app.core.token_utils import estimate_tokens
        
        total_tokens = estimate_tokens(content, include_overhead=False)
        total_chars = len(content)
        
        if total_tokens > 0:
            real_chars_per_token = total_chars / total_tokens
        else:
            real_chars_per_token = self.config.tokenizer.fallback_chars_per_token
        
        max_chars = int(max_tokens * real_chars_per_token * 0.85)
        max_chars = max(max_chars, 100)
        
        chunks = []
        remaining = content
        
        while remaining:
            if self._count_tokens(remaining) <= max_tokens:
                chunks.append(remaining)
                break
            
            chunk = remaining[:max_chars]
            last_space = chunk.rfind(' ')
            last_newline = chunk.rfind('\n')
            
            break_point = max(last_newline, last_space)
            
            if break_point > max_chars * 0.7:
                chunk = remaining[:break_point + 1]
                remaining = remaining[break_point + 1:]
            else:
                chunk = remaining[:max_chars]
                remaining = remaining[max_chars:]
            
            if chunk.strip():
                chunks.append(chunk)
        
        return chunks
    
    def _group_small_pages(self, pages: List[str], target_tokens: int) -> List[str]:
        """
        Agrupa páginas pequenas em chunks maiores.
        
        Agrupa páginas até atingir target_tokens, mas nunca excede effective_max_tokens.
        
        Args:
            pages: Lista de páginas
            target_tokens: Alvo de tokens para agrupamento
        
        Returns:
            Lista de chunks agrupados
        """
        grouped_chunks = []
        current_group = ""
        current_tokens = 0
        
        for page in pages:
            page_tokens = self._count_tokens(page)
            
            # Verificar se adicionar esta página excederia limite
            potential_tokens = current_tokens + page_tokens
            
            if potential_tokens > self.effective_max_tokens and current_group:
                # Chunk atual está completo, salvar e começar novo
                grouped_chunks.append(current_group)
                current_group = page
                current_tokens = page_tokens
            elif current_tokens >= target_tokens and current_group:
                # Atingiu target mas não excedeu limite, opcionalmente começar novo chunk
                # (preferir agrupar mais para reduzir número de chunks)
                if potential_tokens <= self.effective_max_tokens:
                    # Pode adicionar mais, continuar agrupando
                    current_group += "\n\n" + page
                    current_tokens = potential_tokens
                else:
                    # Não cabe, salvar e começar novo
                    grouped_chunks.append(current_group)
                    current_group = page
                    current_tokens = page_tokens
            else:
                # Adicionar ao grupo atual
                if current_group:
                    current_group += "\n\n" + page
                else:
                    current_group = page
                current_tokens = potential_tokens
        
        # Adicionar último grupo
        if current_group:
            grouped_chunks.append(current_group)
        
        logger.debug(
            f"Agrupadas {len(pages)} páginas em {len(grouped_chunks)} chunks "
            f"(target: {target_tokens:,}, max: {self.effective_max_tokens:,} tokens)"
        )
        
        return grouped_chunks
    
    def chunk_content(self, content: str) -> List[Chunk]:
        """
        Divide conteúdo em chunks respeitando limites de tokens.
        
        Pipeline:
        1. Dividir por páginas
        2. Validar e dividir páginas grandes
        3. Agrupar páginas pequenas
        4. Criar objetos Chunk com metadados
        5. Validar todos os chunks
        
        Args:
            content: Conteúdo para dividir
        
        Returns:
            Lista de Chunks válidos
        """
        total_tokens = self._count_tokens(content)
        logger.info(f"Iniciando chunking: {len(content):,} chars, ~{total_tokens:,} tokens")
        
        # 1. Dividir por páginas
        raw_pages = self._split_by_pages(content)
        logger.debug(f"Dividido em {len(raw_pages)} páginas iniciais")
        
        # 2. Validar e dividir páginas grandes
        processed_pages = []
        for i, page in enumerate(raw_pages):
            page_tokens = self._count_tokens(page)
            
            if page_tokens > self.effective_max_tokens:
                logger.warning(
                    f"Página {i+1}/{len(raw_pages)} muito grande ({page_tokens:,} tokens), dividindo..."
                )
                page_chunks = self._split_large_page(page, self.effective_max_tokens)
                processed_pages.extend(page_chunks)
                logger.info(f"  Página {i+1} dividida em {len(page_chunks)} sub-chunks")
            else:
                processed_pages.append(page)
        
        # 3. Agrupar páginas pequenas
        grouped_content = self._group_small_pages(processed_pages, self.config.group_target_tokens)
        logger.debug(f"Agrupamento resultou em {len(grouped_content)} chunks")
        
        # 4. Criar objetos Chunk com metadados
        chunks = []
        for i, chunk_content in enumerate(grouped_content):
            chunk_tokens = self._count_tokens(chunk_content)
            
            # Extrair URLs das páginas incluídas
            pages_included = []
            for page in self._split_by_pages(chunk_content):
                url = self._extract_page_url(page)
                if url:
                    pages_included.append(url)
            
            chunk = Chunk(
                content=chunk_content,
                tokens=chunk_tokens,
                index=i + 1,
                total_chunks=len(grouped_content),
                pages_included=pages_included,
            )
            chunks.append(chunk)
            
            logger.debug(
                f"Chunk {chunk.index}/{chunk.total_chunks}: {chunk.tokens:,} tokens, "
                f"{len(chunk.pages_included)} páginas"
            )
        
        # 5. Validação final - garantir que nenhum chunk excede limite
        valid_chunks = []
        for chunk in chunks:
            if chunk.tokens > self.effective_max_tokens:
                logger.warning(
                    f"Chunk {chunk.index} excede limite ({chunk.tokens:,} > {self.effective_max_tokens:,}), "
                    f"dividindo..."
                )
                # Dividir chunk excedente
                sub_chunks = self._split_large_page(chunk.content, self.effective_max_tokens)
                for j, sub_content in enumerate(sub_chunks):
                    sub_tokens = self._count_tokens(sub_content)
                    sub_chunk = Chunk(
                        content=sub_content,
                        tokens=sub_tokens,
                        index=len(valid_chunks) + j + 1,
                        total_chunks=len(valid_chunks) + len(sub_chunks),
                        pages_included=chunk.pages_included,
                    )
                    valid_chunks.append(sub_chunk)
            else:
                valid_chunks.append(chunk)
        
        # Atualizar total_chunks em todos os chunks
        total_valid = len(valid_chunks)
        for chunk in valid_chunks:
            chunk.total_chunks = total_valid
        
        # Log final
        total_chunk_tokens = sum(c.tokens for c in valid_chunks)
        avg_tokens = total_chunk_tokens / len(valid_chunks) if valid_chunks else 0
        max_chunk_tokens = max((c.tokens for c in valid_chunks), default=0)
        
        logger.info(
            f"✅ Chunking concluído: {len(valid_chunks)} chunks "
            f"(avg: {avg_tokens:,.0f}, max: {max_chunk_tokens:,} tokens, "
            f"total: {total_chunk_tokens:,} tokens)"
        )
        
        return valid_chunks


def chunk_content(content: str, config: ChunkingConfig = None) -> List[Chunk]:
    """
    Função de conveniência para dividir conteúdo em chunks.
    
    Args:
        content: Conteúdo para dividir
        config: Configuração opcional (usa singleton se None)
    
    Returns:
        Lista de Chunks
    """
    from .config import get_chunking_config
    
    if config is None:
        config = get_chunking_config()
    
    chunker = SmartChunker(config)
    return chunker.chunk_content(content)

