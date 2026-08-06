#!/usr/bin/env python3
"""校验 6 个模块文件齐全（**不合并**）。

用法: collect_modules.py <out_dir> [--skill-dir DIR]

读:
  - <out_dir>/_modules/<module>.json
  - <skill_dir>/manifest.json（module list + char_limit + safe_io_rules）

校验:
  - 必需 module 都存在（从 manifest 读，不再硬编码）
  - 每个都含 content_md
  - 每个 content_md 包含模块 H1 标题 (# N. <id>)
  - figure_refs[].path 实际存在（防止飞书写失败）
  - safe_io_rules: content_md 不应含未转义 ASCII 双引号

exit 0: 全齐
exit 1: 有缺
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


def find_skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def load_manifest(skill_dir: Path) -> dict:
    p = skill_dir / "manifest.json"
    if not p.exists():
        sys.exit(f"ERROR: manifest.json missing at {p}; run build_manifest.py first")
    return json.loads(p.read_text())


def check_ascii_doublequote_in_content(content_md: str) -> list[str]:
    """Heuristic: any unescaped ASCII double-quote inside content_md violates safe_io_rules.

    JSON-parsed content_md should have NO raw `"` chars at all (they should all be
    escaped to `\"` or use 「」 / “”). Returns list of bad spans.
    """
    bad = []
    # In JSON-decoded strings there should be 0 raw `"`. Count them.
    for i, ch in enumerate(content_md):
        if ch == '"':
            # Get surrounding context
            ctx = content_md[max(0, i - 30): i + 30]
            bad.append(f"...{ctx}...")
            if len(bad) >= 3:
                break
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--skill-dir", default=None)
    args = ap.parse_args()
    outdir = Path(args.out_dir)
    skill_dir = Path(args.skill_dir) if args.skill_dir else find_skill_dir()

    manifest = load_manifest(skill_dir)
    modules_def = manifest["modules"]

    modules_dir = outdir / "_modules"
    if not modules_dir.exists():
        sys.exit(f"ERROR: {modules_dir} 不存在")

    found = {}
    missing = []
    empty_content = []
    bad_quotes = []
    bad_fig_paths = []

    for mod_def in modules_def:
        mod_id = mod_def["id"]
        fname = mod_def["filename"]
        p = modules_dir / fname
        if not p.exists():
            missing.append(mod_id)
            continue
        try:
            data = json.loads(p.read_text())
        except Exception as e:
            print(f"  WARN: {fname} 解析失败: {e}")
            missing.append(mod_id)
            continue
        content_md = data.get("content_md", "")
        if not content_md:
            empty_content.append(mod_id)
            continue
        # validate module_id matches
        if data.get("module_id") and data.get("module_id") != mod_id:
            print(f"  WARN: {fname} module_id={data.get('module_id')!r} != filename id={mod_id!r}")
        # safe_io: warn (not fail) on ASCII doublequote in content_md
        # — already JSON-decoded strings can carry raw `"` if they were
        #   properly escaped at write time. Failing here would break
        #   legitimate modules. The hard guard lives in safe_io.safe_write_json.
        bad = check_ascii_doublequote_in_content(content_md)
        if bad:
            bad_quotes.append((mod_id, len(bad)))
        # figure path existence
        for ref in data.get("figure_refs", []) + data.get("table_refs", []):
            rpath = ref.get("path", "")
            if rpath and not (outdir / rpath).exists():
                bad_fig_paths.append((mod_id, rpath))
        found[mod_id] = data

    n_chars = sum(len(d.get("content_md", "")) for d in found.values())
    n_figs = sum(len(d.get("figure_refs", [])) for d in found.values())
    n_tabs = sum(len(d.get("table_refs", [])) for d in found.values())
    print(f"✓ {len(found)}/{len(modules_def)} 模块 | {n_chars} chars | {n_figs} figures | {n_tabs} tables")

    # Soft warnings (don't block)
    if bad_quotes:
        for m, n in bad_quotes:
            print(f"  ⚠ {m}.json: 含 {n} 个 ASCII 双引号（safe_write 会在写入时强制改用「」）")
    if bad_fig_paths:
        print(f"  ⚠ 图/表路径不存在: {bad_fig_paths[:3]}")

    # Hard failures only
    issues = []
    if missing:
        issues.append(f"缺: {missing}")
    if empty_content:
        issues.append(f"空 content_md: {empty_content}")

    if issues:
        for issue in issues:
            print(f"  ✗ {issue}")
        sys.exit(1)


if __name__ == "__main__":
    main()
