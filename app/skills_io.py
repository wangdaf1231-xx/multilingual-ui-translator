# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from app.config import SKILLS_DIR
from app.constants import KB_ID, SKILL_ID
from app.kb.normalize import cell_str

TOOLS = ("lookup", "translate", "confirm_write", "export_xlsx")


def _slug(text: str) -> str:
    s = cell_str(text).lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "skill"


def _path(skill_id: str) -> Path:
    return SKILLS_DIR / f"{skill_id}.yaml"


def _read(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sid = data.get("id") or path.stem
    return {
        "id": sid,
        "name": data.get("name") or sid,
        "description": data.get("description") or "",
        "system_prompt": data.get("system_prompt") or "",
        "tools": list(data.get("tools") or list(TOOLS)),
        "kb_ids": list(data.get("kb_ids") or [KB_ID]),
        "scope": data.get("scope") or "space",
    }


def list_skills() -> list[dict[str, Any]]:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    items = [_read(p) for p in sorted(SKILLS_DIR.glob("*.yaml"))]
    return items


def get_skill(skill_id: str) -> dict[str, Any] | None:
    path = _path(skill_id)
    if not path.exists():
        return None
    return _read(path)


def save_skill(payload: dict[str, Any], *, is_new: bool = False) -> dict[str, Any]:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    sid = cell_str(payload.get("id")) or _slug(payload.get("name") or "")
    sid = re.sub(r"[^a-zA-Z0-9_-]+", "-", sid).strip("-") or "skill"
    path = _path(sid)
    if is_new and path.exists():
        raise ValueError("技能 ID 已存在")
    if not is_new and not path.exists():
        raise FileNotFoundError("技能不存在")
    data = {
        "id": sid,
        "name": cell_str(payload.get("name")) or sid,
        "description": cell_str(payload.get("description")),
        "scope": payload.get("scope") or "space",
        "tools": [t for t in (payload.get("tools") or TOOLS) if t in TOOLS] or list(TOOLS),
        "kb_ids": payload.get("kb_ids") or [KB_ID],
        "system_prompt": payload.get("system_prompt") or "",
    }
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return _read(path)


def delete_skill(skill_id: str) -> None:
    if skill_id == SKILL_ID:
        raise ValueError("默认技能不能删除")
    path = _path(skill_id)
    if not path.exists():
        raise FileNotFoundError("技能不存在")
    path.unlink()
