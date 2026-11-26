"""研究依赖图：从每项研究反向追溯到计算模块、数据集、取数模块与来源，找出未被使用的模块与断链。

只读静态信号，不运行研究、不读取数据：

- 研究定义 ``config/studies/*.yaml``：``branch``（研究分支）、``data``（数据集）、``method`` 中指向登记的键
- 研究分支：``research/*.py`` 中 ``@register_branch("名称")`` 的位置
- Python import（ast 解析，包括函数内的延迟导入）：只沿计算与取数模块传递，不穿过基础设施
  （contracts、registry、data.store 等所有研究都用的部分），否则一切都可达，看不出未使用的模块
- 运行框架 ``runs.py`` 导入的计算模块（关键发现规则、原始快照抽查）：所有研究共用
- 数据集登记 ``config/datasets.yaml``：``connector``（接入器类的 ``name``）、``source_id``
- 证据包数据集（``evidence_bundle``）的生成者：模块里的 ``DATASET_ID = "..."``，或脚本中出现该数据集 ID；
  经中间文件的环节读不出，在 ``config/lineage.yaml`` 声明

只用标准库与项目已有的 PyYAML。输出 ``build()`` 的字典；``markdown()`` 生成清单；网站页面见 site/lineage.py。
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

PKG = "investment_os"
COMPUTE_TOPS = {"analytics", "research", "validation", "earnings", "events", "supply_chain", "tenor"}
FETCH_MODULES = {"investment_os.data.fundamentals"}
# 基础设施：所有研究都经过，不作为依赖链的一环，也不判断是否被使用
INFRA = {"investment_os.research", "investment_os.research.base", "investment_os.connectors",
         "investment_os.connectors.base"}
# method 中指向登记的键：键 → (登记文件或目录, 引用方式)
METHOD_REFS = {
    "earnings": ("config/earnings", "file"),
    "event": ("config/events", "file"),
    "units": ("config/supply_chain/units.yaml", "id"),
    "root": ("config/supply_chain/entities.yaml", "id"),
    "downstream_notes": ("config/supply_chain/claims.yaml", "id"),
}
_CONFIG_PATH = re.compile(r"^config/[\w./-]+$")


# ---------------------------------------------------------------- Python 模块

def _module_name(src: Path, path: Path) -> str:
    rel = path.relative_to(src).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_reexport(tree: ast.Module) -> bool:
    """包的 __init__ 只做导入与 __all__ 时视为基础设施（转出口），不算计算模块。"""
    return not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for n in tree.body)


def category(name: str, reexport: bool = False) -> str:
    """compute（计算）、fetch（取数）或 infra（基础设施）。"""
    if name in INFRA or reexport:
        return "infra"
    parts = name.split(".")
    if len(parts) > 1 and parts[1] == "connectors" or name in FETCH_MODULES:
        return "fetch"
    if len(parts) > 1 and parts[1] in COMPUTE_TOPS:
        return "compute"
    return "infra"


def _imports(tree: ast.Module, name: str, is_pkg: bool, known: set[str]) -> tuple[set[str], set[str]]:
    """返回 (导入的本包模块, 找不到的本包模块)。"""
    found, missing = set(), set()
    pkg = name.split(".") if is_pkg else name.split(".")[:-1]

    def add(target: str, alias: str | None) -> None:
        if alias and f"{target}.{alias}" in known:
            found.add(f"{target}.{alias}")
        elif target in known:
            found.add(target)
        else:
            missing.add(target)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg[:len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                target = ".".join(base + (node.module.split(".") if node.module else []))
            elif node.module and node.module.split(".")[0] == PKG:
                target = node.module
            else:
                continue
            for a in node.names:
                add(target, None if a.name == "*" else a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] == PKG:
                    add(a.name, None)
    return found - {name}, missing


def _string_constants(tree: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _config_paths(tree: ast.AST) -> set[str]:
    """源码里写明的 config 路径：字符串 "config/x.yaml"，或 root / "config" / "earnings" 这样的路径拼接。"""
    out = {s for s in _string_constants(tree) if _CONFIG_PATH.match(s)}
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            parts, cur = [], node
            while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
                if isinstance(cur.right, ast.Constant) and isinstance(cur.right.value, str):
                    parts.append(cur.right.value)
                else:
                    parts = []
                cur = cur.left
            if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
                parts.append(cur.value)
            parts.reverse()
            if "config" in parts:
                out.add("/".join(parts[parts.index("config"):]))
    return {p for p in out if p != "config"}


def _dataset_id_constant(tree: ast.Module) -> str | None:
    for node in tree.body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DATASET_ID" for t in node.targets)
                and isinstance(node.value, ast.Constant)):
            return node.value.value
    return None


def _branches(tree: ast.Module) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            for d in node.decorator_list:
                if (isinstance(d, ast.Call) and getattr(d.func, "id", getattr(d.func, "attr", None)) == "register_branch"
                        and d.args and isinstance(d.args[0], ast.Constant)):
                    out.append(d.args[0].value)
    return out


def _connector_names(tree: ast.Module) -> list[str]:
    out = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for b in node.body:
                if (isinstance(b, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "name" for t in b.targets)
                        and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str)):
                    out.append(b.value.value)
    return out


# ---------------------------------------------------------------- 构建

def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None


def build(root: Path) -> dict[str, Any]:
    root = Path(root)
    src = root / "src"
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, list[tuple[str, str]]] = defaultdict(list)   # 依赖方 → [(被依赖方, 信号)]
    broken: list[dict[str, str]] = []

    def node(nid: str, kind: str, label: str, **extra: Any) -> str:
        nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label, **extra})
        return nid

    def edge(a: str, b: str, signal: str) -> None:
        if (b, signal) not in edges[a]:
            edges[a].append((b, signal))

    # Python 模块
    trees: dict[str, ast.Module] = {}
    paths: dict[str, Path] = {}
    pkgs: set[str] = set()
    for path in sorted((src / PKG).rglob("*.py")):
        name = _module_name(src, path)
        trees[name] = ast.parse(path.read_text(encoding="utf-8"))
        paths[name] = path
        if path.name == "__init__.py":
            pkgs.add(name)
    known = set(trees)
    cat = {n: category(n, n in pkgs and _is_reexport(t)) for n, t in trees.items()}
    imports: dict[str, set[str]] = {}
    for n, t in trees.items():
        imports[n], missing = _imports(t, n, n in pkgs, known)
        for m in sorted(missing):
            broken.append({"from": paths[n].relative_to(root).as_posix(), "to": m, "kind": "import",
                           "detail": "导入的本包模块不存在"})

    def mod(n: str) -> str:
        return node(f"mod:{n}", cat[n], paths[n].relative_to(src / PKG).as_posix(),
                    path=paths[n].relative_to(root).as_posix())

    for n in trees:
        if cat[n] != "infra":
            mod(n)
            for m in sorted(imports[n]):
                if cat[m] != "infra":
                    edge(f"mod:{n}", mod(m), "import")
    # 本包外的使用者（cli、site、reporting 等）：给「未使用」一栏做背景说明
    importers: dict[str, set[str]] = defaultdict(set)
    for n, deps in imports.items():
        for m in deps:
            importers[m].add(n)

    # 脚本
    scripts: dict[str, ast.Module] = {}
    for path in sorted((root / "scripts").glob("*.py")):
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scripts[rel] = tree
        sid = node(f"script:{rel}", "script", rel, path=rel)
        found, missing = _imports(tree, "__script__", False, known)
        for m in sorted(found):
            importers[m].add(rel)
            if cat[m] != "infra":
                edge(sid, mod(m), "import")
        for m in sorted(missing):
            broken.append({"from": rel, "to": m, "kind": "import", "detail": "导入的本包模块不存在"})
    # 测试只用于「其他引用」说明，不作为依赖
    for path in sorted((root / "tests").glob("test_*.py")):
        found, _ = _imports(ast.parse(path.read_text(encoding="utf-8")), "__test__", False, known)
        for m in found:
            importers[m].add(path.relative_to(root).as_posix())

    # 登记文件
    def cfg(rel: str, signal: str, owner: str) -> str | None:
        p = root / rel
        if not p.exists():
            broken.append({"from": owner, "to": rel, "kind": signal, "detail": "引用的登记文件或目录不存在"})
            return None
        return node(f"cfg:{rel}", "config", rel, path=rel)

    for n, t in trees.items():
        if cat[n] != "infra":
            for rel in sorted(_config_paths(t)):
                if (c := cfg(rel, "config_path", paths[n].relative_to(root).as_posix())):
                    edge(f"mod:{n}", c, "config_path")
    for rel, t in scripts.items():
        for p in sorted(_config_paths(t)):
            if (c := cfg(p, "config_path", rel)):
                edge(f"script:{rel}", c, "config_path")

    # 分支 → 模块；接入器名 → 模块
    branch_mod: dict[str, str] = {}
    connector_mod: dict[str, str] = {}
    for n, t in trees.items():
        for b in _branches(t):
            branch_mod[b] = n
        if n.startswith(f"{PKG}.connectors."):
            for c in _connector_names(t):
                connector_mod[c] = n

    # 来源与数据集
    source_doc = _load(root / "config" / "sources.yaml") or {}
    sources = {s["id"]: s for s in source_doc.get("sources", [])}
    datasets = (_load(root / "config" / "datasets.yaml") or {}).get("datasets", {})
    declared = (_load(root / "config" / "lineage.yaml") or {}).get("evidence_inputs", {}) or {}
    content_text = (root / "site" / "content.yaml").read_text(encoding="utf-8") if (root / "site" / "content.yaml").exists() else ""
    producers: dict[str, list[str]] = defaultdict(list)
    for n, t in trees.items():
        if (d := _dataset_id_constant(t)):
            producers[d].append(f"mod:{n}")
    for rel, t in scripts.items():
        for d in _string_constants(t) & set(datasets):
            producers[d].append(f"script:{rel}")

    for did, spec in datasets.items():
        dn = node(f"ds:{did}", "dataset", did, connector=spec.get("connector"), source=spec.get("source_id"),
                  description=spec.get("description", ""))
        sid = spec.get("source_id")
        if sid in sources:
            edge(dn, node(f"src:{sid}", "source", sources[sid].get("name") or sid, source_id=sid), "source_id")
        else:
            broken.append({"from": f"config/datasets.yaml#{did}", "to": str(sid), "kind": "source_id",
                           "detail": "来源未在 config/sources.yaml 登记"})
        conn = spec.get("connector")
        if conn in connector_mod:
            edge(dn, mod(connector_mod[conn]), "connector")
        else:
            broken.append({"from": f"config/datasets.yaml#{did}", "to": str(conn), "kind": "connector",
                           "detail": "接入器未注册"})
        if conn == "evidence_bundle":
            for p in producers.get(did, []):
                edge(dn, p, "producer")
            extra = declared.get(did) or {}
            for rel in extra.get("built_by", []):
                if (root / rel).exists():
                    edge(dn, node(f"script:{rel}", "script", rel, path=rel), "declared")
                else:
                    broken.append({"from": f"config/lineage.yaml#{did}", "to": rel, "kind": "declared",
                                   "detail": "声明的生成脚本不存在"})
            if extra.get("via"):
                nodes[dn]["via"] = extra["via"]
            if not producers.get(did) and not extra.get("built_by"):
                nodes[dn]["producer_unknown"] = True
    for did in declared:
        if did not in datasets:
            broken.append({"from": "config/lineage.yaml", "to": did, "kind": "declared",
                           "detail": "声明的数据集未在 config/datasets.yaml 登记"})

    # 运行框架：所有研究共用的计算模块
    framework = sorted(f"mod:{m}" for m in imports.get(f"{PKG}.runs", set()) if cat[m] != "infra")
    for f in framework:
        mod(f.removeprefix("mod:"))

    # 研究
    studies = []
    for path in sorted((root / "config" / "studies").glob("*.yaml")):
        rel = path.relative_to(root).as_posix()
        doc = _load(path) or {}
        st = doc.get("study_id", path.stem)
        sn = node(f"study:{st}", "study", doc.get("title", st), path=rel, question=doc.get("question", ""),
                  branch=doc.get("branch"))
        studies.append(sn)
        b = doc.get("branch")
        if b in branch_mod:
            edge(sn, mod(branch_mod[b]), "branch")
        else:
            broken.append({"from": rel, "to": str(b), "kind": "branch", "detail": "研究分支未注册"})
        for f in framework:
            edge(sn, f, "framework")
        for role, v in (doc.get("data") or {}).items():
            did = v.get("dataset") if isinstance(v, dict) else v
            required = not (isinstance(v, dict) and v.get("required") is False)
            if did in datasets:
                edge(sn, f"ds:{did}", f"data.{role}" + ("" if required else "?"))
            else:
                broken.append({"from": rel, "to": str(did), "kind": f"data.{role}", "detail": "数据集未在 config/datasets.yaml 登记"})
        method = doc.get("method") or {}
        for key, (target, how) in METHOD_REFS.items():
            if key not in method:
                continue
            values = method[key] if isinstance(method[key], list) else [method[key]]
            if how == "file":
                for v in values:
                    if (c := cfg(f"{target}/{v}.yaml", f"method.{key}", rel)):
                        edge(sn, c, f"method.{key}")
            else:
                ids = _ids(root / target)
                c = cfg(target, f"method.{key}", rel)
                for v in values:
                    if v not in ids:
                        broken.append({"from": rel, "to": f"{target}#{v}", "kind": f"method.{key}",
                                       "detail": "登记中没有这个 id"})
                if c:
                    edge(sn, c, f"method.{key}")

    # 可达性：每项研究能到达的节点
    reach: dict[str, set[str]] = {}
    for sn in studies:
        seen, stack = set(), [sn]
        while stack:
            cur = stack.pop()
            for nxt, _ in edges.get(cur, []):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        reach[sn] = seen
    used_by: dict[str, list[str]] = defaultdict(list)
    for sn, seen in reach.items():
        for n in seen:
            used_by[n].append(sn.removeprefix("study:"))

    # 未使用：从任何研究都到达不了的计算、取数模块、脚本、数据集与已接入的来源
    unused = []
    connected = {spec.get("source_id") for spec in datasets.values()}
    for nid, n in sorted(nodes.items()):
        if nid in used_by or n["kind"] in ("study", "config"):
            continue
        if n["kind"] == "source" and n.get("source_id") not in connected:
            continue
        others: list[str] = []
        if nid.startswith("mod:"):
            name = nid.removeprefix("mod:")
            others = sorted(_short(i) for i in importers.get(name, ()))
            if name.startswith(f"{PKG}.connectors."):
                regs = [c for c, m in connector_mod.items() if m == name]
                users = sorted(d for d, s in datasets.items() if s.get("connector") in regs)
                others += [f"数据集 {d}" for d in users] or [f"接入器 {', '.join(regs)} 没有登记的数据集使用"]
        elif nid.startswith("ds:"):
            did = nid.removeprefix("ds:")
            spec = datasets[did]
            if spec.get("scheduled_fetch") is not None:
                others.append("定时取数（scheduled_fetch）")
            if re.search(rf"\b{re.escape(did)}\b", content_text):
                others.append("网站说明 site/content.yaml")
            others += sorted(r for r, t in scripts.items() if did in _string_constants(t))
        elif nid.startswith("script:"):
            others = ["脚本，不被研究引用"]
        elif nid.startswith("src:"):
            others = [f"数据集 {d}" for d, s in datasets.items() if s.get("source_id") == n["source_id"]]
        unused.append({"id": nid, "kind": n["kind"], "label": n["label"], "others": others})

    # 接入器：所在模块被用到，但这个接入器的数据集没有研究用到
    reached_ds = {n.removeprefix("ds:") for n in used_by if n.startswith("ds:")}
    for conn, m in sorted(connector_mod.items()):
        if f"mod:{m}" not in used_by:
            continue
        users = sorted(d for d, s in datasets.items() if s.get("connector") == conn)
        if not set(users) & reached_ds:
            label = f"{nodes[f'mod:{m}']['label']} · {conn}"
            unused.append({"id": f"connector:{conn}", "kind": "connector", "label": label,
                           "others": [f"数据集 {d}" for d in users] or ["没有登记的数据集使用这个接入器"]})

    candidates = sorted(s for s in sources if s not in connected)
    return {
        "schema": "iros-lineage.v1",
        "nodes": nodes,
        "edges": {k: [{"to": t, "signal": s} for t, s in v] for k, v in edges.items()},
        "studies": [s.removeprefix("study:") for s in studies],
        "framework": framework,
        "reach": {k.removeprefix("study:"): sorted(v) for k, v in reach.items()},
        "used_by": {k: sorted(v) for k, v in used_by.items()},
        "unused": unused,
        "broken": broken,
        "candidate_sources": candidates,
        "counts": _counts(nodes, studies, unused, broken),
        "coverage": _coverage(root, studies, nodes, edges),
    }


def _ids(path: Path) -> set[str]:
    """登记文件里所有 id 字段的值。"""
    out: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if isinstance(x.get("id"), str):
                out.add(x["id"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(_load(path))
    return out


def _short(name: str) -> str:
    return name.removeprefix(f"{PKG}.") if "/" not in name else name


def _counts(nodes: dict[str, Any], studies: list[str], unused: list[dict[str, Any]], broken: list[Any]) -> dict[str, int]:
    kinds = defaultdict(int)
    for n in nodes.values():
        kinds[n["kind"]] += 1
    return {"studies": len(studies), "compute": kinds["compute"], "fetch": kinds["fetch"], "scripts": kinds["script"],
            "modules": kinds["compute"] + kinds["fetch"] + kinds["script"], "datasets": kinds["dataset"],
            "sources": kinds["source"], "config": kinds["config"], "unused": len(unused),
            "unused_modules": sum(1 for u in unused if u["kind"] in ("compute", "fetch", "script", "connector")),
            "broken": len(broken)}


def _coverage(root: Path, studies: list[str], nodes: dict[str, Any], edges: dict[str, Any]) -> dict[str, int]:
    """各信号覆盖多少项研究（盘点依赖能否被机器读出）。"""
    out = defaultdict(int)
    for sn in studies:
        signals = {s.split(".")[0].rstrip("?") for _, s in edges.get(sn, [])}
        for s in signals:
            out[s] += 1
    return dict(out)


# ---------------------------------------------------------------- 依赖链（按研究展开）

def chain(graph: dict[str, Any], study: str) -> dict[str, Any]:
    """一项研究的主干：分支模块及其导入、登记、数据集 → 接入器/生成者 → 来源。框架模块单列，不在每项研究下重复。"""
    nodes, edges = graph["nodes"], graph["edges"]
    framework = set(graph["framework"])

    def subtree(nid: str, seen: frozenset[str]) -> dict[str, Any]:
        kids = []
        for e in edges.get(nid, []):
            t = e["to"]
            if t in seen or t in framework:
                continue
            kids.append({**subtree(t, seen | {t}), "signal": e["signal"]})
        return {"id": nid, "kind": nodes[nid]["kind"], "label": nodes[nid]["label"], "children": kids}

    sn = f"study:{study}"
    out = {"compute": [], "config": [], "data": []}
    for e in edges.get(sn, []):
        if e["signal"] == "framework":
            continue
        t = subtree(e["to"], frozenset({sn, e["to"]}))
        t["signal"] = e["signal"]
        out["data" if e["signal"].startswith("data.") else "config" if e["signal"].startswith("method.") else "compute"].append(t)
    return out


def signature(graph: dict[str, Any], study: str) -> tuple:
    """依赖完全相同的研究合并展示（例如 15 项公司年度研究）。"""
    return tuple(sorted((e["to"], e["signal"]) for e in graph["edges"].get(f"study:{study}", [])))


def groups(graph: dict[str, Any]) -> list[list[str]]:
    by: dict[tuple, list[str]] = defaultdict(list)
    for s in graph["studies"]:
        by[signature(graph, s)].append(s)
    return sorted(by.values(), key=lambda g: (graph["nodes"][f"study:{g[0]}"].get("branch") or "", g[0]))


def fan_in(graph: dict[str, Any], kinds: tuple[str, ...]) -> list[tuple[str, int]]:
    """每个节点被多少项研究用到；共用越多越核心。"""
    rows = [(nid, len(graph["used_by"].get(nid, []))) for nid, n in graph["nodes"].items() if n["kind"] in kinds]
    return sorted(rows, key=lambda r: (-r[1], r[0]))


def impact(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """每个来源出错会波及哪些研究（经过哪些数据集）。"""
    nodes, edges = graph["nodes"], graph["edges"]
    rows = []
    for sid in (n for n, v in nodes.items() if v["kind"] == "source"):
        ds = sorted(d for d, es in edges.items() if d.startswith("ds:") and any(e["to"] == sid for e in es))
        studies = sorted({s for d in ds for s in graph["used_by"].get(d, [])})
        per = {d.removeprefix("ds:"): graph["used_by"].get(d, []) for d in ds}
        rows.append({"source": sid, "label": nodes[sid]["label"], "datasets": per, "studies": studies})
    return sorted(rows, key=lambda r: (-len(r["studies"]), r["source"]))


# ---------------------------------------------------------------- Markdown 清单

KIND_LABEL = {"compute": "计算模块", "fetch": "取数模块", "connector": "接入器", "script": "脚本", "dataset": "数据集",
              "source": "来源"}
SIGNAL_LABEL = {"branch": "研究分支", "import": "导入", "connector": "接入器", "source_id": "来源", "producer": "生成者",
                "declared": "声明的生成脚本", "config_path": "读取登记", "framework": "运行框架",
                "data": "数据集（data）", "method": "登记引用（method）"}


def _sig(s: str) -> str:
    if s.startswith("data."):
        return f"数据·{s[5:].rstrip('?')}" + ("（可选）" if s.endswith("?") else "")
    if s.startswith("method."):
        return f"登记·{s[7:]}"
    return SIGNAL_LABEL.get(s, s)


def _md_tree(t: dict[str, Any], depth: int, lines: list[str]) -> None:
    lines.append(f"{'  ' * depth}- {_sig(t['signal'])}：`{t['label']}`")
    for k in t["children"]:
        _md_tree(k, depth + 1, lines)


def markdown(graph: dict[str, Any]) -> str:
    c, nodes = graph["counts"], graph["nodes"]
    lines = [
        "# 研究依赖清单",
        "",
        "由 `uv run iros lineage --md docs/lineage.md` 生成，不要手改；网站页面 `lineage.html` 在每次构建时重新生成。"
        "方法与信号见 `src/investment_os/lineage.py` 开头的说明。",
        "",
        f"- 研究 {c['studies']} 项；模块 {c['modules']} 个（计算 {c['compute']}、取数 {c['fetch']}、脚本 {c['scripts']}）；"
        f"数据集 {c['datasets']} 个；已接入来源 {c['sources']} 个",
        f"- 从任何研究都到达不了：{c['unused']} 项（其中模块与脚本 {c['unused_modules']} 个）",
        f"- 断链：{c['broken']} 处",
        "",
        "## 1. 信号覆盖",
        "",
        "| 信号 | 覆盖研究数 |",
        "|---|---|",
        *(f"| {_sig(k)} | {v} / {c['studies']} |" for k, v in sorted(graph["coverage"].items())),
        "",
        "所有研究还经过运行框架 `runs.py` 调用的这些计算模块（下文不在每项研究下重复）："
        + "、".join(f"`{nodes[f]['label']}`" for f in graph["framework"]),
        "",
        "## 2. 每项研究的依赖链",
        "",
    ]
    for g in groups(graph):
        head = nodes[f"study:{g[0]}"]
        title = head["label"] if len(g) == 1 else f"{len(g)} 项研究（分支 {head.get('branch')}，依赖相同）"
        lines += [f"### {title}", "", "研究：" + "、".join(f"`{s}`" for s in g), ""]
        ch = chain(graph, g[0])
        for part in ("compute", "config", "data"):
            for t in ch[part]:
                _md_tree(t, 0, lines)
        lines.append("")
    lines += ["## 3. 模块被多少研究用到", "", "| 模块 | 类型 | 研究数 |", "|---|---|---|"]
    kind_label = {"compute": "计算", "fetch": "取数", "script": "脚本"}
    for nid, n in fan_in(graph, ("compute", "fetch", "script")):
        if n:
            lines.append(f"| `{nodes[nid]['label']}` | {kind_label[nodes[nid]['kind']]} | {n} |")
    lines += ["", "## 4. 来源出错会波及的研究", "", "| 来源 | 数据集（研究数） | 受影响研究数 |", "|---|---|---|"]
    for r in impact(graph):
        ds = "、".join(f"`{d}`（{len(s)}）" for d, s in r["datasets"].items())
        lines.append(f"| {r['label']}（`{r['source'].removeprefix('src:')}`） | {ds} | {len(r['studies'])} |")
    lines += ["", "## 5. 从任何研究都到达不了的模块与数据", "",
              "「其他引用」说明它在研究之外是否还有用途（命令行、网站、定时取数等），供判断是否删除；本清单不作删除建议。", "",
              "| 名称 | 类型 | 其他引用 |", "|---|---|---|"]
    kl = KIND_LABEL
    for u in sorted(graph["unused"], key=lambda u: (list(kl).index(u["kind"]), u["label"])):
        lines.append(f"| `{u['label']}` | {kl[u['kind']]} | {'；'.join(u['others']) or '无'} |")
    lines += ["", f"另有 {len(graph['candidate_sources'])} 个来源没有登记数据集（候选或已停用），不算未使用。", "",
              "## 6. 断链", ""]
    if graph["broken"]:
        lines += ["| 引用方 | 指向 | 信号 | 说明 |", "|---|---|---|---|"]
        lines += [f"| `{b['from']}` | `{b['to']}` | {b['kind']} | {b['detail']} |" for b in graph["broken"]]
    else:
        lines.append("没有断链。")
    return "\n".join(lines) + "\n"
