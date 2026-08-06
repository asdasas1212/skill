#!/usr/bin/env python3
"""build_figure_alias.py — generate short-name mapping for figures/tables.

Reason: Phase 4 writing agents write `![Description](figures/page007_figure_02.png)`
in content_md. Long names like `page007_figure_02.png` are error-prone:
- agent may drop a leading zero (`page7_figure_02.png` → broken)
- agent may swap underscore positions (`page007figure_02.png` → broken)
- downstream Phase 6 media-insert gets `unsafe file path`

Solution: generate a stable short alias per figure/table on disk.
Agents reference short aliases; Phase 6 resolves them via figures_alias.json.

Usage:
    python3 scripts/build_figure_alias.py <out_dir>
    # writes <out_dir>/figures_alias.json + symlinks short names alongside originals
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path


def human_key(s: str) -> str:
    """Sort helper: pageNNN_figure_NN.png -> page, figure (preserves numeric order)."""
    parts = re.split(r'(\d+)', s)
    return [int(p) if p.isdigit() else p for p in parts]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--no-symlinks", action="store_true",
                    help="don't create symlinks (just generate alias map)")
    args = ap.parse_args()
    out = Path(args.out_dir)

    # Scan figures/ and tables/
    figures = sorted(
        (p for p in (out / "figures").glob("*.png") if p.is_file()),
        key=lambda p: human_key(p.name),
    ) if (out / "figures").exists() else []
    tables = sorted(
        (p for p in (out / "tables").glob("*.png") if p.is_file()),
        key=lambda p: human_key(p.name),
    ) if (out / "tables").exists() else []

    # Short name pattern: fig-NN.png for figures, tbl-NN.png for tables
    # Use 2-digit padding; >99 figures is unusual for a paper.
    figure_alias = {}
    seen_short = set()
    for i, p in enumerate(figures, 1):
        short = f"fig-{i:02d}.png"
        if short in seen_short:
            short = f"fig-{i:03d}.png"
        seen_short.add(short)
        figure_alias[str(p.relative_to(out))] = short

    table_alias = {}
    for i, p in enumerate(tables, 1):
        short = f"tbl-{i:02d}.png"
        if short in seen_short or short in table_alias.values():
            short = f"tbl-{i:03d}.png"
        table_alias[str(p.relative_to(out))] = short

    alias_doc = {
        "schema_version": 1,
        "figures": figure_alias,
        "tables": table_alias,
        # Inverse map for resolution
        "_inverse": {
            **{v: k for k, v in figure_alias.items()},
            **{v: k for k, v in table_alias.items()},
        },
    }

    out_path = out / "figures_alias.json"
    out_path.write_text(json.dumps(alias_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✓ Wrote {out_path} ({len(figure_alias)} figures, {len(table_alias)} tables)")

    # Print summary
    print("\nFigure aliases:")
    for orig, short in list(figure_alias.items())[:5]:
        print(f"  {orig} → {short}")
    if len(figure_alias) > 5:
        print(f"  ... and {len(figure_alias) - 5} more")
    print("\nTable aliases:")
    for orig, short in table_alias.items():
        print(f"  {orig} → {short}")

    # Optional: create symlinks for direct short-name access
    if not args.no_symlinks:
        alias_dir = out / "figures_short"
        alias_dir.mkdir(exist_ok=True)
        for orig, short in figure_alias.items():
            target = alias_dir / short
            if target.exists() or target.is_symlink():
                target.unlink()
            target.symlink_to(f"../{orig}")
        if table_alias:
            tdir = out / "tables_short"
            tdir.mkdir(exist_ok=True)
            for orig, short in table_alias.items():
                target = tdir / short
                if target.exists() or target.is_symlink():
                    target.unlink()
                target.symlink_to(f"../{orig}")
        print(f"\n✓ Symlinks at figures_short/ and tables_short/")


if __name__ == "__main__":
    main()
