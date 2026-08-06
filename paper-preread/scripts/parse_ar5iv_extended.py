#!/usr/bin/env python3
"""parse_ar5iv_extended.py — extended ar5iv parser for paper-preread skill.

Builds on parse_ar5iv.py (figures/tables/title/abstract/sections) but adds the
content paper.md lacks: per-section paragraphs, inline equations (LaTeX from
<math alttext>), table cells (full cell matrix, not just captions).

Output: paper_sections.json alongside the standard meta.json / figs.json / imgs/.

Why: pymupdf4llm-extracted paper.md is noisy on pages with figures / tables
(pymupdf4llm cuts layout-rich pages into broken cell fragments — see OpenVLA
paper.md lines 33-40). ar5iv HTML is rendered from LaTeX source so paragraphs,
equations, and tables are semantically clean.

Usage:
    python3 parse_ar5iv_extended.py <arxiv_id> <outdir> [--download-imgs]
"""
from __future__ import annotations
import argparse
import html as htmllib
import json
import os
import re
import subprocess
import sys
import time
from html.parser import HTMLParser
from pathlib import Path


UA = "Mozilla/5.0 (paper-preread)"


def fetch(aid: str, retries: int = 2, timeout: int = 90) -> str:
    base = f"https://ar5iv.labs.arxiv.org/html/{aid}"
    last_err = None
    for i in range(retries + 1):
        try:
            r = subprocess.run(
                ["curl", "-sL", "--max-time", str(timeout), "-A", UA, base],
                capture_output=True, text=True, timeout=timeout + 30
            )
            if r.returncode == 0 and r.stdout and "<title>" in r.stdout:
                return r.stdout
            last_err = RuntimeError(f"curl rc={r.returncode}, len={len(r.stdout)}")
        except Exception as e:
            last_err = e
            if i < retries:
                time.sleep(2 + i * 2)
    raise RuntimeError(f"ar5iv fetch {aid} failed after {retries+1} tries: {last_err}")


# --------- text extraction helpers ---------

