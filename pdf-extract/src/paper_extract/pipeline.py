"""高层 API：编排 layout + ocr + formula_det + formula_rec。

CLI 入口 `paper-extract` 和顶层 `extract_all()` 都走这里。
"""

import json
from pathlib import Path


def _device_banner():
    """Print GPU availability once. Models still default to CPU unless GPU is wired in."""
    try:
        import torch
        cuda = torch.cuda.is_available()
        mps = getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
    except Exception:
        cuda, mps = False, False
    if cuda:
        print("[device] CUDA available — runtime paths will use it when invoked with --formulas", flush=True)
    elif mps:
        print("[device] MPS available — runtime paths default to CPU for stability", flush=True)
    else:
        print("[device] CPU only — formula stage is the slowest; pass --no-formulas to skip it", flush=True)


def extract(
    pdf_path: str,
    out_dir: str,
    *,
    layout: bool = True,
    ocr: bool = True,
    formulas: bool = True,
    dpi: int = 200,
    conf: float = 0.25,
    crop_classes: set | None = None,
) -> dict:
    """一键跑指定模块。

    Args:
        crop_classes: 传给 layout module 决定 crop 哪些 class；default = {figure, table}

    Returns:
        dict: {
          'layout': {...},     # layout 模块的返回
          'formulas': {...},   # formula_det+rec 的返回
          'captions': [...],   # ocr 模块的返回
          'summary_path': Path, # summary.json 路径
        }
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = {'layout': None, 'formulas': None, 'captions': []}

    _device_banner()
    if not formulas:
        print("[hint] formulas stage skipped (--no-formulas); pull formulas from ar5iv HTML instead", flush=True)

    # Stage 1: layout detection (figures/tables bbox + crops)
    layout_result = None
    if layout:
        print(f"[stage 1/3] layout start — {Path(pdf_path).name}", flush=True)
        from .layout import extract as layout_extract
        layout_result = layout_extract(
            pdf_path, str(out), dpi=dpi, conf=conf, crop_classes=crop_classes,
        )
        n_l = len(layout_result.get('figure_crops', [])) + len(layout_result.get('table_crops', []))
        print(f"[stage 1/3] layout done — {n_l} crops", flush=True)
        result['layout'] = layout_result

    # Stage 2: formula detect + rec (skippable if ar5iv covers formulas)
    formula_det_result = None
    if formulas:
        print(f"[stage 2/3] formulas start (this is the slow stage ~1-2 min on CPU)", flush=True)
        from .formula_det import extract as formula_det_extract
        from .formula_rec import extract_with_latex
        formula_det_result = formula_det_extract(
            pdf_path, str(out), dpi=dpi, conf=conf
        )
        crops = formula_det_result['crops']
        if crops:
            latex_json = out / 'formulas' / '_latex.json'
            extract_with_latex(crops, str(latex_json))
        print(f"[stage 2/3] formulas done — {len(crops)} crops", flush=True)
        result['formulas'] = formula_det_result

    # Stage 3: caption OCR (PaddleOCR)
    if ocr:
        print(f"[stage 3/3] ocr start", flush=True)
        from .ocr import extract as ocr_extract
        result['captions'] = ocr_extract(
            str(out), pdf_path=pdf_path, dpi=dpi
        )
        print(f"[stage 3/3] ocr done — {len(result['captions'])} captions", flush=True)

    # 汇总
    summary = _build_summary(layout_result, formula_det_result, result['captions'], out)
    summary_path = out / 'summary.json'
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    result['summary_path'] = summary_path

    n_fig = sum(1 for s in summary if s.get('type') == 'figure')
    n_tbl = sum(1 for s in summary if s.get('type') == 'table')
    n_fml = sum(1 for s in summary if s.get('type') == 'formula')
    print(f'✓ {n_fig} figures + {n_tbl} tables + {n_fml} formulas → {out}')

    return result


def _build_summary(layout_result, formula_result, captions, out_dir):
    """汇总各模块产物为统一 summary.json schema。"""
    out_dir = Path(out_dir)
    summary = []

    cap_lookup = {(c['page'], c['type'], tuple(c['bbox'])): c for c in captions}
    if layout_result:
        for elem in layout_result.get('all_elements', []):
            if elem['class'] not in ('figure', 'table'):
                continue
            entry = {
                'page': elem['page'],
                'type': elem['class'],
                'bbox': elem['bbox'],
                'conf': elem['conf'],
            }
            cap = cap_lookup.get((elem['page'], elem['class'], tuple(elem['bbox'])))
            if cap:
                entry['caption_bbox'] = cap['caption_bbox']
                entry['caption_image'] = cap['caption_image']
                entry['caption_text'] = cap['caption_text']
            summary.append(entry)

    if formula_result:
        latex_data = {}
        crops = formula_result.get('crops') or []
        latex_path = Path(crops[0]).parent / '_latex.json' if crops else None
        if latex_path and latex_path.exists():
            latex_data = {
                rec['image']: rec['latex']
                for rec in json.loads(latex_path.read_text())
            }
        for det in formula_result.get('detections', []):
            entry = {
                'page': det['page'],
                'type': 'formula',
                'subtype': det['subtype'],
                'bbox': det['bbox'],
                'conf': det['conf'],
            }
            img = det.get('image')
            if img:
                entry['image'] = str(Path(img).relative_to(out_dir))
                entry['latex'] = latex_data.get(img, '')
            summary.append(entry)

    return summary