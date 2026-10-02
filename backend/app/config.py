"""Settings loaded from the repo-root .env file.

Paths in .env are resolved relative to the repo root, so the backend can be
started from any working directory.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DATA_DIR = BACKEND / "data"
DOC_CACHE_DIR = DATA_DIR / "documents"
OCR_CACHE_DIR = DATA_DIR / "ocr"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT / ".env", override=False)


class ConfigError(RuntimeError):
    pass


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def require(name: str, why: str) -> str:
    value = env(name)
    if not value:
        raise ConfigError(f"{name} is empty in .env. It is needed for {why}. Paste a value next to {name}= in {ROOT / '.env'}.")
    return value


def resolve_path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (ROOT / p).resolve()


def database_path() -> Path:
    url = env("DATABASE_URL", "sqlite:///./clearcase.db")
    if not url.startswith("sqlite:///"):
        raise ConfigError("Only sqlite:/// DATABASE_URLs are supported.")
    return resolve_path(url[len("sqlite:///"):])


def firm_name() -> str:
    return env("FIRM_NAME") or "Your Firm"


def clio_source() -> str:
    return env("CLIO_SOURCE", "live").lower()


def clio_base_url() -> str:
    return env("CLIO_REGION_BASE_URL", "https://app.clio.com").rstrip("/")


def mirror_path() -> Path:
    return resolve_path(env("SAPINI_MIRROR_PATH", "../Sapini Case Materials/sapini-clio-data.json"))


def signing_key_path() -> Path:
    return resolve_path(env("SIGNING_KEY_PATH", "./secrets/firm_ed25519.pem"))


def public_base_url() -> str:
    return env("PUBLIC_BASE_URL", "http://localhost:5173").rstrip("/")
