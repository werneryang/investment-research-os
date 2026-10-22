"""命令行入口：iros <命令>。

    iros sources                         来源与核验状态
    iros datasets                        数据集、最新版本与质量概况
    iros fetch <dataset> --start 2024    取得并版本化
    iros import <dataset> <file> --declared-source "..."
    iros run config/studies/x.yaml       运行研究，生成报告与运行记录
    iros verify <run_id>                 用固定数据版本复现运行结果
    iros verify --all                    复现全部运行
    iros site --out _site                生成项目静态网站
    iros runs                            运行记录列表
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .data import DataStore, ingest
from .registry import Registry, RegistryError
from .runs import list_runs, run_study, verify_run


def _root(arg: str | None) -> Path:
    root = Path(arg or os.environ.get("IROS_HOME") or Path.cwd()).resolve()
    if not (root / "config" / "sources.yaml").exists():
        raise SystemExit(f"{root} 不是项目根目录（缺少 config/sources.yaml）；用 --root 或 IROS_HOME 指定")
    return root


def cmd_sources(args: argparse.Namespace) -> int:
    reg = Registry.load(_root(args.root))
    for src in reg.sources.values():
        print(f"{src.id}  ·  {src.publisher}")
        print(f"    渠道：{src.channel}；注册：{src.registration}")
        datasets = [d for d in reg.datasets.values() if d.source_id == src.id]
        for d in datasets:
            print(f"    - {d.id}: {src.status_for(d.id).value}")
        for v in src.verification:
            print(f"      [{v.date}] {v.dataset} {v.status.value}：{v.evidence}")
    return 0


def cmd_datasets(args: argparse.Namespace) -> int:
    root = _root(args.root)
    reg, store = Registry.load(root), DataStore(root)
    for d in reg.datasets.values():
        v = store.latest(d.id)
        status = reg.sources[d.source_id].status_for(d.id).value
        print(f"{d.id}  [{status}]  {d.frequency} · {d.unit}")
        if v is None:
            print("    尚无版本")
            continue
        counts = v.quality.get("status_counts", {})
        print(f"    最新版本 {v.version_id}（{v.rows} 行；{counts}）创建于 {v.created_at}")
        for issue in v.quality.get("issues", [])[:5]:
            print(f"    ! {issue}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    root = _root(args.root)
    request = {k: v for k, v in {"start": args.start, "end": args.end}.items() if v}
    result = ingest(Registry.load(root), DataStore(root), args.dataset, request)
    print(f"[{result.status}] {args.dataset}：{result.message}")
    if result.status == "failed" and result.version:
        print(f"    已保留旧版本 {result.version.version_id}，未更新数据")
    return 1 if result.status == "failed" else 0


def cmd_import(args: argparse.Namespace) -> int:
    root = _root(args.root)
    reg = Registry.load(root)
    if reg.dataset(args.dataset).connector != "manual_csv":
        raise SystemExit(f"{args.dataset} 不是人工导入数据集")
    request = {"path": args.file, "declared_source": args.declared_source}
    result = ingest(reg, DataStore(root), args.dataset, request)
    print(f"[{result.status}] {args.dataset}：{result.message}")
    return 1 if result.status == "failed" else 0


def cmd_run(args: argparse.Namespace) -> int:
    root = _root(args.root)
    pins = dict(p.split("=", 1) for p in args.pin or [])
    manifest = run_study(root, Path(args.study), pins)
    print(f"[{manifest['status']}] {manifest['run_id']}")
    if manifest["status"] == "failed":
        print(f"    错误：{manifest.get('error')}")
        return 1
    for w in manifest.get("warnings", []):
        print(f"    ! {w}")
    for u in manifest.get("unsupported", []):
        print(f"    不支持：{u['item']}（{u['reason']}）")
    for out in manifest["outputs"]:
        if out["path"].endswith(".html"):
            print(f"    报告：{root / out['path']}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    root = _root(args.root)
    if args.all:
        run_ids = [r["run_id"] for r in list_runs(root) if r["status"] not in ("failed", "running")]
    elif args.run_id:
        run_ids = [args.run_id]
    else:
        raise SystemExit("请给出 run_id，或用 --all 复现全部运行")
    failed = 0
    for run_id in run_ids:
        record = verify_run(root, run_id)
        ok = record["reproduced"]
        failed += not ok
        print(f"[{'reproduced' if ok else 'mismatch'}] {run_id}")
        print(f"    原结果 {record['original_hash'][:16]}，重算 {record['new_hash'][:16]}")
        if record["code_changed"]:
            print("    注意：代码或配置与原运行不同")
    return 1 if failed else 0


def cmd_site(args: argparse.Namespace) -> int:
    from .site import build_site  # 延迟导入：只在生成网站时需要

    index = build_site(_root(args.root), Path(args.out))
    print(f"网站已生成：{index}")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    for r in list_runs(_root(args.root)):
        print(json.dumps(r, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="iros", description="个人投资研究框架")
    p.add_argument("--root", help="项目根目录（默认当前目录或 IROS_HOME）")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("sources", help="来源与核验状态").set_defaults(func=cmd_sources)
    sub.add_parser("datasets", help="数据集与最新版本").set_defaults(func=cmd_datasets)

    f = sub.add_parser("fetch", help="取得数据并创建版本")
    f.add_argument("dataset")
    f.add_argument("--start", help="起始（年份或 YYYY-MM-DD）")
    f.add_argument("--end", help="结束（年份或 YYYY-MM-DD）")
    f.set_defaults(func=cmd_fetch)

    i = sub.add_parser("import", help="人工导入 CSV")
    i.add_argument("dataset")
    i.add_argument("file")
    i.add_argument("--declared-source", required=True, help="原始发布者、取得方式与日期")
    i.set_defaults(func=cmd_import)

    r = sub.add_parser("run", help="运行研究")
    r.add_argument("study", help="研究定义 YAML")
    r.add_argument("--pin", action="append", metavar="DATASET=VERSION", help="固定数据版本")
    r.set_defaults(func=cmd_run)

    v = sub.add_parser("verify", help="复现运行结果")
    v.add_argument("run_id", nargs="?")
    v.add_argument("--all", action="store_true", help="复现全部未失败的运行")
    v.set_defaults(func=cmd_verify)

    w = sub.add_parser("site", help="生成项目静态网站")
    w.add_argument("--out", default="_site", help="输出目录（默认 _site）")
    w.set_defaults(func=cmd_site)

    sub.add_parser("runs", help="运行记录").set_defaults(func=cmd_runs)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RegistryError, LookupError, ValueError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
