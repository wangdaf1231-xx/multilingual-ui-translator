# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.loop import AgentLoop, should_write_glossary
from app.agent.parse import parse_message
from app.kb.normalize import zh_norm
from app.kb.store import Store

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "翻译库.xlsx"


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.bulk_insert(
        "glossary",
        [
            {
                "zh": "身高",
                "en": "Height",
                "fr": "Taille",
                "de": "Größe",
                "it": "Altezza",
                "pl": "Wzrost",
                "es": "Altura",
                "pt": "Altura",
            },
            {
                "zh": "椭圆机",
                "en": "Elliptical",
                "fr": "Elliptique",
                "de": "Crosstrainer",
                "it": "Ellittica",
                "pl": "Orbitrek",
                "es": "Elíptica",
                "pt": "Elíptico",
            },
            {
                "zh": "划行",
                "en": "Rowing",
                "fr": "Aviron",
                "de": "Rudern",
                "it": "Canottaggio",
                "pl": "Wioślarstwo",
                "es": "Remo",
                "pt": "Remo",
            },
            {
                "zh": "包含",
                "en": "Includes",
                "fr": "Inclut",
                "de": "Enthält",
                "it": "Include",
                "pl": "Zawiera",
                "es": "Incluye",
                "pt": "Inclui",
            },
            {
                "zh": "智能手环",
                "en": "Smart Band",
                "fr": "Bracelet",
                "de": "Armband",
                "it": "Bracciale",
                "pl": "Opaska",
                "es": "Pulsera",
                "pt": "Pulseira",
            },
        ],
    )
    s.bulk_insert(
        "tm",
        [
            {
                "zh": "PitPat智能手环",
                "en": "PitPat Smart Band",
                "fr": "PitPat Smart Band",
                "de": "PitPat Smart Band",
                "it": "PitPat Smart Band",
                "pl": "PitPat Smart Band",
                "es": "PitPat Smart Band",
                "pt": "PitPat Smart Band",
            },
            {
                "zh": "室内划行",
                "en": "Indoor Rowing",
                "fr": "Aviron indoor",
                "de": "Indoor-Rudern",
                "it": "Canottaggio indoor",
                "pl": "Wioślarstwo indoor",
                "es": "Remo indoor",
                "pt": "Remo indoor",
            },
            {
                "zh": "仅$19.99/天",
                "en": "Only $19.99/day",
                "fr": "Seulement 19,99 $/jour",
                "de": "Nur 19,99 $/Tag",
                "it": "Solo 19,99 $/giorno",
                "pl": "Tylko 19,99 $/dzień",
                "es": "Solo 19,99 $/día",
                "pt": "Apenas 19,99 $/dia",
            },
        ],
    )
    return s


def test_amount_norm():
    assert zh_norm("仅$19.99/天") == zh_norm("仅19.99$/天")
    assert zh_norm("仅 $19.99 /天") == zh_norm("仅$19.99/天")


def test_exact_hits(store):
    for zh, en in [
        ("身高", "Height"),
        ("椭圆机", "Elliptical"),
        ("划行", "Rowing"),
        ("包含", "Includes"),
        ("智能手环", "Smart Band"),
    ]:
        hit = store.lookup(zh)
        assert hit is not None, zh
        assert hit.complete
        assert hit.langs["en"] == en
        assert hit.source == "glossary"


def test_smartband_not_confused(store):
    a = store.lookup("智能手环")
    b = store.lookup("PitPat智能手环")
    assert a.langs["en"] == "Smart Band"
    assert b.langs["en"] == "PitPat Smart Band"
    assert a.source == "glossary"
    assert b.source == "tm"


def test_no_longer_neighbor(store):
    hit = store.lookup("划行")
    assert hit.langs["en"] == "Rowing"
    assert store.lookup("室内划行").langs["en"] == "Indoor Rowing"
    assert store.lookup("户外划行") is None


def test_amount_lookup(store):
    hit = store.lookup("仅19.99$/天")
    assert hit is not None
    assert hit.langs["en"] == "Only $19.99/day"


def test_parse_ui_and_excel():
    p = parse_message("UI类型：按钮\n立即登录\n查看详情\n帮我输出表格")
    assert p.intent == "translate"
    assert p.want_excel
    assert p.batch_ui == "按钮"
    assert [x.zh for x in p.lines] == ["立即登录", "查看详情"]
    p2 = parse_message("【标题】影响因素")
    assert p2.lines[0].ui_type == "页面标题"
    p3 = parse_message("确认入库")
    assert p3.intent == "confirm"


def test_confirm_gate(store, monkeypatch):
    from app.agent import loop as loop_mod

    def fake_translate(items, locked, skill_id="ui-i18n"):
        out = {}
        for it in items:
            out[it["zh"]] = {
                "en": "Hello",
                "fr": "Bonjour",
                "de": "Hallo",
                "it": "Ciao",
                "pl": "Czesc",
                "es": "Hola",
                "pt": "Ola",
            }
        return out, None

    monkeypatch.setattr(loop_mod, "translate_with_deepseek", fake_translate)
    agent = AgentLoop(store)
    r = agent.handle("s1", "欢迎回来呀这是一句新的测试文案")
    assert r["pending"]
    assert store.lookup("欢迎回来呀这是一句新的测试文案") is None
    r2 = agent.handle("s1", "确认入库")
    assert "已写入" in r2["reply_markdown"]
    assert store.lookup("欢迎回来呀这是一句新的测试文案") is not None


