# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.config import DB_PATH, TURSO_AUTH_TOKEN, TURSO_DATABASE_URL, ensure_dirs
from app.constants import HIT_GLOSSARY, HIT_TM, LANGS
from app.kb.normalize import cell_str, is_empty_trans, zh_norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS glossary (
  zh TEXT PRIMARY KEY,
  zh_norm TEXT NOT NULL,
  en TEXT DEFAULT '',
  fr TEXT DEFAULT '',
  de TEXT DEFAULT '',
  it TEXT DEFAULT '',
  pl TEXT DEFAULT '',
  es TEXT DEFAULT '',
  pt TEXT DEFAULT '',
  source_version TEXT DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_glossary_norm ON glossary(zh_norm);

CREATE TABLE IF NOT EXISTS tm (
  zh TEXT PRIMARY KEY,
  zh_norm TEXT NOT NULL,
  en TEXT DEFAULT '',
  fr TEXT DEFAULT '',
  de TEXT DEFAULT '',
  it TEXT DEFAULT '',
  pl TEXT DEFAULT '',
  es TEXT DEFAULT '',
  pt TEXT DEFAULT '',
  ui_type TEXT DEFAULT '',
  source_version TEXT DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tm_norm ON tm(zh_norm);

CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  pending_json TEXT DEFAULT '[]',
  last_result_json TEXT DEFAULT '{}',
  overwrite_json TEXT DEFAULT '[]',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS request_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  zh TEXT,
  ui_type TEXT DEFAULT '',
  hit_source TEXT,
  is_new INTEGER DEFAULT 0,
  confirmed INTEGER DEFAULT 0,
  deepseek_failed INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL,
  zh TEXT,
  table_name TEXT,
  payload_json TEXT,
  session_id TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_bases (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _langs_from_row(row: sqlite3.Row) -> dict[str, str]:
    return {k: cell_str(row[k]) for k in LANGS}


def _missing(langs: dict[str, str]) -> list[str]:
    return [k for k in LANGS if is_empty_trans(langs.get(k, ""))]


@dataclass
class Entry:
    zh: str
    langs: dict[str, str]
    source: str
    source_version: str = ""
    stored_zh: str = ""

    @property
    def missing(self) -> list[str]:
        return _missing(self.langs)

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass
class SessionState:
    pending: list[dict[str, Any]] = field(default_factory=list)
    last_result: dict[str, Any] = field(default_factory=dict)
    overwrite: list[dict[str, Any]] = field(default_factory=list)


class Store:
    def __init__(self, path: Path | None = None) -> None:
        ensure_dirs()
        self.path = Path(path) if path else DB_PATH
        self._lock = threading.Lock()
        self._conn = self._connect()
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        self._conn.executescript(SCHEMA)
        self._ensure_kb_column()
        self._conn.commit()
        self.ensure_kb("pitpat-dict", "七国语言词典", "已确认的中文与英/法/德/意/波/西/葡译文，供对话复用。")

    def _connect(self) -> sqlite3.Connection:
        if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
            try:
                import libsql  # type: ignore

                conn = libsql.connect(
                    str(self.path),
                    sync_url=TURSO_DATABASE_URL,
                    auth_token=TURSO_AUTH_TOKEN,
                )
                return conn
            except Exception:
                pass
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self.path), check_same_thread=False)

    def close(self) -> None:
        self._conn.close()

    def _ensure_kb_column(self) -> None:
        for table in ("glossary", "tm"):
            cols = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if "kb_id" not in cols:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN kb_id TEXT NOT NULL DEFAULT 'pitpat-dict'"
                )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_glossary_kb ON glossary(kb_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tm_kb ON tm(kb_id)")

    def ensure_kb(self, kb_id: str, name: str, description: str = "") -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO knowledge_bases (id, name, description, created_at)
               VALUES (?, ?, ?, ?)""",
            (kb_id, name, description, _now()),
        )
        if kb_id == "pitpat-dict":
            self._conn.execute(
                "UPDATE knowledge_bases SET name = ?, description = ? WHERE id = ?",
                (name, description, kb_id),
            )
        self._conn.commit()

    def list_kbs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, name, description, created_at FROM knowledge_bases ORDER BY created_at"
        ).fetchall()
        out = []
        for r in rows:
            g = self._conn.execute(
                "SELECT COUNT(*) FROM glossary WHERE kb_id = ?", (r["id"],)
            ).fetchone()[0]
            t = self._conn.execute(
                "SELECT COUNT(*) FROM tm WHERE kb_id = ?", (r["id"],)
            ).fetchone()[0]
            out.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "description": r["description"] or "",
                    "created_at": r["created_at"],
                    "glossary_count": int(g),
                    "tm_count": int(t),
                }
            )
        return out

    def save_kb(self, kb_id: str, name: str, description: str = "", *, is_new: bool = False) -> dict[str, Any]:
        kid = cell_str(kb_id)
        if not kid:
            raise ValueError("知识库 ID 不能为空")
        existing = self._conn.execute(
            "SELECT id FROM knowledge_bases WHERE id = ?", (kid,)
        ).fetchone()
        if is_new and existing:
            raise ValueError("知识库 ID 已存在")
        if not is_new and not existing:
            raise FileNotFoundError("知识库不存在")
        if is_new:
            self._conn.execute(
                "INSERT INTO knowledge_bases (id, name, description, created_at) VALUES (?, ?, ?, ?)",
                (kid, name, description, _now()),
            )
        else:
            self._conn.execute(
                "UPDATE knowledge_bases SET name = ?, description = ? WHERE id = ?",
                (name, description, kid),
            )
        self._conn.commit()
        return next(x for x in self.list_kbs() if x["id"] == kid)

    def delete_kb(self, kb_id: str) -> None:
        if kb_id == "pitpat-dict":
            raise ValueError("默认知识库不能删除")
        with self._lock:
            self._conn.execute("DELETE FROM glossary WHERE kb_id = ?", (kb_id,))
            self._conn.execute("DELETE FROM tm WHERE kb_id = ?", (kb_id,))
            self._conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
            self._conn.commit()

    def list_entries(
        self, table: str, *, kb_id: str = "pitpat-dict", q: str = "", limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        if table not in {"glossary", "tm"}:
            raise ValueError("table")
        where = "kb_id = ?"
        args: list[Any] = [kb_id]
        if cell_str(q):
            where += " AND zh LIKE ?"
            args.append(f"%{cell_str(q)}%")
        total = self._conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}", args
        ).fetchone()[0]
        rows = self._conn.execute(
            f"SELECT * FROM {table} WHERE {where} ORDER BY zh LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
        items = []
        for row in rows:
            item = {"zh": row["zh"], "source_version": cell_str(row["source_version"])}
            for k in LANGS:
                item[k] = cell_str(row[k])
            items.append(item)
        return {"total": int(total), "items": items}

    def delete_entry(self, table: str, zh: str, *, kb_id: str = "pitpat-dict") -> None:
        if table not in {"glossary", "tm"}:
            raise ValueError("table")
        with self._lock:
            self._conn.execute(
                f"DELETE FROM {table} WHERE kb_id = ? AND zh = ?", (kb_id, zh)
            )
            self._conn.commit()

    def counts(self) -> tuple[int, int]:
        g = self._conn.execute("SELECT COUNT(*) FROM glossary").fetchone()[0]
        t = self._conn.execute("SELECT COUNT(*) FROM tm").fetchone()[0]
        return int(g), int(t)

    def _get_by_zh(self, table: str, zh: str, kb_id: str = "pitpat-dict") -> sqlite3.Row | None:
        return self._conn.execute(
            f"SELECT * FROM {table} WHERE kb_id = ? AND zh = ?", (kb_id, zh)
        ).fetchone()

    def _get_by_norm(self, table: str, norm: str, kb_id: str = "pitpat-dict") -> sqlite3.Row | None:
        return self._conn.execute(
            f"SELECT * FROM {table} WHERE kb_id = ? AND zh_norm = ? ORDER BY zh LIMIT 1",
            (kb_id, norm),
        ).fetchone()

    def list_glossary_entries(self, kb_id: str = "pitpat-dict") -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM glossary WHERE kb_id = ?", (kb_id,)
        ).fetchall()
        return [{"zh": cell_str(row["zh"]), "langs": _langs_from_row(row)} for row in rows]

    def lookup(self, zh: str, kb_id: str = "pitpat-dict") -> Entry | None:
        raw = cell_str(zh)
        if not raw:
            return None
        norm = zh_norm(raw)
        with self._lock:
            row = self._get_by_zh("glossary", raw, kb_id)
            if row is None and norm:
                row = self._get_by_norm("glossary", norm, kb_id)
            if row is not None:
                return Entry(
                    zh=raw,
                    langs=_langs_from_row(row),
                    source=HIT_GLOSSARY,
                    source_version=cell_str(row["source_version"]),
                    stored_zh=cell_str(row["zh"]),
                )
            row = self._get_by_zh("tm", raw, kb_id)
            if row is None and norm:
                row = self._get_by_norm("tm", norm, kb_id)
            if row is not None:
                return Entry(
                    zh=raw,
                    langs=_langs_from_row(row),
                    source=HIT_TM,
                    source_version=cell_str(row["source_version"]),
                    stored_zh=cell_str(row["zh"]),
                )
        return None

    def exists(self, zh: str, kb_id: str = "pitpat-dict") -> dict[str, bool]:
        raw = cell_str(zh)
        norm = zh_norm(raw)
        with self._lock:
            g = self._get_by_zh("glossary", raw, kb_id) or self._get_by_norm("glossary", norm, kb_id)
            t = self._get_by_zh("tm", raw, kb_id) or self._get_by_norm("tm", norm, kb_id)
        return {"glossary": g is not None, "tm": t is not None}

    def upsert(
        self,
        table: str,
        zh: str,
        langs: dict[str, str],
        *,
        overwrite: bool = False,
        source_version: str = "",
        ui_type: str = "",
        kb_id: str = "pitpat-dict",
    ) -> str:
        """Returns insert | ignore | update."""
        raw = cell_str(zh)
        norm = zh_norm(raw)
        now = _now()
        cols = ", ".join(LANGS)
        placeholders = ", ".join("?" for _ in LANGS)
        values = [cell_str(langs.get(k, "")) for k in LANGS]
        with self._lock:
            existing = self._get_by_zh(table, raw, kb_id) or self._get_by_norm(table, norm, kb_id)
            if existing is not None and not overwrite:
                return "ignore"
            if existing is not None and overwrite:
                sets = ", ".join(f"{k} = ?" for k in LANGS)
                extra = ""
                extra_vals: list[Any] = []
                if table == "tm":
                    extra = ", ui_type = ?"
                    extra_vals.append(ui_type)
                self._conn.execute(
                    f"UPDATE {table} SET {sets}{extra}, source_version = ?, updated_at = ?, zh_norm = ? WHERE kb_id = ? AND zh = ?",
                    [*values, *extra_vals, source_version, now, norm, kb_id, existing["zh"]],
                )
                self._conn.commit()
                return "update"
            if table == "glossary":
                self._conn.execute(
                    f"INSERT INTO glossary (kb_id, zh, zh_norm, {cols}, source_version, updated_at) VALUES (?, ?, ?, {placeholders}, ?, ?)",
                    [kb_id, raw, norm, *values, source_version, now],
                )
            else:
                self._conn.execute(
                    f"INSERT INTO tm (kb_id, zh, zh_norm, {cols}, ui_type, source_version, updated_at) VALUES (?, ?, ?, {placeholders}, ?, ?, ?)",
                    [kb_id, raw, norm, *values, ui_type, source_version, now],
                )
            self._conn.commit()
            return "insert"

    def bulk_insert(self, table: str, rows: Iterable[dict[str, str]], kb_id: str = "pitpat-dict") -> int:
        now = _now()
        n = 0
        with self._lock:
            for item in rows:
                zh = cell_str(item.get("zh"))
                if not zh:
                    continue
                langs = {k: cell_str(item.get(k, "")) for k in LANGS}
                if all(is_empty_trans(v) for v in langs.values()):
                    continue
                try:
                    if table == "glossary":
                        self._conn.execute(
                            """INSERT OR IGNORE INTO glossary
                            (kb_id, zh, zh_norm, en, fr, de, it, pl, es, pt, source_version, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            [
                                kb_id,
                                zh,
                                zh_norm(zh),
                                langs["en"],
                                langs["fr"],
                                langs["de"],
                                langs["it"],
                                langs["pl"],
                                langs["es"],
                                langs["pt"],
                                cell_str(item.get("source_version")),
                                now,
                            ],
                        )
                    else:
                        self._conn.execute(
                            """INSERT OR IGNORE INTO tm
                            (kb_id, zh, zh_norm, en, fr, de, it, pl, es, pt, ui_type, source_version, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            [
                                kb_id,
                                zh,
                                zh_norm(zh),
                                langs["en"],
                                langs["fr"],
                                langs["de"],
                                langs["it"],
                                langs["pl"],
                                langs["es"],
                                langs["pt"],
                                cell_str(item.get("ui_type")),
                                cell_str(item.get("source_version")),
                                now,
                            ],
                        )
                    n += 1
                except sqlite3.Error:
                    continue
            self._conn.commit()
        return n

    def get_session(self, session_id: str) -> SessionState:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return SessionState()
        return SessionState(
            pending=json.loads(row["pending_json"] or "[]"),
            last_result=json.loads(row["last_result_json"] or "{}"),
            overwrite=json.loads(row["overwrite_json"] or "[]"),
        )

    def save_session(self, session_id: str, state: SessionState) -> None:
        now = _now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO sessions (session_id, pending_json, last_result_json, overwrite_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                     pending_json = excluded.pending_json,
                     last_result_json = excluded.last_result_json,
                     overwrite_json = excluded.overwrite_json,
                     updated_at = excluded.updated_at""",
                [
                    session_id,
                    json.dumps(state.pending, ensure_ascii=False),
                    json.dumps(state.last_result, ensure_ascii=False),
                    json.dumps(state.overwrite, ensure_ascii=False),
                    now,
                ],
            )
            self._conn.commit()

    def log_request(
        self,
        session_id: str,
        zh: str,
        hit_source: str,
        *,
        ui_type: str = "",
        is_new: bool = False,
        deepseek_failed: bool = False,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO request_log
                (session_id, zh, ui_type, hit_source, is_new, confirmed, deepseek_failed, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
                [session_id, zh, ui_type, hit_source, int(is_new), int(deepseek_failed), _now()],
            )
            self._conn.commit()

    def mark_confirmed(self, session_id: str, zh_list: list[str]) -> None:
        if not zh_list:
            return
        with self._lock:
            for zh in zh_list:
                self._conn.execute(
                    """UPDATE request_log SET confirmed = 1
                       WHERE id = (
                         SELECT id FROM request_log
                         WHERE session_id = ? AND zh = ?
                         ORDER BY id DESC LIMIT 1
                       )""",
                    (session_id, zh),
                )
            self._conn.commit()

    def audit(
        self,
        action: str,
        zh: str,
        table_name: str,
        payload: dict[str, Any],
        session_id: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO audit_log (action, zh, table_name, payload_json, session_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    action,
                    zh,
                    table_name,
                    json.dumps(payload, ensure_ascii=False),
                    session_id,
                    _now(),
                ],
            )
            self._conn.commit()

    def stats(self) -> dict[str, Any]:
        total = self._conn.execute("SELECT COUNT(*) FROM request_log").fetchone()[0]
        hits = self._conn.execute(
            "SELECT COUNT(*) FROM request_log WHERE hit_source IN ('glossary', 'tm')"
        ).fetchone()[0]
        news = self._conn.execute(
            "SELECT COUNT(*) FROM request_log WHERE is_new = 1"
        ).fetchone()[0]
        confirmed = self._conn.execute(
            "SELECT COUNT(*) FROM request_log WHERE confirmed = 1"
        ).fetchone()[0]
        failed = self._conn.execute(
            "SELECT COUNT(*) FROM request_log WHERE deepseek_failed = 1"
        ).fetchone()[0]
        g, t = self.counts()
        return {
            "total_lookups": int(total),
            "hits": int(hits),
            "hit_rate": round(hits / total, 4) if total else 0.0,
            "new_translations": int(news),
            "confirmed": int(confirmed),
            "deepseek_failed": int(failed),
            "glossary_count": g,
            "tm_count": t,
        }