def clean_inline(t: str) -> str:
    """Strip tags but preserve math alttext as `[latex]` inline, and unescape entities.

    Also strips figure blocks (when called on a paragraph that contained inline
    figures, we lose them — that's intentional for the body text only).
    """
    t = re.sub(r'<math[^>]*alttext="([^"]*)"[^>]*>.*?</math>', r' [\1] ', t, flags=re.S)
    t = re.sub(r'<figure\b.*?</figure>', ' ', t, flags=re.S)  # drop figure blocks
    t = re.sub(r'<[^>]+>', ' ', t)
    t = htmllib.unescape(t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def extract_math_latex(t: str) -> list[str]:
    """Extract alttext from <math alttext="..."> tags in a chunk."""
    return re.findall(r'<math[^>]*alttext="([^"]*)"', t)


def key_terms(text: str) -> list[str]:
    """Cheap extractor: capitalized words, CamelCase, ALL-CAPS, hyphen-camel."""
    seen = set()
    terms = []
    for m in re.finditer(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+|[A-Z][A-Z0-9]+(?:[-_][A-Z0-9]+)*|[A-Z][A-Za-z0-9-]{2,})\b', text):
        t = m.group(1)
        if t in seen:
            continue
        if len(t) > 32:
            continue
        seen.add(t)
        terms.append(t)
    return terms[:40]


# --------- DOM parser for paragraph / section tree ---------

class LtxParser(HTMLParser):
    """Walk ar5iv HTML, emit (sections, tables, title).

    Stack-based: each <section class="ltx_section"> pushes a new section dict;
    paragraphs flow into the section at top of stack. Sections without
    explicit h-title get merged into parent. Math alttext is also captured
    per-section.

    Tables: any <figure class="ltx_table"> contains a <figcaption> and a <table>;
    we capture caption label + caption + cell matrix.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections: list[dict] = []
        self.tables: list[dict] = []
        self.title = ""

        # stack of "section dict" being built (in order of nesting)
        self._sec_stack: list[dict] = []
        # current paragraph buffer (for content of the open <p>)
        self._p_buf: list[str] = []
        # current text-title buffer (for content of open <h*>)
        self._h_buf: list[str] | None = None
        self._h_level: int = 0
        self._in_p_depth: int = 0
        # abstract state
        self._in_abstract = False
        # table state
        self._in_table_figure = False
        self._table_caption: list[str] = []
        self._table_caption_label: str = ""
        self._in_caption = False
        self._tbl_rows: list[list[str]] = []
        self._tbl_cur_row: list[str] | None = None
        self._tbl_cur_cell_buf: list[str] = []
        # header h1 title (top-level paper title) at <h1 class="ltx_title ltx_title_document">
        self._capturing_doc_title = False
        self._doc_title_buf: list[str] | None = None

    # ----- helpers -----

    def _flush_paragraph(self):
        if not self._p_buf:
            return
        text = clean_inline("".join(self._p_buf))
        # combine math alttext captured via <math> attrs with text-extracted
        # alttext (the former is more reliable; the latter catches stragglers)
        eqs_pending = []
        if self._sec_stack:
            eqs_pending = self._sec_stack[-1].pop("_inline_eqs_pending", [])
        # also include any alttext captured via extract_math_latex (text grep)
        text_eqs = extract_math_latex("".join(self._p_buf))
        # dedupe while preserving order
        seen = set()
        merged = []
        for e in eqs_pending + text_eqs:
            if e not in seen:
                seen.add(e)
                merged.append(e)
        self._p_buf = []
        if not text:
            return
        if not self._sec_stack:
            return
        cur = self._sec_stack[-1]
        cur["paragraphs"].append(text)
        for e in merged:
            cur["inline_equations"].append({"latex": e, "context": text[:80]})

    def _finalize_table(self):
        # close any in-progress row
        if self._tbl_cur_row is not None:
            cell = clean_inline("".join(self._tbl_cur_cell_buf))
            self._tbl_cur_row.append(cell)
            self._tbl_rows.append(self._tbl_cur_row)
            self._tbl_cur_row = None
            self._tbl_cur_cell_buf = []
        self.tables.append({
            "caption_label": self._table_caption_label,
            "caption": clean_inline("".join(self._table_caption)),
            "cells": self._tbl_rows,
        })
        self._in_table_figure = False
        self._table_caption = []
        self._table_caption_label = ""
        self._tbl_rows = []

    def _open_section(self, attrs_dict):
        sec = {
            "id": attrs_dict.get("id", ""),
            "level": 0,
            "title": "",
            "paragraphs": [],
            "inline_equations": [],
            "key_terms": [],
        }
        self._sec_stack.append(sec)

    def _close_section(self):
        self._flush_paragraph()
        if not self._sec_stack:
            return
        sec = self._sec_stack.pop()
        if sec["title"]:
            full_text = " ".join(sec["paragraphs"])
            sec["key_terms"] = key_terms(full_text)
            self.sections.append(sec)
        elif self._sec_stack:
            # anonymous wrapper — merge into parent
            parent = self._sec_stack[-1]
            parent["paragraphs"].extend(sec["paragraphs"])
            parent["inline_equations"].extend(sec["inline_equations"])

    # ----- HTMLParser callbacks -----

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""

        if tag == "section":
            if "ltx_abstract" in cls:
                self._in_abstract = True
            elif ("ltx_section" in cls
                  or "ltx_subsection" in cls
                  or "ltx_subsubsection" in cls
                  or "ltx_appendix" in cls):
                self._flush_paragraph()
                self._open_section(a)

        elif tag == "h1" and "ltx_title_document" in cls:
            self._capturing_doc_title = True
            self._doc_title_buf = []

        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and "ltx_title" in cls:
            self._flush_paragraph()
            self._h_buf = []
            self._h_level = int(tag[1])

        elif tag == "p":
            if self._sec_stack or self._in_abstract:
                if self._in_p_depth == 0:
                    self._flush_paragraph()
                self._in_p_depth += 1
                self._p_buf = []

        # Math alttext capture (alttext is in attribute, not text content)
        if tag == "math" and "alttext" in a and self._sec_stack:
            self._sec_stack[-1].setdefault("_inline_eqs_pending", []).append(a["alttext"])
            if self._in_p_depth > 0:
                self._p_buf.append(f' [{a["alttext"]}] ')

        # Table parsing
        if tag == "figure" and "ltx_table" in cls:
            self._in_table_figure = True
            self._table_caption_label = a.get("id", "")
            self._table_caption = []
            self._tbl_rows = []
            self._tbl_cur_row = None
            self._tbl_cur_cell_buf = []
            self._in_caption = False
        if self._in_table_figure:
            if tag == "figcaption":
                self._in_caption = True
            elif tag == "tr":
                # flush previous row
                if self._tbl_cur_row is not None:
                    cell = clean_inline("".join(self._tbl_cur_cell_buf))
                    self._tbl_cur_row.append(cell)
                    self._tbl_rows.append(self._tbl_cur_row)
                self._tbl_cur_row = []
                self._tbl_cur_cell_buf = []
            elif tag in ("td", "th"):
                if self._tbl_cur_row is not None:
                    cell = clean_inline("".join(self._tbl_cur_cell_buf))
                    self._tbl_cur_row.append(cell)
                self._tbl_cur_cell_buf = []

    def handle_endtag(self, tag):
        if tag == "section":
            # close abstract first
            self._in_abstract = False
            if self._sec_stack:
                self._close_section()
        elif tag == "h1" and self._capturing_doc_title:
            if self._doc_title_buf is not None:
                self.title = clean_inline("".join(self._doc_title_buf))
            self._capturing_doc_title = False
            self._doc_title_buf = None
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if self._h_buf is not None and self._sec_stack:
                title = clean_inline("".join(self._h_buf))
                self._sec_stack[-1]["title"] = title
                self._sec_stack[-1]["level"] = self._h_level
                self._h_buf = None
        elif tag == "p" and self._in_p_depth > 0:
            self._in_p_depth -= 1
            if self._in_p_depth == 0:
                self._flush_paragraph()
        # Table
        if self._in_table_figure:
            if tag == "figcaption":
                self._in_caption = False
            elif tag in ("td", "th"):
                pass  # cell handled at next tr / figure close
            elif tag == "figure":
                self._finalize_table()
                self._in_table_figure = False

    def handle_data(self, data):
        # doc title
        if self._capturing_doc_title and self._doc_title_buf is not None:
            self._doc_title_buf.append(data)
        # section heading
        if self._h_buf is not None:
            self._h_buf.append(data)
        # paragraph body
        if self._in_p_depth > 0 and (self._sec_stack or getattr(self, "_in_abstract", False)):
            self._p_buf.append(data)
        # table cell
        if self._in_table_figure and self._tbl_cur_row is not None and not self._in_caption:
            self._tbl_cur_cell_buf.append(data)
        # table caption
        if self._in_table_figure and self._in_caption:
            self._table_caption.append(data)


# --------- CLI ---------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arxiv_id")
    ap.add_argument("outdir")
    ap.add_argument("--download-imgs", action="store_true",
                    help="also download all ar5iv images (slow)")
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching ar5iv for {args.arxiv_id}...")
    src = fetch(args.arxiv_id)
    print(f"  fetched {len(src)} chars")

    parser = LtxParser()
    parser.feed(src)
    sections, tables = parser.sections, parser.tables
    print(f"  sections: {len(sections)} | tables: {len(tables)}")
    n_para = sum(len(s["paragraphs"]) for s in sections)
    n_eq = sum(len(s["inline_equations"]) for s in sections)
    n_terms = sum(len(s.get("key_terms", [])) for s in sections)
    print(f"  paragraphs: {n_para} | inline_equations: {n_eq} | key_terms: {n_terms}")

    abstract_match = re.search(r'<section[^>]*class="ltx_abstract"[^>]*>(.*?)</section>', src, re.S)
    abstract = clean_inline(abstract_match.group(1)) if abstract_match else ""

    n_img_dl = 0
    if args.download_imgs:
        imgs_dir = outdir / "imgs"
        imgs_dir.mkdir(exist_ok=True)
        all_srcs = re.findall(r'src="(/html/' + re.escape(args.arxiv_id) + r'/assets/[^"]+)"', src)
        seen = set()
        for s in all_srcs:
            if s in seen:
                continue
            seen.add(s)
            fname = os.path.basename(s.split("?")[0])
            local = imgs_dir / fname
            try:
                subprocess.run(
                    ["curl", "-sL", "--max-time", "30", "-o", str(local), "https://ar5iv.labs.arxiv.org" + s],
                    timeout=60, check=False
                )
                n_img_dl += 1
            except Exception:
                pass

    paper_sections = {
        "source": "ar5iv",
        "arxiv_id": args.arxiv_id,
        "fallback_source": "pymupdf4llm",
        "title": parser.title or "",
        "abstract": abstract,
        "sections": sections,
        "tables": tables,
        "stats": {
            "n_sections": len(sections),
            "n_paragraphs": n_para,
            "n_inline_equations": n_eq,
            "n_tables": len(tables),
            "n_images_downloaded": n_img_dl,
        },
    }
    out_path = outdir / "paper_sections.json"
    out_path.write_text(json.dumps(paper_sections, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✓ Wrote {out_path}")

    # Patch meta.json for backward compat
    meta_path = outdir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            meta["paper_sections_relpath"] = "paper_sections.json"
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  ↻ Patched {meta_path}")
        except Exception as e:
            print(f"  WARN: failed to patch meta.json: {e}")


if __name__ == "__main__":
    main()
