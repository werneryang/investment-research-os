"""网站的中英文切换。

中文页面在站点根目录，英文页面是同一套模板在 en/ 下的镜像；两种语言共用 assets/、runs/ 与 latest/。

- 模板里的固定文字写成 `L("中文", "English")`，按当前语言取值。
- 登记、研究定义与运行记录里的文字（研究标题、限制、来源证据等）不改动原记录，英文由
  `site/en.yaml` 提供：`phrases` 是逐句对照（键是原文），`patterns` 处理运行时带日期、数字生成的句子
  （正则的命名分组在译文中以 {name} 引用，分组内容本身再查对照表）。`te()` 查不到译文时保留原文，
  并用 `<span lang="zh-CN">` 标出，英文页面上未翻译的内容一眼可见。
- 运行记录中的关键发现保持原样；英文页面显示按同一规则的英文模板从结构化结果生成的译文（见 findings_en.py）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import re

import yaml

LANGS = ("zh", "en")
HTML_LANG = {"zh": "zh-CN", "en": "en"}

_lang: ContextVar[str] = ContextVar("lang", default="zh")
_phrases: ContextVar[dict[str, Any]] = ContextVar("phrases", default={})
_missing: ContextVar[set[str] | None] = ContextVar("missing", default=None)


def lang() -> str:
    return _lang.get()


def is_en() -> bool:
    return _lang.get() == "en"


def load_phrases(root: Path) -> dict[str, Any]:
    """读取 site/en.yaml：{"phrases": {原文: 译文}, "patterns": [(正则, 译文模板)]}。"""
    path = Path(root) / "site" / "en.yaml"
    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}
    return {"phrases": {str(k).strip(): str(v).strip() for k, v in (data.get("phrases") or {}).items() if v},
            "patterns": [(re.compile(p["zh"]), p["en"]) for p in data.get("patterns") or []]}


def _translate(s: str) -> str | None:
    table = _phrases.get()
    found = (table.get("phrases") or {}).get(s)
    if found is not None:
        return found
    for pattern, template in table.get("patterns") or []:
        m = pattern.fullmatch(s)
        if m:
            parts = {k: (_translate(v) or v).replace("、", ", ") for k, v in m.groupdict().items()}
            return template.format(**parts)
    return None


@contextmanager
def use(language: str, phrases: dict[str, str] | None = None, missing: set[str] | None = None) -> Iterator[None]:
    """在一段渲染中使用指定语言；missing 收集英文页面上没有译文的原文。"""
    tokens = [_lang.set(language)]
    if phrases is not None:
        tokens.append(_phrases.set(phrases))
    if missing is not None:
        tokens.append(_missing.set(missing))
    try:
        yield
    finally:
        for var, tok in zip((_lang, _phrases, _missing), tokens):  # noqa: B905 - 只重置已设置的
            var.reset(tok)


def L(zh: str, en: str) -> str:
    """模板中的固定文字。"""
    return en if _lang.get() == "en" else zh


class Labels(dict):
    """值为 (中文, English) 的标签表；取值时按当前语言返回。"""

    def __getitem__(self, key: Any) -> str:
        return L(*super().__getitem__(key))

    def get(self, key: Any, default: Any = None) -> Any:
        return self[key] if key in self else default


def tx(text: Any) -> str:
    """登记或记录中的文字的纯文本译文；没有译文时返回原文（用于 title、alt 等属性）。"""
    s = "" if text is None else str(text)
    if _lang.get() != "en" or not s:
        return s
    found = _translate(s.strip())
    if found is None:
        missing = _missing.get()
        if missing is not None and has_cjk(s):
            missing.add(s.strip())
        return s
    return found


def te(text: Any) -> str:
    """登记或记录中的文字，转义为 HTML；英文页面上没有译文的原文用 lang="zh-CN" 标出。"""
    from .common import e  # 避免循环引用

    s = "" if text is None else str(text)
    out = tx(s)
    if _lang.get() == "en" and out == s and has_cjk(s):
        return f'<span lang="zh-CN">{e(s)}</span>'
    return e(out)


def has_cjk(s: str) -> bool:
    """含汉字或全角标点。"""
    return any("\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f" or "\uff00" <= ch <= "\uffef" for ch in s)
