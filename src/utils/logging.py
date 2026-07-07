"""
Configuración de logging del proyecto.

Provee una función `get_logger(name)` que devuelve un logger configurado con
la configuración declarada en `config/logging_config.yaml`. La primera llamada
inicializa la configuración global.
"""
from __future__ import annotations

import logging
import logging.config
from pathlib import Path

import yaml

from config import settings

_CONFIGURED = False


def _configure() -> None:
    """Carga la configuración de logging desde el YAML. Idempotente."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings.paths.log_dir.mkdir(parents=True, exist_ok=True)

    config_path = settings.project_root / "config" / "logging_config.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Reescribir rutas de archivos de log con paths absolutos
    for handler in cfg.get("handlers", {}).values():
        if "filename" in handler:
            handler["filename"] = str(
                settings.project_root / handler["filename"]
            )

    logging.config.dictConfig(cfg)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Devuelve un logger configurado. Uso: `logger = get_logger(__name__)`."""
    _configure()
    return logging.getLogger(name)
