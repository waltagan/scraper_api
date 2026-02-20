"""
Conexão assíncrona com PostgreSQL via asyncpg.
"""
import os
import asyncpg
from typing import Optional
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

# Pool global de conexões
_pool: Optional[asyncpg.Pool] = None

# Schema padrão do banco de dados
DB_SCHEMA = "busca_fornecedor"


async def get_pool() -> asyncpg.Pool:
    """
    Retorna pool de conexões (singleton).
    Cria pool na primeira chamada.
    Configura o search_path para garantir que o schema correto seja usado.
    
    Returns:
        asyncpg.Pool: Pool de conexões assíncrono
        
    Raises:
        Exception: Se não conseguir criar o pool
    """
    global _pool
    if _pool is None:
        try:
            # Função para configurar search_path em cada conexão
            async def init_connection(conn):
                """
                Configura search_path para cada conexão do pool.
                Executado automaticamente pelo asyncpg quando uma nova conexão é criada.
                
                IMPORTANTE: Schema sem aspas no SET search_path (foi criado sem aspas).
                """
                try:
                    # Schema sem aspas no SET search_path (foi criado sem aspas)
                    await conn.execute(f'SET search_path TO {DB_SCHEMA}, public')
                    logger.debug(f"✅ Search path configurado: {DB_SCHEMA}")
                except Exception as e:
                    # Se falhar, a conexão não será adicionada ao pool
                    logger.error(f"❌ Erro crítico ao configurar search_path no init_connection: {e}")
                    raise
            
            pool_min = int(os.getenv("DATABASE_POOL_MIN_SIZE", "5"))
            pool_max = int(os.getenv("DATABASE_POOL_MAX_SIZE", "50"))
            _pool = await asyncpg.create_pool(
                settings.DATABASE_URL,
                min_size=pool_min,
                max_size=pool_max,
                command_timeout=60,
                init=init_connection,
            )
            logger.info(f"✅ Pool asyncpg criado (min={pool_min}, max={pool_max}, schema={DB_SCHEMA})")
        except Exception as e:
            logger.error(f"❌ Erro ao criar pool asyncpg: {e}")
            raise
    return _pool


async def close_pool():
    """
    Fecha pool de conexões (chamar no shutdown).
    """
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("🔌 Pool asyncpg fechado")


async def test_connection() -> bool:
    """
    Testa a conexão com o banco de dados.
    
    Returns:
        bool: True se a conexão está funcionando
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            return result == 1
    except Exception as e:
        logger.error(f"❌ Erro ao testar conexão: {e}")
        return False

