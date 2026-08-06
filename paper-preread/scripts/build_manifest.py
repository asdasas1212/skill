#!/usr/bin/env python3
"""build_manifest.py — generate / verify manifest.json from manifest source.

manifest.json 是 paper-preread skill 的 single source of truth for:
- module list (背景 / 问题 / 结论 / 技术 / 实验 / 讨论)
- score dimensions and trigger rules
- phase_2 expected outputs

Build target: skill directory (where SKILL.md lives).

Usage:
    python3 scripts/build_manifest.py [--skill-dir DIR] [--verify]

If --verify: only read existing manifest.json and validate consistency.
If no manifest.json exists: write a fresh default.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


# ---- Default manifest (kept in sync with the actual file) ----
DEFAULT_MODULES = [
    {"id": "背景", "index": 1, "filename": "背景.json", "heading": "背景", "char_limit": 1000},
    {"id": "问题", "index": 2, "filename": "问题.json", "heading": "问题", "char_limit": 1500},
    {"id": "结论", "index": 3, "filename": "结论.json", "heading": "结论", "char_limit": 1000},
    {"id": "技术", "index": 4, "filename": "技术.json", "heading": "技术", "char_limit": 3000},
    {"id": "实验", "index": 5, "filename": "实验.json", "heading": "实验", "char_limit": 3000},
    {"id": "讨论", "index": 6, "filename": "讨论.json", "heading": "讨论", "char_limit": 2000},
]


def build_manifest() -> dict:
    """Build the default manifest as a Python dict."""
    return {
        "schema_version": 1,
        "skill_name": "paper-preread",
        "modules": list(DEFAULT_MODULES),
        "score_dims": ["correctness", "clarity", "completeness"],
        "trigger_rules": {
            "balanced": {"description": "≥2 medium_or_low", "neg_min": 2, "low_min": None},
            "strict": {"description": "≥2 low", "neg_min": None, "low_min": 2},
            "conservative": {"description": "≥1 low", "neg_min": None, "low_min": 1},
        },
        "phase_contracts": {
            "phase_2_outputs": [
                "paper.pdf",
                "paper.md",
                "paper_meta.json",
                "paper_sections.json",
                "paper_context.json",
                "figures_alias.json",
                "summary.json",
                "figures/",
                "tables/",
                "formulas/",
                "meta.json",
                "figs.json",
            ],
            "phase_3_schema": "_plan.json",
            "phase_4_module_schema": "_modules/<module_id>.json",
        },
        "safe_io_rules": {
            "max_ascii_doublequote_in_content_md": 0,
            "forbid_raw_control_chars": True,
            "atomic_write": True,
        },
        "audience": "VLM-direction graduate student / engineer",
    }


def write_manifest(skill_dir: Path, m: dict) -> Path:
    out = skill_dir / "manifest.json"
    out.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    print(f"✓ Wrote {out}")
    return out


def verify_manifest(skill_dir: Path) -> int:
    p = skill_dir / "manifest.json"
    if not p.exists():
        print(f"ERROR: {p} not found")
        return 1
    m = json.loads(p.read_text())
    # Cross-checks
    errs = []
    if m.get("schema_version") != 1:
        errs.append("schema_version != 1")
    mods = m.get("modules", [])
    if len(mods) != 6:
        errs.append(f"modules count != 6 (got {len(mods)})")
    expected_ids = ["背景", "问题", "结论", "技术", "实验", "讨论"]
    got_ids = [x.get("id") for x in mods]
    if got_ids != expected_ids:
        errs.append(f"module ids != {expected_ids} (got {got_ids})")
    for mod in mods:
        if mod.get("filename") != f"{mod['id']}.json":
            errs.append(f"module {mod['id']} filename != {mod['id']}.json")
        if not isinstance(mod.get("char_limit"), int) or mod["char_limit"] <= 0:
            errs.append(f"module {mod['id']} missing valid char_limit")
    rules = m.get("trigger_rules", {})
    for rule_name in ("balanced", "strict", "conservative"):
        if rule_name not in rules:
            errs.append(f"trigger_rules missing '{rule_name}'")
    if errs:
        for e in errs:
            print(f"  ✗ {e}")
        return 1
    print(f"✓ manifest.json valid ({len(mods)} modules, schema v{m['schema_version']})")
    return 0


def main():
    ap = argparse.ArgumentParser(description="build/verify paper-preread manifest.json")
    ap.add_argument(
        "--skill-dir",
        default=str(Path(__file__).resolve().parent.parent),
        help="skill directory; defaults to the directory containing this script",
    )
    ap.add_argument("--verify", action="store_true", help="only verify existing manifest")
    args = ap.parse_args()
    skill_dir = Path(args.skill_dir)
    if args.verify:
        sys_exit_code = verify_manifest(skill_dir)
        import sys as _sys
        _sys.exit(sys_exit_code)
    else:
        write_manifest(skill_dir, build_manifest())


if __name__ == "__main__":
    main()
