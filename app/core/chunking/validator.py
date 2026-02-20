"""
Validator - Validação final de chunks.

Responsável por validar chunks antes do envio ao LLM e aplicar
correções automáticas quando necessário (sempre dividindo, nunca truncando).
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from app.core.token_utils import estimate_tokens

from .chunker import SmartChunker, Chunk
from .config import ChunkingConfig

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """
    Resultado da validação de um chunk.
    
    Atributos:
        is_valid: Se o chunk está dentro dos limites
        tokens: Número de tokens do chunk
        max_allowed: Limite máximo permitido
        issues: Lista de problemas encontrados
    """
    
    is_valid: bool
    tokens: int
    max_allowed: int
    issues: List[str] = None
    
    def __post_init__(self):
        if self.issues is None:
            self.issues = []
    
    def __str__(self) -> str:
        status = "✅ VÁLIDO" if self.is_valid else "❌ INVÁLIDO"
        return (
            f"ValidationResult({status}, {self.tokens:,}/{self.max_allowed:,} tokens, "
            f"{len(self.issues)} issues)"
        )


@dataclass
class BatchValidationResult:
    """
    Resultado da validação de múltiplos chunks.
    
    Atributos:
        valid_chunks: Lista de chunks válidos
        invalid_count: Número de chunks inválidos
        corrected_count: Número de chunks corrigidos
        total_chunks: Total de chunks processados
    """
    
    valid_chunks: List[Chunk]
    invalid_count: int
    corrected_count: int
    total_chunks: int
    
    def __str__(self) -> str:
        return (
            f"BatchValidationResult({self.total_chunks} total, "
            f"{len(self.valid_chunks)} válidos, "
            f"{self.invalid_count} inválidos, "
            f"{self.corrected_count} corrigidos)"
        )


class ChunkValidator:
    """
    Validador de chunks com capacidade de correção automática.
    
    Valida chunks e aplica correções (divisão) quando necessário.
    NUNCA trunca conteúdo - sempre divide para preservar 100% das informações.
    """
    
    def __init__(self, config: ChunkingConfig):
        """
        Inicializa o validador.
        
        Args:
            config: Configuração de chunking
        """
        self.config = config
        self.effective_max_tokens = config.effective_max_tokens
        self.max_chunk_tokens = config.max_chunk_tokens
        self.min_chunk_chars = config.min_chunk_chars
    
    def validate_chunk(self, chunk: Chunk) -> ValidationResult:
        """
        Valida um chunk individual.
        
        Verificações:
        1. Tokens <= effective_max_tokens
        2. Conteúdo não vazio
        3. Mínimo de caracteres úteis
        
        Args:
            chunk: Chunk para validar
        
        Returns:
            ValidationResult com resultado da validação
        """
        issues = []
        
        # Contar tokens
        tokens = chunk.tokens
        
        # Verificar limite de tokens (usar effective_max como padrão)
        max_allowed = self.effective_max_tokens
        
        if tokens > max_allowed:
            issues.append(
                f"Chunk excede effective_max_tokens: {tokens:,} > {max_allowed:,}"
            )
        
        # Verificar limite absoluto também
        if tokens > self.max_chunk_tokens:
            issues.append(
                f"Chunk excede max_chunk_tokens: {tokens:,} > {self.max_chunk_tokens:,}"
            )
        
        # Verificar conteúdo não vazio
        content = chunk.content
        if not content or not content.strip():
            issues.append("Chunk está vazio ou contém apenas whitespace")
        
        # Verificar mínimo de caracteres úteis
        stripped_content = content.strip()
        if len(stripped_content) < self.min_chunk_chars:
            issues.append(
                f"Chunk muito pequeno: {len(stripped_content)} < {self.min_chunk_chars} chars"
            )
        
        is_valid = len(issues) == 0
        
        result = ValidationResult(
            is_valid=is_valid,
            tokens=tokens,
            max_allowed=max_allowed,
            issues=issues,
        )
        
        if not is_valid:
            logger.debug(f"Chunk {chunk.index} inválido: {', '.join(issues)}")
        
        return result
    
    def enforce_limit(self, chunk_content: str, max_tokens: int, _depth: int = 0) -> List[str]:
        """
        Garante que conteúdo não exceda limite, dividindo se necessário.
        
        NUNCA trunca - sempre divide preservando 100% do conteúdo.
        
        Args:
            chunk_content: Conteúdo do chunk
            max_tokens: Limite máximo de tokens
            _depth: Controle interno de profundidade de recursao
        
        Returns:
            Lista de chunks divididos (pode ser lista com 1 elemento se já está OK)
        """
        MAX_DEPTH = 5
        tokens = estimate_tokens(chunk_content, include_overhead=False)
        
        if tokens <= max_tokens:
            return [chunk_content]
        
        if _depth >= MAX_DEPTH:
            logger.warning(
                f"Recursão máxima ({MAX_DEPTH}) atingida com {tokens:,} tokens. "
                f"Forçando split binário por caracteres."
            )
            mid = len(chunk_content) // 2
            space_pos = chunk_content.rfind(' ', mid - 500, mid + 500)
            if space_pos > 0:
                mid = space_pos
            left = chunk_content[:mid]
            right = chunk_content[mid:]
            result = []
            for part in (left, right):
                if part.strip():
                    result.extend(self.enforce_limit(part, max_tokens, _depth + 1))
            return result if result else [chunk_content]
        
        logger.warning(
            f"Conteúdo excede limite ({tokens:,} > {max_tokens:,} tokens), dividindo..."
        )
        
        temp_chunker = SmartChunker(self.config)
        divided_chunks = temp_chunker._split_large_page(chunk_content, max_tokens)
        
        final_chunks = []
        for i, sub_chunk in enumerate(divided_chunks):
            sub_tokens = estimate_tokens(sub_chunk, include_overhead=False)
            
            if sub_tokens > max_tokens:
                logger.warning(
                    f"Sub-chunk {i+1} ainda excede ({sub_tokens:,} > {max_tokens:,}), "
                    f"dividindo recursivamente..."
                )
                recursive_chunks = self.enforce_limit(sub_chunk, max_tokens, _depth + 1)
                final_chunks.extend(recursive_chunks)
            else:
                final_chunks.append(sub_chunk)
        
        logger.info(
            f"Conteúdo dividido de {tokens:,} tokens em {len(final_chunks)} chunks válidos"
        )
        
        return final_chunks
    
    def validate_all(self, chunks: List[Chunk]) -> BatchValidationResult:
        """
        Valida todos os chunks e aplica correções automaticamente.
        
        Chunks inválidos são divididos recursivamente até ficarem válidos.
        
        Args:
            chunks: Lista de chunks para validar
        
        Returns:
            BatchValidationResult com chunks válidos
        """
        if not chunks:
            return BatchValidationResult(
                valid_chunks=[],
                invalid_count=0,
                corrected_count=0,
                total_chunks=0,
            )
        
        valid_chunks = []
        invalid_count = 0
        corrected_count = 0
        
        for chunk in chunks:
            validation = self.validate_chunk(chunk)
            
            if validation.is_valid:
                # Chunk válido, adicionar diretamente
                valid_chunks.append(chunk)
            else:
                # Chunk inválido, tentar corrigir
                invalid_count += 1
                
                logger.warning(
                    f"Chunk {chunk.index}/{chunk.total_chunks} inválido: "
                    f"{', '.join(validation.issues)}"
                )
                
                # Dividir chunk para corrigir
                divided_contents = self.enforce_limit(
                    chunk.content,
                    self.effective_max_tokens
                )
                
                if len(divided_contents) > 1:
                    corrected_count += 1
                    logger.info(
                        f"Chunk {chunk.index} dividido em {len(divided_contents)} chunks válidos"
                    )
                
                # Criar novos chunks a partir do conteúdo dividido
                for i, content in enumerate(divided_contents):
                    sub_tokens = estimate_tokens(content, include_overhead=False)
                    
                    # Extrair páginas (copiar do chunk original)
                    pages_included = chunk.pages_included.copy() if chunk.pages_included else []
                    
                    sub_chunk = Chunk(
                        content=content,
                        tokens=sub_tokens,
                        index=len(valid_chunks) + i + 1,
                        total_chunks=0,  # Será atualizado depois
                        pages_included=pages_included,
                    )
                    
                    valid_chunks.append(sub_chunk)
        
        # Atualizar total_chunks em todos os chunks
        total_valid = len(valid_chunks)
        for chunk in valid_chunks:
            chunk.total_chunks = total_valid
        
        result = BatchValidationResult(
            valid_chunks=valid_chunks,
            invalid_count=invalid_count,
            corrected_count=corrected_count,
            total_chunks=len(chunks),
        )
        
        if invalid_count > 0:
            logger.info(
                f"Validação: {result.total_chunks} chunks → {len(result.valid_chunks)} válidos "
                f"({invalid_count} inválidos, {corrected_count} corrigidos)"
            )
        else:
            logger.debug(f"Validação: Todos os {result.total_chunks} chunks são válidos")
        
        return result


def validate_chunks(chunks: List[Chunk], config: ChunkingConfig = None) -> List[Chunk]:
    """
    Função de conveniência para validar chunks.
    
    Args:
        chunks: Lista de chunks para validar
        config: Configuração opcional (usa singleton se None)
    
    Returns:
        Lista de chunks válidos (com correções aplicadas se necessário)
    """
    from .config import get_chunking_config
    
    if config is None:
        config = get_chunking_config()
    
    validator = ChunkValidator(config)
    result = validator.validate_all(chunks)
    return result.valid_chunks

