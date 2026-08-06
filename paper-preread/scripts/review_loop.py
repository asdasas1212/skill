#!/usr/bin/env python3
"""
Review loop coordinator for paper-preread skill.

Wraps: agent scoring (one or many perspectives) + aggregation + trigger rules + optimization prompt generation.

Operates on _modules/<模块>.json (independent files, no merge).

Input schema (single agent output):
  {
    "perspective": "panel",  // or "vlm_novice", "cvpr_reviewer", "vln_student", "figure_auditor"
    "module_scores": {
      "<模块>": {
        "correctness": "high" | "medium" | "low",
        "clarity":     "high" | "medium" | "low",
        "completeness":"high" | "medium" | "low",
        "comments": {"correctness": "...", "clarity": "...", "completeness": "..."}
      },
      ...
    }
  }

If multiple perspectives: pass a list of these dicts as input.

Trigger logic:
  Read from <skill_dir>/manifest.json → trigger_rules.<rule_name>
  balanced: neg_count >= manifest.trigger_rules.balanced.neg_min
  strict:   low_count >= manifest.trigger_rules.strict.low_min
  conservative: low_count >= manifest.trigger_rules.conservative.low_min

Usage:
  review_loop.py <scores.json or -> [--rule balanced] [--max-iter 2] [--current-iter 1]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


# Score values
NEG = {"low", "medium"}


def find_skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def load_manifest(skill_dir: Path) -> dict:
    p = skill_dir / "manifest.json"
    if not p.exists():
        sys.exit(f"ERROR: manifest.json missing at {p}; run build_manifest.py first")
    return json.loads(p.read_text())


def aggregate_scores(score_dicts: list[dict], manifest: dict, rule: str = "balanced") -> tuple[dict, list]:
    """Aggregate score dicts (one per perspective).
    Returns (report_dict, triggered_list) where triggered is list of (module, dim, comments_dict).
    """
    module_ids = [m["id"] for m in manifest["modules"]]
    dims = manifest["score_dims"]
    trigger_conf = manifest["trigger_rules"][rule]

    # Build scores structure {agent_name: {module: {dim: score, comments: {dim: text}}}}
    scores = {}
    for i, sd in enumerate(score_dicts):
        agent_name = sd.get("perspective", f"agent_{i}")
        scores[agent_name] = {}
        for mod_id in module_ids:
            mod_score = sd.get("module_scores", {}).get(mod_id, {})
            scores[agent_name][mod_id] = {
                "correctness": mod_score.get("correctness", ""),
                "clarity": mod_score.get("clarity", ""),
                "completeness": mod_score.get("completeness", ""),
                "comments": mod_score.get("comments", {}),
            }

    triggered = []
    report = {}
    for mod_id in module_ids:
        for dim in dims:
            neg = [a for a, ms in scores.items() if ms.get(mod_id, {}).get(dim) in NEG]
            low = [a for a, ms in scores.items() if ms.get(mod_id, {}).get(dim) == "low"]
            neg_count = len(neg)
            low_count = len(low)
            # Trigger evaluation from manifest config
            needs_fix = False
            if trigger_conf.get("neg_min") is not None and neg_count >= trigger_conf["neg_min"]:
                needs_fix = True
            if trigger_conf.get("low_min") is not None and low_count >= trigger_conf["low_min"]:
                needs_fix = True
            entry = {
                "neg_count": neg_count,
                "low_count": low_count,
                "needs_fix": needs_fix,
                "neg_agents": neg,
                "low_agents": low,
            }
            if needs_fix:
                comments = {
                    a: scores[a][mod_id].get("comments", {}).get(dim, "")
                    for a in neg
                }
                entry["comments"] = comments
                triggered.append((mod_id, dim, comments))
            report[(mod_id, dim)] = entry
    return report, triggered


def print_report(score_dicts: list[dict], manifest: dict, rule: str = "balanced",
                 max_iter: int = 2, current_iter: int = 1) -> tuple[dict, list]:
    report, triggered = aggregate_scores(score_dicts, manifest, rule=rule)
    iter_note = f"  [迭代 {current_iter}/{max_iter}]"
    if current_iter >= max_iter and triggered:
        iter_note += "  ⚠️ 已达 max_iter，停止重写"
    print(f"\n=== 评分汇总（规则: {rule}）{iter_note}===")
    n_agents = len(score_dicts)
    headers = " ".join(f"P{i:<5}" for i in range(n_agents))
    print(f"\n{'模块':<{5}} {'维度':<{12}} {headers}")
    print("-" * 60)
    for mod_def in manifest["modules"]:
        mod_id = mod_def["id"]
        for dim in manifest["score_dims"]:
            cells = []
            for sd in score_dicts:
                v = sd.get("module_scores", {}).get(mod_id, {}).get(dim, "")
                cells.append(v)
            entry = report[(mod_id, dim)]
            mark = "✓" if entry["needs_fix"] else " "
            agent_cols = " ".join(f"{c:<{5}}" for c in cells)
            print(f"{mod_id:<{5}} {dim:<{12}} {agent_cols} {mark}")
    print()
    print(f"=== 触发清单（{len(triggered)} 项）===")
    if not triggered:
        print("  ★ 无触发项，迭代结束")
    for module, dim, comments in triggered:
        print(f"\n  [{module} × {dim}]")
        for a, c in comments.items():
            print(f"    - {a}: {c[:200]}{'...' if len(c) > 200 else ''}")
    return report, triggered


def format_optimization_prompt(module: str, dim: str, orig_text: str, comments: dict,
                                arxiv_id: str, manifest: dict) -> str:
    """Generate the optimization prompt for LLM to rewrite a module.

    Schema-correct version: rewrites the WHOLE module JSON (not just content_md),
    so figure_refs / table_refs / formula_refs stay in sync with content_md.
    """
    comment_lines = "\n".join(f"- {a}: {c}" for a, c in comments.items())
    module_def = next((m for m in manifest["modules"] if m["id"] == module), {})
    char_limit = module_def.get("char_limit", 2000)
    return f"""你是论文精读文档的编辑。修复模块（{module}）的「{dim}」维度问题。

