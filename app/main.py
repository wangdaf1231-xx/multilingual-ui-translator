# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent.loop import AgentLoop, skill_catalog
from app.config import EXPORT_DIR, ROOT, WEB_DIR, ensure_dirs
from app.constants import KB_ID, LANGS, SKILL_ID
from app.kb.export_xlsx import export_kb
from app.kb.import_xlsx import import_xlsx
from app.kb.store import Store
from app.skills_io import delete_skill, get_skill, save_skill

_store: Store | None = None
_loop: AgentLoop | None = None
_import_stats: dict = {}


def get_store() -> Store:
    global _store, _loop, _import_stats
    if _store is None:
        ensure_dirs()
        _store = Store()
        g, t = _store.counts()
        if g == 0 and t == 0:
            _import_stats = import_xlsx(_store, kb_id=KB_ID)
        else:
            _import_stats = {"glossary": g, "tm": t, "skipped": 1}
        _loop = AgentLoop(_store)
    return _store


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_store()
    yield


app = FastAPI(title="多语言翻译助手", lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatIn(BaseModel):
    session_id: str = Field(min_length=4)
    message: str = ""
    skill_id: str = SKILL_ID
    kb_id: str = ""
    action: str = ""


class SkillIn(BaseModel):
    id: str = ""
    name: str
    description: str = ""
    system_prompt: str = ""
    tools: list[str] = Field(default_factory=list)
    kb_ids: list[str] = Field(default_factory=lambda: [KB_ID])
    scope: str = "space"


class KbMetaIn(BaseModel):
    id: str = ""
    name: str
    description: str = ""


class EntryIn(BaseModel):
    zh: str
    en: str = ""
    fr: str = ""
    de: str = ""
    it: str = ""
    pl: str = ""
    es: str = ""
    pt: str = ""
    overwrite: bool = True


@app.get("/")
def index():
    path = WEB_DIR / "index.html"
    if not path.exists():
        raise HTTPException(404, "web/index.html missing")
    return FileResponse(path)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    store = get_store()
    return {
        "skills": skill_catalog(),
        "knowledge_bases": store.list_kbs(),
        "stats": store.stats(),
        "import": _import_stats,
        "default_skill": SKILL_ID,
        "default_kb": KB_ID,
    }


@app.get("/api/stats")
def stats():
    return get_store().stats()


@app.post("/api/chat")
def chat(body: ChatIn):
    global _loop
    if _loop is None:
        _loop = AgentLoop(get_store())
    return _loop.handle(
        body.session_id,
        body.message,
        skill_id=body.skill_id or SKILL_ID,
        kb_id=body.kb_id or "",
        action=body.action or "",
    )


@app.get("/api/skills")
def api_skills():
    return {"items": skill_catalog()}


@app.get("/api/skills/{skill_id}")
def api_skill_get(skill_id: str):
    item = get_skill(skill_id)
    if not item:
        raise HTTPException(404, "技能不存在")
    return item


@app.post("/api/skills")
def api_skill_create(body: SkillIn):
    try:
        return save_skill(body.model_dump(), is_new=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/skills/{skill_id}")
def api_skill_update(skill_id: str, body: SkillIn):
    data = body.model_dump()
    data["id"] = skill_id
    try:
        return save_skill(data, is_new=False)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/skills/{skill_id}")
def api_skill_delete(skill_id: str):
    try:
        delete_skill(skill_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.get("/api/kbs")
def api_kbs():
    return {"items": get_store().list_kbs()}


@app.post("/api/kbs")
def api_kb_create(body: KbMetaIn):
    try:
        return get_store().save_kb(body.id or body.name, body.name, body.description, is_new=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/kbs/{kb_id}")
def api_kb_update(kb_id: str, body: KbMetaIn):
    try:
        return get_store().save_kb(kb_id, body.name, body.description, is_new=False)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/kbs/{kb_id}")
def api_kb_delete(kb_id: str):
    try:
        get_store().delete_kb(kb_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.get("/api/kbs/{kb_id}/entries")
def api_entries(
    kb_id: str,
    table: str = Query("glossary"),
    q: str = "",
    limit: int = 50,
    offset: int = 0,
):
    store = get_store()
    try:
        return store.list_entries(table, kb_id=kb_id, q=q, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/kbs/{kb_id}/entries/{table}")
def api_entry_save(kb_id: str, table: str, body: EntryIn):
    if table not in {"glossary", "tm"}:
        raise HTTPException(400, "table 必须是 glossary 或 tm")
    langs = {k: getattr(body, k) for k in LANGS}
    action = get_store().upsert(
        table,
        body.zh,
        langs,
        overwrite=body.overwrite,
        source_version="manual",
        kb_id=kb_id,
    )
    if action == "ignore":
        raise HTTPException(409, "中文已存在，请勾选覆盖")
    get_store().audit(action + "_" + table, body.zh, table, langs, "manual")
    return {"ok": True, "action": action}


@app.delete("/api/kbs/{kb_id}/entries/{table}")
def api_entry_delete(kb_id: str, table: str, zh: str = Query(...)):
    get_store().delete_entry(table, zh, kb_id=kb_id)
    get_store().audit("delete_" + table, zh, table, {}, "manual")
    return {"ok": True}


@app.post("/api/kbs/{kb_id}/import")
async def api_kb_import(kb_id: str, file: UploadFile = File(...)):
    raw = await file.read()
    tmp = EXPORT_DIR / ("_upload_" + (file.filename or "in.xlsx"))
    tmp.write_bytes(raw)
    try:
        stats = import_xlsx(get_store(), tmp, kb_id=kb_id)
    finally:
        tmp.unlink(missing_ok=True)
    return stats


@app.get("/api/kbs/{kb_id}/export")
def api_kb_export(kb_id: str):
    path = export_kb(get_store(), kb_id)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/downloads/{name}")
def download(name: str):
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "invalid name")
    path = EXPORT_DIR / name
    if not path.exists():
        raise HTTPException(404, "file not found")
    return FileResponse(
        path,
        filename=name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
