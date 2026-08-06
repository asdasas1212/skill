#!/usr/bin/env python3
"""build_paper_context.py — pre-compute a shared context for writing/review agents.

Each writing agent previously had to read all 23k chars of paper.md, then the
same 6 agents × ~3 min/token each = waste. This script pre-computes a
paper_context.json with:

- Per-section gist (≤500 chars of summary text) — so writers only read their relevant slices
- Key numbers (auto-extracted from paper_sections.json)
- Figure caption table (id_short, caption_200char, page)
- Module dispatch: which sections feed into which module (using _plan.json + manifest)

Inputs:
- paper_sections.json (from parse_ar5iv_extended.py)
- _plan.json (Phase 3 routing output)
- figures_alias.json (from build_figure_alias.py)
- manifest.json (skill root)
- summary.json + meta.json (for figure captions)

Output: paper_context.json at out_dir
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


def make_gist(paragraphs: list[str], max_chars: int = 500) -> str:
    """Return a gisted version of section paragraphs (first N chars of concatenated text)."""
    full = " ".join(paragraphs)
    if len(full) <= max_chars:
        return full
    # Truncate at sentence boundary
    truncated = full[: max_chars]
    last_period = truncated.rfind(". ")
    if last_period > max_chars * 0.6:
        truncated = truncated[: last_period + 1]
    return truncated.strip() + " ..."


def extract_key_numbers(text: str) -> list[str]:
    """Pull out percentages, big numbers, model sizes for highlight box."""
    seen = set()
    nums = []
    patterns = [
        r"[+\-]?\d+(?:\.\d+)?%",
        r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:A100|GPU|epochs?|hours?|min(?:s)?|sec(?:s)?|fps|Hz|MB|GB|KB|trajectories?|samples?|tasks?|models?|parameters?)",
        r"\$\d+(?:\.\d+)?[BMK]?",
        r"\d+(?:\.\d+)?(?:x|×)\s*(?:faster|slower|more|less|larger|smaller)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            n = m.group(0).strip()
            if n and n not in seen and len(n) < 80:
                seen.add(n)
                nums.append(n)
    return nums[:30]


def build_paper_context(out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    paper_sections_path = out_dir / "paper_sections.json"
    plan_path = out_dir / "_plan.json"
    alias_path = out_dir / "figures_alias.json"
    meta_path = out_dir / "meta.json"
    summary_path = out_dir / "summary.json"

    if not paper_sections_path.exists():
        sys.exit(f"ERROR: {paper_sections_path} missing; run parse_ar5iv_extended.py first")
    paper_sections = json.loads(paper_sections_path.read_text())

    plan = json.loads(plan_path.read_text()) if plan_path.exists() else {"modules": {}}
    alias = json.loads(alias_path.read_text()) if alias_path.exists() else {"figures": {}, "tables": {}}
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else []

    # 1) Per-section gist + key numbers
    sections_out = []
    for s in paper_sections.get("sections", []):
        full_text = " ".join(s.get("paragraphs", []))
        sections_out.append({
            "id": s.get("id", ""),
            "level": s.get("level", 0),
            "title": s.get("title", ""),
            "gist_500char": make_gist(s.get("paragraphs", []), max_chars=500),
            "n_paragraphs": len(s.get("paragraphs", [])),
            "n_inline_equations": len(s.get("inline_equations", [])),
            "key_terms": s.get("key_terms", [])[:20],
            "first_equation": s.get("inline_equations", [{}])[0].get("latex", "") if s.get("inline_equations") else "",
        })

    # 2) Key numbers from full text (single string of all paragraphs)
    full_text = " ".join(
        p for s in paper_sections.get("sections", []) for p in s.get("paragraphs", [])
    )
    key_numbers = extract_key_numbers(full_text)

    # 3) Figure caption table (use figs.json from parse_ar5iv if available, else summary)
    figure_table = []
    figs_path = out_dir / "figs.json"
    figs_meta = json.loads(figs_path.read_text()) if figs_path.exists() else []
    for i, fg in enumerate(figs_meta[:25], 1):
        if fg.get("spacer"):
            continue
        caption = (fg.get("caption") or "").strip()
        if not caption:
            continue
        # Map to short alias
        src = fg.get("src", "")
        full_png = None
        for k in alias.get("figures", {}):
            if k.endswith(src.split("/")[-1]) or k in src:
                full_png = k
                break
        short_id = alias.get("figures", {}).get(full_png, f"fig-{i:02d}.png") if full_png else f"fig-{i:02d}.png"
        figure_table.append({
            "id_short": short_id,
            "label": fg.get("label", ""),
            "caption_300char": caption[:300],
            "page_hint": None,
        })

    # 4) Table caption table
    table_table = []
    for i, t in enumerate(paper_sections.get("tables", [])[:25], 1):
        caption = (t.get("caption") or "").strip()
        if not caption:
            continue
        table_table.append({
            "id_short": f"tbl-{i:02d}",
            "caption_300char": caption[:300],
            "n_cells": len(t.get("cells", [])),
        })

    # 5) Module dispatch: which sections feed which modules (from _plan.json)
    module_dispatch = {}
    for mod_id, mod_data in plan.get("modules", {}).items():
        section_refs = mod_data.get("sections", [])
        module_dispatch[mod_id] = {
            "section_titles": [s.get("title", "") for s in section_refs],
            "n_elements": len(mod_data.get("elements", [])),
        }

    return {
        "schema_version": 1,
        "arxiv_id": paper_sections.get("arxiv_id", ""),
        "title": paper_sections.get("title", ""),
        "abstract_300char": make_gist(
            [paper_sections.get("abstract", "")], max_chars=400,
        ),
        "key_numbers": key_numbers,
        "sections": sections_out,
        "figures": figure_table,
        "tables": table_table,
        "module_dispatch": module_dispatch,
        "stats": paper_sections.get("stats", {}),
        "source": "build_paper_context.py",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    ctx = build_paper_context(out_dir)
    out = out_dir / "paper_context.json"
    out.write_text(json.dumps(ctx, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✓ Wrote {out}")
    print(f"  sections: {len(ctx['sections'])} | figures: {len(ctx['figures'])} | tables: {len(ctx['tables'])}")
    print(f"  key_numbers: {len(ctx['key_numbers'])}")


if __name__ == "__main__":
    main()
