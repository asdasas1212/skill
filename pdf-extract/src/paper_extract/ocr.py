"""PaddleOCR 抽取 caption 文字。

依赖：layout.extract() 已落 page_NNN.json（每页元素含 caption bbox）。
本模块：读 page_NNN.json，找 figure/table，配对最近的 figure_caption/table_caption，
       裁出 caption 区域，跑 PaddleOCR 拿文字，写回 page_NNN.json 的 elements[i].caption_text。

输出：captions/<file>.png + summary.json（带 caption_text 字段）。
"""

import json
from pathlib import Path
from typing import Optional

import cv2
import fitz
import numpy as np

_OCR = None


def _get_ocr(lang: str = 'ch'):
    global _OCR
    if _OCR is None:
        from paddleocr import PaddleOCR
        from .models import get_ocr_det_model_dir, get_ocr_rec_model_dir
        _OCR = PaddleOCR(
            use_angle_cls=False,
            lang=lang,
            show_log=False,
            det_model_dir=get_ocr_det_model_dir(),
            rec_model_dir=get_ocr_rec_model_dir(),
        )
    return _OCR


def _nearest_caption_bbox(elements: list, target_bbox: list, caption_class: str):
    """y 距离最近匹配 caption bbox。"""
    best, best_d = None, 1e18
    cy = (target_bbox[1] + target_bbox[3]) / 2
    for e in elements:
        if e['class'] != caption_class:
            continue
        d = abs((e['bbox'][1] + e['bbox'][3]) / 2 - cy)
        if d < best_d:
            best_d = d
            best = e['bbox']
    return best


def _render_page(pdf_path: str, page_idx_1based: int, dpi: int = 200) -> Optional[np.ndarray]:
    doc = fitz.open(pdf_path)
    try:
        if page_idx_1based - 1 >= len(doc):
            return None
        page = doc[page_idx_1based - 1]
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, 3
        )
    finally:
        doc.close()


def _ocr_text(ocr, img: np.ndarray) -> str:
    res = ocr.ocr(img, cls=False)
    if not res or not res[0]:
        return ''
    return ' '.join(line[1][0] for line in res[0]).strip()


def extract(
    out_dir: str,
    pdf_path: Optional[str] = None,
    *,
    dpi: int = 200,
    lang: str = 'ch',
    save_crops: bool = True,
    target_classes: Optional[set] = None,
) -> list[dict]:
    """对已落 page_NNN.json 的目录跑 OCR。

    Args:
        out_dir: 含 page_NNN.json 的目录
        pdf_path: 原 PDF（用于反查 page 图像）。如果 page_*.json 中已含 image 路径也可省。
        target_classes: 要配 caption 的元素类别，默认 {'figure', 'table'}

    Returns:
        list[dict]: [{page, type, bbox, image, caption_image, caption_text}, ...]
    """
    target_classes = target_classes or {'figure', 'table'}
    out = Path(out_dir)
    cap_dir = out / 'captions'
    if save_crops:
        cap_dir.mkdir(parents=True, exist_ok=True)

    ocr = _get_ocr(lang=lang)
    summary = []

    for page_json_path in sorted(out.glob('page_*.json')):
        page = json.loads(page_json_path.read_text())
        elements = page['elements']
        page_idx = page['page']

        # 反查 page 图像
        page_img = None
        if pdf_path:
            page_img = _render_page(pdf_path, page_idx, dpi=dpi)
        if page_img is None:
            # 没 PDF 路径就跳过 OCR
            continue

        # 对每个 figure/table 元素配 caption 并 OCR
        for j, e in enumerate(elements):
            if e['class'] not in target_classes:
                continue
            cap_class = (
                'figure_caption' if e['class'] == 'figure' else 'table_caption'
            )
            cap_bbox = _nearest_caption_bbox(elements, e['bbox'], cap_class)
            if cap_bbox is None:
                continue

            cx1, cy1, cx2, cy2 = cap_bbox
            cap_img = page_img[cy1:cy2, cx1:cx2]
            cap_path = None
            if save_crops:
                cap_path = cap_dir / f'page{page_idx:03d}_{e["class"]}_{j:02d}_cap.png'
                cv2.imwrite(str(cap_path), cap_img)

            text = _ocr_text(ocr, cap_img)
            # 写回 page_NNN.json（追加 caption_text）
            elements[j]['caption_text'] = text
            elements[j]['caption_bbox'] = cap_bbox

            summary.append({
                'page': page_idx,
                'type': e['class'],
                'bbox': e['bbox'],
                'conf': e['conf'],
                'caption_bbox': cap_bbox,
                'caption_image': str(cap_path.relative_to(out)) if cap_path else None,
                'caption_text': text,
            })

        page_json_path.write_text(
            json.dumps(page, indent=2, ensure_ascii=False)
        )

    # 写 summary.json
    (out / 'caption_summary.json').write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    return summary