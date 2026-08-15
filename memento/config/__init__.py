"""Configuration: settings (paths + user config) and prompts."""

from . import prompts
from .settings import (
    BASE_DIR,
    CONFIG_PATH,
    DB_PATH,
    DEFAULTS,
    LAUNCH_LABEL,
    LOG_PATH,
    MCP_DEFAULT_HOST,
    MCP_DEFAULT_PORT,
    ensure_base,
    load_config,
    save_config,
)

__all__ = [
    "prompts",
    "BASE_DIR", "DB_PATH", "CONFIG_PATH", "LOG_PATH", "DEFAULTS",
    "LAUNCH_LABEL", "MCP_DEFAULT_HOST", "MCP_DEFAULT_PORT",
    "ensure_base", "load_config", "save_config",
]
