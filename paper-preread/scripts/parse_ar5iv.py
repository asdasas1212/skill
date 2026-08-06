#!/usr/bin/env python3
"""Parse an ar5iv paper: extract title/abstract/sections/figures(tables)/captions, download all images."""
import re, os, json, sys, subprocess, html as htmllib

aid = sys.argv[1]
outdir = sys.argv[2]
base = f"https://ar5iv.labs.arxiv.org/html/{aid}"
src = subprocess.run(
    ["curl", "-sL", "--max-time", "90", base],
    capture_output=True, text=True, timeout=120
).stdout

os.makedirs(outdir + "/imgs", exist_ok=True)

def clean(t):
    t = re.sub(r'<math[^>]*alttext="([^"]*)"[^>]*>.*?</math>', r' [\1] ', t, flags=re.S)  # keep latex alt
    t = re.sub(r'<[^>]+>', ' ', t)
    t = htmllib.unescape(t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

# ---- title ----
title = ""
m = re.search(r'<h1[^>]*class="ltx_title[^"]*"[^>]*>(.*?)</h1>', src, re.S)
if not m:
    m = re.search(r'<title>([^<]*)</title>', src)
    title = m.group(1).strip() if m else ""
else:
    title = clean(m.group(1))

# ---- abstract ----
abstract = ""
m = re.search(r'<div[^>]*class="ltx_abstract"[^>]*>(.*?)</div>\s*</div>', src, re.S) or re.search(r'<section[^>]*class="ltx_abstract"[^>]*>(.*?)</section>', src, re.S)
if m:
    abstract = clean(m.group(1))
    abstract = re.sub(r'^.*?Abstract\s*', '', abstract)

# ---- figures (with figcaption) ----
# Spacer detection: ar5iv pages often have tiny "Time" / "axis" / "divider" PNGs
# (typical width=14 or height < 50). Mark them so build scripts don't auto-pick.
# Also tag every image with its enclosing figure id for traceability.
figures = []
for m in re.finditer(r'<figure[^>]*id="([^"]+)"[^>]*>(.*?)</figure>', src, re.S):
    fig_id = m.group(1)
    block = m.group(2)
    imgs_raw = re.findall(r'<img[^>]*src="([^"]+)"[^>]*>', block)
    cap_m = re.search(r'<figcaption[^>]*>(.*?)</figcaption>', block, re.S)
    cap = clean(cap_m.group(1)) if cap_m else ""
    label = ""
    lm = re.search(r'(Figure\s*\d+|Table\s*\d+|图\s*\d+)', cap)
    if lm: label = lm.group(1)
    for s in imgs_raw:
        if not s.startswith("/html/"): continue
        # Detect spacer: an image element preceded by width="<50" or aspect ratio extreme
        # Re-find the specific <img> tag to inspect width/height
        m2 = re.search(r'<img[^>]*src="' + re.escape(s) + r'"[^>]*>', block)
        w = re.search(r'width="(\d+)"', m2.group(0)) if m2 else None
        h = re.search(r'height="(\d+)"', m2.group(0)) if m2 else None
        wi, hi = (int(w.group(1)) if w else None), (int(h.group(1)) if h else None)
        is_spacer = False
        if (wi is not None and wi < 50) or (hi is not None and hi < 50):
            is_spacer = True
        if wi is not None and hi is not None and (wi < 80 or hi < 80):
            # small diagrams (architecture boxes) are also bad for display
            # but we'll only auto-skip obvious spacers
            pass
        figures.append({
            "src": s, "url": "https://ar5iv.labs.arxiv.org" + s,
            "caption": cap, "label": label,
            "fig_id": fig_id,  # enclosing <figure id="...">
            "width": wi, "height": hi,
            "spacer": is_spacer,
            "extraction": "pdf_preferred",  # hint for build script
        })

# ---- section headings ----
sections = []
for m in re.finditer(r'<h([1-6])[^>]*class="ltx_title[^"]*"[^>]*>(.*?)</h\1>', src, re.S):
    t = clean(m.group(2))
    if t and not t.lower().startswith("abstract"):
        sections.append({"level": int(m.group(1)), "title": t})

# ---- tables (caption + first rows text) ----
tables = []
for m in re.finditer(r'<figure[^>]*class="ltx_table"[^>]*>(.*?)</figure>', src, re.S):
    cap_m = re.search(r'<figcaption[^>]*>(.*?)</figcaption>', m.group(1), re.S)
    cap = clean(cap_m.group(1)) if cap_m else ""
    tables.append({"caption": cap})

# ---- download all images ----
downloaded = {}
all_imgs = re.findall(r'src="(/html/%s/assets/[^"]+)"' % aid, src)
seen = set()
for s in all_imgs:
    if s in seen: continue
    seen.add(s)
    fname = os.path.basename(s.split("?")[0])
    local = outdir + "/imgs/" + fname
    try:
        subprocess.run(
            ["curl", "-sL", "--max-time", "30", "-o", local, "https://ar5iv.labs.arxiv.org"+s],
            timeout=60, check=False
        )
        downloaded[s] = fname
    except Exception as e:
        downloaded[s] = "ERR:"+str(e)

meta = {"arxiv": aid, "title": title, "abstract": abstract,
        "sections": sections, "figures": figures, "tables": tables,
        "n_images_downloaded": len([v for v in downloaded.values() if not v.startswith("ERR")])}
with open(outdir + "/meta.json", "w") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
with open(outdir + "/figs.json", "w") as f:
    json.dump(figures, f, ensure_ascii=False, indent=2)

print(f"=== {aid}: {title[:60]} ===")
print(f"abstract: {abstract[:300]}")
print(f"sections: {len(sections)} | figures: {len(figures)} | tables: {len(tables)} | imgs dl: {meta['n_images_downloaded']}")
print("\n--- FIGURES ---")
for i,fg in enumerate(figures):
    spacer_tag = " [SPACER]" if fg.get('spacer') else ""
    print(f"[{i}] {fg['label']:10s} | {os.path.basename(fg['src']):25s} | {fg['width']}x{fg['height']}{spacer_tag} | {fg['caption'][:80]}")
print("\n--- USAGE HINT ---")
print("Spacer images (width<50 OR height<50) are tagged 'spacer:true'.")
print("Build scripts should PREFER figures with spacer:false.")
print("For sharper display, extract figures from the PDF directly using extract_pdf_figures.py")
