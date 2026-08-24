# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
EXPORT_DIR = DATA_DIR / "exports"
_xlsx_env = os.getenv("TRANSLATION_XLSX", "")
if _xlsx_env:
    _xlsx_env_path = Path(_xlsx_env)
    XLSX_PATH = _xlsx_env_path if _xlsx_env_path.is_absolute() else ROOT / _xlsx_env_path
else:
    # 兼容本地中文文件名；Vercel 打包 ASCII 文件名更稳，fallback 自动识别
    XLSX_PATH = ROOT / "翻译库.xlsx" if (ROOT / "翻译库.xlsx").exists() else ROOT / "translation.xlsx"

if os.getenv("VERCEL"):
    DATA_DIR = Path(os.getenv("DATA_DIR", "/tmp/data"))
    EXPORT_DIR = DATA_DIR / "exports"

_default_db = DATA_DIR / "translation.db"
if os.getenv("VERCEL"):
    _default_db = Path("/tmp/translation.db")
DB_PATH = Path(os.getenv("DATABASE_PATH", _default_db))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")

SKILLS_DIR = ROOT / "skills"
WEB_DIR = ROOT / "web"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.parent != Path("/tmp"):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
