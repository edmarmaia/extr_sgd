"""Carrega a configuracao local dos sistemas consultados."""

import json
import os
import sys
from pathlib import Path


CONFIG_FILENAME = "config.local.json"


def _config_path() -> Path:
    configured = os.environ.get("EXTRATOR_SGD_CONFIG")
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CONFIG_FILENAME
    return Path(__file__).resolve().parent / CONFIG_FILENAME


def _load_config() -> dict:
    path = _config_path()
    if not path.is_file():
        raise RuntimeError(
            f"Configuracao ausente: {path}. "
            "Crie config.local.json a partir de config.example.json."
        )
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Nao foi possivel ler a configuracao: {path}") from exc

    required_urls = ("status_url", "denial_report_url")
    for key in required_urls:
        value = config.get(key)
        if not isinstance(value, str) or not value.startswith(("http://", "https://")):
            raise RuntimeError(f"Valor invalido em {key}: informe uma URL HTTP ou HTTPS.")

    required_maps = ("denial_departments", "schedule_departments")
    for key in required_maps:
        value = config.get(key)
        if not isinstance(value, dict) or not value:
            raise RuntimeError(f"Valor invalido em {key}: informe ao menos um departamento.")
        if not all(isinstance(name, str) and isinstance(code, str) for name, code in value.items()):
            raise RuntimeError(f"Valor invalido em {key}: nomes e codigos devem ser textos.")
    return config


_CONFIG = _load_config()
STATUS_URL: str = _CONFIG["status_url"]
DENIAL_REPORT_URL: str = _CONFIG["denial_report_url"]
DENIAL_DEPARTMENTS: dict[str, str] = _CONFIG["denial_departments"]
SCHEDULE_DEPARTMENTS: dict[str, str] = _CONFIG["schedule_departments"]
