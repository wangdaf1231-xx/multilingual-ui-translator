# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from app.constants import LANGS
from app.kb.normalize import is_empty_trans, zh_norm


def _complete(langs: dict[str, str]) -> bool:
    return all(not is_empty_trans(langs.get(k, "")) for k in LANGS)


def extract_glossary_terms(zh: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从句子里抠出术语库短词：最长优先、互不重叠。不扫描翻译记忆。"""
    text = zh_norm(zh)
    if not text:
        return []
    candidates: list[tuple[int, int, dict[str, Any], str]] = []
    for e in entries:
        raw = (e.get("zh") or "").strip()
        langs = e.get("langs") or {}
        needle = zh_norm(raw)
        if not needle or needle == text:
            continue
        if not _complete(langs):
            continue
        pos = text.find(needle)
        if pos < 0:
            continue
        candidates.append((len(needle), pos, e, needle))
    candidates.sort(key=lambda x: (-x[0], x[1]))
    occupied = [False] * len(text)
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _nlen, _pos, e, needle in candidates:
        start = 0
        hit_at = -1
        while True:
            i = text.find(needle, start)
            if i < 0:
                break
            if not any(occupied[i : i + len(needle)]):
                for j in range(i, i + len(needle)):
                    occupied[j] = True
                hit_at = i
                break
            start = i + 1
        if hit_at < 0:
            continue
        key = zh_norm(e.get("zh") or "")
        if key in seen:
            continue
        seen.add(key)
        picked.append({"zh": e["zh"], "langs": dict(e["langs"]), "_at": hit_at})
    picked.sort(key=lambda x: x["_at"])
    for item in picked:
        item.pop("_at", None)
    return picked
