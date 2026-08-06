#!/usr/bin/env python3
"""Extract figures from a paper PDF at high resolution.

Workflow:
  1. Find pages that contain "Figure N" or "Fig. N" captions via pymupdf4llm
  2. For each figure, find the caption y position, then crop the area above
     the caption at the page width, then 4-6× zoom render to PNG.

Usage:
  python3 extract_pdf_figures.py <paper.pdf> <out_dir> [--fig N] [--zoom 4] [--all]

  --fig N      extract only figure N (1-indexed)
  --all        extract all figures (default if --fig not given)
  --zoom 4     render zoom (default 4, use 5-6 for tiny subfigures)

Output: <out_dir>/imgs/figN_full.png (or figN(a).png if a/b/c subfigs detected)
"""
import sys, os, re, json, argparse
import pymupdf4llm, fitz

def find_figure_pages(pdf):
    """Return dict: figure_num -> page_idx (0-indexed) for all Fig. N captions."""
    chunks = pymupdf4llm.to_markdown(pdf, page_chunks=True)
    found = {}
    for c in chunks:
        page_idx = c["metadata"]["page"] - 1  # pymupdf4llm 1-indexed → fitz 0-indexed
        for m in re.finditer(r'(?:Fig\.|Figure)\s*(\d+)\s*[\.\:]([^\n]+)', c["text"]):
            num = int(m.group(1))
            cap_start = m.group(2)[:60].strip()
            # Skip Table captions (they don't have "Fig." prefix)
            # Each figure number, keep the first page where its caption appears
            if num not in found:
                found[num] = {"page": page_idx, "caption": cap_start}
    return found


def find_caption_y(page, fig_num):
    """Find the y-coordinate of 'Fig. N.' or 'Figure N.' caption block.
    Prefer the BOTTOMMOST block that starts with 'Fig. N' to avoid matching inline refs like 'Fig. 1(a)' in body text.
    """
    blocks = page.get_text("blocks")
    candidates = []
    for b in blocks:
        txt = b[4].lstrip()
        # Match block that STARTS with "Fig. N." or "Figure N:" (not inline refs)
        if re.match(rf'(?:Fig\.|Figure)\s*{fig_num}\s*[\.\:]', txt):
            candidates.append((b[1], b[3], txt[:80]))
    if not candidates:
        return None
    # Pick the LOWEST y0 — that's the actual caption, not an inline reference
    candidates.sort(key=lambda x: x[0])
    return candidates[-1]


def find_figure_body_bounds(page, caption_y0):
    """Find the top y where the figure body starts (after page header, skipping subfig labels)."""
    blocks = page.get_text("blocks")
    blocks.sort(key=lambda b: b[1])
    # Subfigure label patterns: "(a) ... (b) ... (c) ..." — short block, near caption
    subfig_re = re.compile(r'\([a-z]\)\s+\S')
    for b in blocks:
        if b[1] < 100: continue
        if b[3] >= caption_y0: continue
        # Skip subfigure labels (short block with (a)/(b)/(c) markers)
        txt = b[4].strip()
        if subfig_re.search(txt) and len(txt) < 200:
            continue
        # Skip page header-like text (page numbers)
        if re.match(r'^\d+\s*$', txt):
            continue
        return b[1] - 4
    return 105  # fallback


def extract_figure(doc, page_idx, fig_num, out_path, zoom=4):
    """Extract a single figure from the page."""
    page = doc[page_idx]
    cap = find_caption_y(page, fig_num)
    if cap is None:
        print(f"  Fig {fig_num}: caption not found on page {page_idx+1}")
        return False
    cap_y0, cap_y1, _ = cap
    body_top = find_figure_body_bounds(page, cap_y0)
    # Crop the figure region: full page width, from body_top to caption start
    rect = fitz.Rect(40, body_top, page.rect.width - 40, cap_y0 - 2)
    # Ensure not degenerate
    if rect.width < 50 or rect.height < 30:
        print(f"  Fig {fig_num}: degenerate rect {rect}")
        return False
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
    pix.save(out_path)
    print(f"  Fig {fig_num} → {out_path} ({pix.width}×{pix.height})")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out_dir")
    ap.add_argument("--fig", type=int, default=None, help="Extract only figure N (1-indexed)")
    ap.add_argument("--zoom", type=int, default=4)
    ap.add_argument("--all", action="store_true", help="Extract all figures")
    args = ap.parse_args()

    os.makedirs(args.out_dir + "/imgs", exist_ok=True)
    doc = fitz.open(args.pdf)
    found = find_figure_pages(args.pdf)
    print(f"Found {len(found)} figures in {args.pdf}")
    for n, info in sorted(found.items()):
        print(f"  Fig {n}: page {info['page']+1} — {info['caption']}")

    targets = [args.fig] if args.fig else sorted(found.keys())
    for n in targets:
        if n not in found:
            print(f"  Fig {n}: not found")
            continue
        out = f"{args.out_dir}/imgs/fig{n}_full.png"
        extract_figure(doc, found[n]["page"], n, out, zoom=args.zoom)

    # Save a manifest
    manifest = {
        "pdf": args.pdf,
        "figures": {str(n): {"page": info["page"]+1, "caption": info["caption"]}
                    for n, info in found.items()},
    }
    with open(args.out_dir + "/pdf_figures.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\nManifest saved to {args.out_dir}/pdf_figures.json")


if __name__ == "__main__":
    main()