# 论文原文（用于核对正确性）
arxiv: {arxiv_id}
首选: 读 <out_dir>/paper_sections.json（ar5iv HTML 提的 sections + paragraphs + equations，结构化）
fallback: 读 <out_dir>/paper.md（pymupdf4llm 抽的全文）
图像: <out_dir>/figures/ + tables/ + formulas/（paper-extract 出的高清图 + caption_text）

# 原始模块文本（_modules/{module}.json 的 content_md 字段）
{orig_text}

# 长度约束
- 模块 content_md ≤ {char_limit} 字符（manifest 规定）
- 太长要压缩；太短(< min(int(char_limit * 0.4), 600))说明漏了

# Agent 反馈（多个 agent 给 medium 或 low）
{comment_lines}

# 修复要求
1. 重点修复「{dim}」维度的具体问题
2. 保持 VLM 视角白话风格（类比、术语解释）
3. 保留模块 H1 标题 `# N. {module}` 不变
4. 保留引用块 / callout / 列表 / `![Figure](figures/...)` / `$$...$$` 等结构
5. **content_md 中绝对不要用 ASCII 双引号 `"`**——所有引号必须用全角「」或 “”
6. 保持 figure_refs[] / table_refs[] / formula_refs[] 列表里 path 与 content_md 里实际引用的 `![]()` 一致

# 写要求（必须）
- 用 Write 工具覆盖整个 _modules/{module}.json（含 module_id, content_md, figure_refs, table_refs, formula_refs, source_sections）
- 写完**立刻跑**验证命令：
  ```
  python3 -c "import json; d=json.load(open('<out_dir>/_modules/{module}.json')); print('OK len=', len(d['content_md']))"
  ```
- 只有返回 OK 才声明完成；不 OK 就再修一遍 content_md 引号

只输出 JSON 全文（不限其他）。"""


def main():
    ap = argparse.ArgumentParser(description="Aggregate scoring for paper-preread iteration")
    ap.add_argument("scores_json", help="JSON file with scoring outputs (single dict or list), or '-' for stdin")
    ap.add_argument("--rule", default="balanced", choices=["balanced", "strict", "conservative"])
    ap.add_argument("--max-iter", type=int, default=2)
    ap.add_argument("--current-iter", type=int, default=1)
    ap.add_argument("--skill-dir", default=None)
    args = ap.parse_args()
    skill_dir = Path(args.skill_dir) if args.skill_dir else find_skill_dir()
    manifest = load_manifest(skill_dir)
    raw = sys.stdin.read() if args.scores_json == '-' else open(args.scores_json).read()
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        score_dicts = [parsed]
    else:
        score_dicts = parsed
    print_report(score_dicts, manifest, rule=args.rule,
                 max_iter=args.max_iter, current_iter=args.current_iter)


if __name__ == "__main__":
    main()
