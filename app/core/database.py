"""
Conexão assíncrona com PostgreSQL via asyncpg.
"""
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
                await conn.execute(f'SET search_path TO "{DB_SCHEMA}", public')
                logger.debug(f"🔍 Search path configurado para: {DB_SCHEMA}")
            
            _pool = await asyncpg.create_pool(
                settings.DATABASE_URL,
                min_size=5,
                max_size=20,
                command_timeout=60,
                # Configurar init para definir search_path em cada conexão
                init=init_connection,
            )
            logger.info(f"✅ Pool asyncpg criado (min=5, max=20, schema={DB_SCHEMA})")
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

