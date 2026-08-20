# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx
import yaml

from dotenv import load_dotenv

from app.config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, ROOT, SKILLS_DIR
from app.constants import LANG_LABEL, LANGS, SKILL_ID
from app.kb.normalize import cell_str

JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def load_skill_prompt(skill_id: str = SKILL_ID) -> str:
    path = SKILLS_DIR / f"{skill_id}.yaml"
    if not path.exists():
        path = next(SKILLS_DIR.glob("*.yaml"), Path())
    if not path or not path.exists():
        return "你是移动端本地化专家。将中文译为英/法/德/意/波/西/葡。只输出 JSON。"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return cell_str(data.get("system_prompt"))


def list_skills() -> list[dict]:
    items = []
    if not SKILLS_DIR.exists():
        return items
    for path in sorted(SKILLS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        items.append(
            {
                "id": data.get("id") or path.stem,
                "name": data.get("name") or path.stem,
                "description": data.get("description") or "",
            }
        )
    return items


def _user_payload(items: list[dict], locked_terms: list[dict]) -> str:
    payload = {
        "task": "只翻译 items 里的中文。已有语言不要改。空字符串的语言必须补译。",
        "locked_terms": [
            {"zh": t["zh"], **{k: t.get(k, "") for k in LANGS}} for t in locked_terms
        ],
        "items": [
            {
                "zh": it["zh"],
                "ui_type": it.get("ui_type") or "正常翻译",
                "need": it.get("need") or list(LANGS),
            }
            for it in items
        ],
        "output_schema": {
            "items": [
                {
                    "zh": "原文",
                    "en": "",
                    "fr": "",
                    "de": "",
                    "it": "",
                    "pl": "",
                    "es": "",
                    "pt": "",
                }
            ]
        },
    }
    langs = "、".join(LANG_LABEL[k] for k in LANGS)
    return (
        f"目标语言：{langs}。必须返回 JSON 对象，键为 items 的数组。不要 Markdown。\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def translate_with_deepseek(
    items: list[dict],
    locked_terms: list[dict],
    skill_id: str = SKILL_ID,
) -> tuple[dict[str, dict[str, str]], str | None]:
    """Returns zh -> langs, error."""
    if not items:
        return {}, None
    load_dotenv(ROOT / ".env", override=True)
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {}, "未配置 DEEPSEEK_API_KEY"
    system = load_skill_prompt(skill_id)
    url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"
    body = {
        "model": DEEPSEEK_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": _user_payload(items, locked_terms)},
        ],
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client(timeout=90.0) as client:
            r = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            r.raise_for_status()
            data = r.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except httpx.HTTPStatusError as exc:
        return {}, f"DeepSeek 调用失败：HTTP {exc.response.status_code}"
    except Exception:
        return {}, "DeepSeek 调用失败"

    rows = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list):
        m = JSON_BLOCK.search(str(content) if "content" in dir() else "")
        if m:
            try:
                parsed = json.loads(m.group(0))
                rows = parsed.get("items", parsed)
            except Exception:
                rows = []
        else:
            rows = []
    out: dict[str, dict[str, str]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            zh = cell_str(row.get("zh"))
            if not zh:
                continue
            out[zh] = {k: cell_str(row.get(k, "")) for k in LANGS}
    return out, None
