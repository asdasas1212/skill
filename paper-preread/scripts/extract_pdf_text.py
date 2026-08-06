#!/usr/bin/env python3
"""Extract full text + section tree from a literature PDF via pymupdf4llm.

用法: extract_pdf_text.py <paper.pdf> <out_dir>
产出:
  - paper.md         全文 markdown（去页眉/页脚/页码/arXiv 标识）
  - paper_meta.json  {sections: [...], n_chars, n_pages} — sections 树从 toc_items 提取

post-processing（清理非正文内容）:
  - 纯数字行（页码 "5" 或 "5 / 13"）
  - arXiv 标识（"arXiv:2409.18839v1 [cs.CV] 14 Sep 2024"）
  - 版权行（"© 20XX IEEE"、"© Springer"）
  - running header（同一短文本在 ≥3 页头部出现）
  - 孤立脚注 URL（"2 https://albumentations.ai"）
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Optional

import pymupdf4llm


ARXIV_RE = re.compile(r"^arXiv:\d{4}\.\d{4,5}(v\d+)?\s*\[", re.I)
PAGE_NUM_RE = re.compile(r"^\s*\d{1,4}(\s*/\s*\d{1,4})?\s*$")
COPYRIGHT_RE = re.compile(r"^©\s*(IEEE|Springer|Elsevier|ACM|20\d{2})", re.I)
FOOTNOTE_URL_RE = re.compile(r"^\d+\s+https?://\S+\s*$")


def is_noise(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    return bool(
        ARXIV_RE.match(s)
        or PAGE_NUM_RE.match(s)
        or COPYRIGHT_RE.match(s)
        or FOOTNOTE_URL_RE.match(s)
    )


def strip_page(lines: list, running_header: Optional[str]) -> list:
    out = []
    for l in lines:
        s = l.strip()
        if not s:
            out.append(l)
            continue
        if running_header and s == running_header:
            continue
        if is_noise(l):
            continue
        out.append(l)
    return out


def detect_running_header(pages_text: list[str]) -> Optional[str]:
    """Find a short line that appears at top of ≥3 pages → running header."""
    candidates: dict[str, int] = {}
    for txt in pages_text:
        lines = [l.strip() for l in txt.split("\n") if l.strip()][:2]
        for l in lines:
            if 5 < len(l) < 80:
                candidates[l] = candidates.get(l, 0) + 1
    for l, n in candidates.items():
        if n >= 3:
            return l
    return None


def main():
    pdf_path = sys.argv[1]
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)

    chunks = pymupdf4llm.to_markdown(pdf_path, page_chunks=True)
    pages_text = [c["text"] for c in chunks]
    running_header = detect_running_header(pages_text)

    cleaned_pages = []
    total_chars = 0
    for txt in pages_text:
        lines = txt.split("\n")
        cleaned = strip_page(lines, running_header)
        page_text = "\n".join(cleaned).strip()
        cleaned_pages.append(page_text)
        total_chars += len(page_text)

    paper_md = "\n\n---\n\n".join(cleaned_pages)

    # section tree（toc_items 格式: [[level, title, page], ...]）
    sections = []
    for c in chunks:
        for toc in c.get("toc_items", []) or []:
            if not isinstance(toc, (list, tuple)) or len(toc) < 3:
                continue
            level, title, page = toc[0], toc[1], toc[2]
            if not title:
                continue
            sections.append({
                "level": int(level),
                "title": str(title).strip(),
                "page": int(page) + 1,  # pymupdf4llm 0-indexed → 1-indexed
            })

    # 去重
    uniq, seen = [], set()
    for s in sections:
        k = (s["level"], s["title"])
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    sections = uniq

    with open(os.path.join(outdir, "paper.md"), "w") as f:
        f.write(paper_md + "\n")
    with open(os.path.join(outdir, "paper_meta.json"), "w") as f:
        json.dump({
            "n_pages": len(chunks),
            "n_chars": total_chars,
            "sections": sections,
            "running_header_detected": running_header,
        }, f, indent=2, ensure_ascii=False)

    print(f"✓ {len(chunks)} pages | {total_chars} chars | {len(sections)} sections")
    if running_header:
        print(f"  running header stripped: {running_header!r}")
    print(f"  → {outdir}/paper.md + paper_meta.json")


if __name__ == "__main__":
    main()