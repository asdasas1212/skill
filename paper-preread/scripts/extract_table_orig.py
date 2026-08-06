#!/usr/bin/env python3
"""
Extract a Table region from a PDF as a PNG image, using PyMuPDF + pymupdf4llm.

Usage:
    python3 extract_table_orig.py <pdf> <table_no> <out_path> \
        [--page 0] [--zoom 4]

Strategy:
  1. Use pymupdf4llm to find the page containing the table caption.
  2. Use fitz.search_for to locate the caption "Table N:" coords.
  3. Use get_text('blocks') to find the table header (above caption) and full extent.
  4. Crop with fitz.Rect + 4x zoom (default), save PNG.

Note: PyMuPDF's find_tables() requires bordered tables; most LaTeX-rendered
PDFs (CVPR/IEEE) lack borders, so we manually find the caption and use blocks.
"""
import sys, fitz, pymupdf4llm, argparse

def find_table_region(pdf_path, table_no, page_hint=None):
    """Return (page_index_0based, caption_y, table_top_y, table_bottom_y, x_left, x_right)."""
    pdf = fitz.open(pdf_path)
    # 1. pymupdf4llm: find page with caption
    chunks = pymupdf4llm.to_markdown(pdf_path, page_chunks=True)
    target_page = None
    for c in chunks:
        if f"Table {table_no}." in c["text"] or f"Table {table_no}:" in c["text"]:
            target_page = c["metadata"]["page"] - 1  # pymupdf4llm 1-indexed → fitz 0-indexed
            break
    if target_page is None and page_hint is not None:
        target_page = page_hint
    if target_page is None:
        raise RuntimeError(f"Table {table_no} not found in PDF")
    page = pdf[target_page]
    # 2. Find caption bbox
    cap = None
    for kw in [f"Table {table_no}.", f"Table {table_no}:"]:
        for inst in page.search_for(kw):
            cap = inst
            break
        if cap:
            break
    if cap is None:
        raise RuntimeError(f"Table {table_no} caption not found on page {target_page}")
    # 3. Find table blocks above caption (table data + header)
    # Restrict to same column as caption to avoid catching prose in adjacent column
    blocks = page.get_text("blocks")
    same_col_blocks = [b for b in blocks if b[1] < cap.y0 and abs(b[0] - cap.x0) < 100]
    if not same_col_blocks:
        raise RuntimeError("No table blocks in same column above caption")
    table_top = min(b[1] for b in same_col_blocks)
    table_bottom = max(b[3] for b in same_col_blocks)
    x_left = min(b[0] for b in same_col_blocks)
    x_right = max(b[2] for b in same_col_blocks)
    # bound x_left to cap.x0 - 50 to avoid catching adjacent column prose
    x_left = max(x_left, cap.x0 - 50)
    # extend slightly to include caption
    cap_bottom = max((b[3] for b in blocks if b[1] >= cap.y0 - 5 and b[3] <= cap.y0 + 200), default=cap.y1)
    return target_page, cap.y0, table_top, max(cap_bottom, cap.y1), x_left, x_right

def crop_table(pdf_path, table_no, out_path, page_hint=None, zoom=4.0):
    page_idx, cap_y, top, bottom, x_left, x_right = find_table_region(pdf_path, table_no, page_hint)
    pdf = fitz.open(pdf_path)
    page = pdf[page_idx]
    # Add a small margin
    rect = fitz.Rect(max(0, x_left - 5), max(0, top - 5), min(page.rect.width, x_right + 5), min(page.rect.height, bottom + 10))
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
    pix.save(out_path)
    print(f"saved {out_path}  size={pix.width}x{pix.height}  page={page_idx}  rect={rect}")
    # verify
    print("--- text in cropped region ---")
    print(page.get_text("text", clip=rect))
    return out_path

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("table_no", type=int)
    ap.add_argument("out_path")
    ap.add_argument("--page", type=int, default=None, help="0-indexed page hint (pymupdf4llm auto-detect if omitted)")
    ap.add_argument("--zoom", type=float, default=4.0)
    args = ap.parse_args()
    crop_table(args.pdf, args.table_no, args.out_path, args.page, args.zoom)
