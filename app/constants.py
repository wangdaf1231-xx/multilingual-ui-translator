# -*- coding: utf-8 -*-
from __future__ import annotations

LANGS = ("en", "fr", "de", "it", "pl", "es", "pt")

LANG_LABEL = {
    "en": "英文",
    "fr": "法语",
    "de": "德语",
    "it": "意大利语",
    "pl": "波兰语",
    "es": "西班牙语",
    "pt": "葡萄牙语",
}

LABEL_TO_LANG = {v: k for k, v in LANG_LABEL.items()}

TABLE_HEADERS = ["中文", *[LANG_LABEL[k] for k in LANGS]]

UI_TYPES = (
    "按钮",
    "Tab",
    "icon",
    "功能入口",
    "页面标题",
    "卡片标题",
    "数据标签",
    "状态标签",
    "Toast",
    "错误提示",
    "占位符",
    "弹窗",
    "说明",
    "健康建议",
    "法律协议",
)

UI_TYPE_ALIASES = {
    "标题": "页面标题",
    "正文": "说明",
    "文本": "说明",
    "tab": "Tab",
    "ICON": "icon",
    "Icon": "icon",
}

KB_ID = "pitpat-dict"
KB_NAME = "PitPat翻译字典"
SKILL_ID = "ui-i18n"

HIT_GLOSSARY = "glossary"
HIT_TM = "tm"
HIT_NEW = "new"
HIT_FAIL = "fail"

SOURCE_LABEL = {
    HIT_GLOSSARY: "术语库",
    HIT_TM: "翻译记忆",
    HIT_NEW: "新译",
    HIT_FAIL: "检索未命中",
}

EXPORT_TRIGGERS = (
    "excel",
    "xlsx",
    "帮我输出表格",
    "导出excel",
    "导出表格",
    "导出xlsx",
)
