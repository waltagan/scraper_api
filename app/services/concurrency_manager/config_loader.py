import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Diretório padrão para arquivos de configuração (apenas JSON, sem código).
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "configs"

# Cache por arquivo para evitar re-leituras frequentes.
_CONFIG_CACHE: Dict[str, Dict[str, Any]] = {}


def load_config(name: str, *, use_cache: bool = True) -> Dict[str, Any]:
    """
    Carrega um arquivo JSON de configuração pelo nome (sem extensão).
    
    Exemplo: load_config("llm_limits") -> app/configs/llm_limits.json
    """
    global _CONFIG_CACHE

    if use_cache and name in _CONFIG_CACHE:
        return _CONFIG_CACHE[name]

    config_path = CONFIG_DIR / f"{name}.json"
    try:
        with open(config_path, "r") as f:
            data = json.load(f)
        if use_cache:
            _CONFIG_CACHE[name] = data
        return data
    except FileNotFoundError:
        logger.warning(f"[config_loader] Arquivo não encontrado: {config_path}")
    except Exception as exc:
        logger.warning(f"[config_loader] Erro ao carregar {config_path}: {exc}")
    return {}


def get_section(name: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Alias para carregar um arquivo de config. Mantém compatibilidade com chamadas existentes."""
    cfg = load_config(name)
    return cfg if cfg else (default or {})


def reset_cache() -> None:
    """Limpa cache em memória (útil para testes)."""
    global _CONFIG_CACHE
    _CONFIG_CACHE = {}