def test_should_write_glossary():
    langs = {k: "x" for k in ("en", "fr", "de", "it", "pl", "es", "pt")}
    assert should_write_glossary("划行", langs)
    assert not should_write_glossary("这是一句很长的说明文案", langs)


def _seven(en: str) -> dict[str, str]:
    return {k: en for k in ("en", "fr", "de", "it", "pl", "es", "pt")}


def test_extract_glossary_in_new_sentence():
    from app.kb.terms import extract_glossary_terms

    entries = [
        {"zh": "步频", "langs": _seven("Cadence")},
        {"zh": "设置", "langs": _seven("Settings")},
        {"zh": "请设置你的步频", "langs": _seven("Set your cadence")},
    ]
    got = extract_glossary_terms("请设置你的步频", entries)
    assert [x["zh"] for x in got] == ["设置", "步频"]
    assert got[0]["langs"]["en"] == "Settings"
    assert got[1]["langs"]["en"] == "Cadence"


def test_extract_longest_term_wins():
    from app.kb.terms import extract_glossary_terms

    entries = [
        {"zh": "会员", "langs": _seven("Member")},
        {"zh": "会员中心", "langs": _seven("Membership")},
    ]
    got = extract_glossary_terms("打开会员中心", entries)
    assert [x["zh"] for x in got] == ["会员中心"]


def test_extract_ignores_incomplete_and_does_not_use_tm_shape():
    from app.kb.terms import extract_glossary_terms

    entries = [
        {"zh": "步频", "langs": {"en": "Cadence", "fr": "", "de": "", "it": "", "pl": "", "es": "", "pt": ""}},
        {"zh": "划行", "langs": _seven("Rowing")},
    ]
    assert extract_glossary_terms("请设置你的步频", entries) == []
    got = extract_glossary_terms("今天室内划行很累", entries)
    assert [x["zh"] for x in got] == ["划行"]


def test_new_sentence_locks_in_sentence_glossary(store, monkeypatch):
    from app.agent import loop as loop_mod

    store.bulk_insert(
        "glossary",
        [
            {"zh": "步频", **_seven("Cadence")},
            {"zh": "设置", **_seven("Settings")},
        ],
    )
    captured: dict = {}

    def fake_translate(items, locked, skill_id="ui-i18n"):
        captured["items"] = items
        captured["locked"] = locked
        out = {}
        for it in items:
            out[it["zh"]] = _seven("Please set your cadence")
        return out, None

    monkeypatch.setattr(loop_mod, "translate_with_deepseek", fake_translate)
    agent = AgentLoop(store)
    r = agent.handle("s-terms", "请设置你的步频")
    terms = captured["items"][0]["terms"]
    assert [t["zh"] for t in terms] == ["设置", "步频"]
    assert any(t["zh"] == "步频" and t["en"] == "Cadence" for t in captured["locked"])
    assert all(t["zh"] != "请设置你的步频" for t in captured["locked"])
    assert "室内划行" not in [t["zh"] for t in terms]
    md = r["reply_markdown"]
    assert "整句未命中" in md
    assert "步频=Cadence" in md
    assert "设置=Settings" in md


def test_tm_exact_still_not_sliced(store, monkeypatch):
    from app.agent import loop as loop_mod

    called = {"n": 0}

    def fake_translate(items, locked, skill_id="ui-i18n"):
        called["n"] += 1
        return {}, None

    monkeypatch.setattr(loop_mod, "translate_with_deepseek", fake_translate)
    agent = AgentLoop(store)
    r = agent.handle("s-tm", "室内划行")
    assert called["n"] == 0
    assert r["checks"][0]["hit_source"] == "tm"
    r2 = agent.handle("s-tm2", "今天室内划行很累")
    assert called["n"] == 1
    zhs = [t["zh"] for t in (r2["checks"][0].get("terms") or [])]
    assert "室内划行" not in zhs
    assert "划行" in zhs


@pytest.mark.skipif(not XLSX.exists(), reason="翻译库.xlsx missing")
def test_real_xlsx_golden(tmp_path):
    from app.kb.import_xlsx import import_xlsx

    s = Store(tmp_path / "real.db")
    stats = import_xlsx(s, XLSX)
    assert stats["glossary"] > 0 and stats["tm"] > 0
    for zh in ("身高", "椭圆机", "划行", "包含", "智能手环"):
        hit = s.lookup(zh)
        assert hit is not None and hit.complete, zh
        assert hit.source in {"glossary", "tm"}
    band = s.lookup("智能手环")
    pit = s.lookup("PitPat智能手环")
    assert band.langs["en"] != pit.langs["en"]
    assert "PitPat" not in band.langs["en"] or band.langs["en"] == "Smart Band"
