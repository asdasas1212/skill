"""布局检测：figure / table / caption / title / formula 等 bbox。

DocLayout-YOLO 10 类输出：
  0 title, 1 plain text, 2 abandon,
  3 figure, 4 figure_caption,
  5 table,  6 table_caption, 7 table_footnote,
  8 isolate_formula, 9 formula_caption
"""

import json
from pathlib import Path
from typing import Generator, Optional

import cv2
import fitz
import numpy as np

LAYOUT_CLASSES = {
    0: 'title',
    1: 'plain text',
    2: 'abandon',
    3: 'figure',
    4: 'figure_caption',
    5: 'table',
    6: 'table_caption',
    7: 'table_footnote',
    8: 'isolate_formula',
    9: 'formula_caption',
}

CROP_CLASSES = {'figure', 'table'}


def render_pdf(pdf_path: str, dpi: int = 200) -> Generator[tuple, None, None]:
    """Yield (page_idx_0based, img_bgr, width, height) per page."""
    doc = fitz.open(pdf_path)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, 3
            )
            yield i, img, pix.width, pix.height
    finally:
        doc.close()


def _load_model(model_path: Optional[str] = None):
    from doclayout_yolo import YOLOv10
    if model_path is None:
        from .models import get_layout_model_path
        model_path = get_layout_model_path()
    return YOLOv10(model_path)


def detect(
    model,
    img: np.ndarray,
    conf: float = 0.25,
    iou: float = 0.45,
    img_size: int = 1024,
) -> list[dict]:
    res = model.predict(
        img,
        imgsz=img_size,
        conf=conf,
        iou=iou,
        verbose=False,
        device='cpu',
    )[0]
    boxes = res.boxes
    out = []
    for b, c, s in zip(
        boxes.xyxy.cpu().numpy(),
        boxes.cls.cpu().numpy().astype(int),
        boxes.conf.cpu().numpy(),
    ):
        out.append({
            'class': LAYOUT_CLASSES[int(c)],
            'conf': round(float(s), 3),
            'bbox': [int(x) for x in b],
        })
    return out


def extract(
    pdf_path: str,
    out_dir: str,
    *,
    model_path: Optional[str] = None,
    conf: float = 0.25,
    iou: float = 0.45,
    dpi: int = 200,
    save_crops: bool = True,
    crop_classes: Optional[set] = None,
) -> dict:
    """跑布局检测，落每页 JSON + figure/table crops。

    Returns:
        dict: {
          'page_jsons': [Path, ...],
          'figure_crops': [Path, ...],
          'table_crops': [Path, ...],
          'all_elements': [dict, ...]   # 跨页汇总
        }
    """
    crop_classes = crop_classes or CROP_CLASSES
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig_dir = out / 'figures'
    tbl_dir = out / 'tables'
    if save_crops and crop_classes:
        if 'figure' in crop_classes:
            fig_dir.mkdir(parents=True, exist_ok=True)
        if 'table' in crop_classes:
            tbl_dir.mkdir(parents=True, exist_ok=True)

    model = _load_model(model_path)
    page_jsons = []
    figure_crops = []
    table_crops = []
    all_elements = []

    for page_idx, img, w, h in render_pdf(pdf_path, dpi=dpi):
        records = detect(model, img, conf=conf, iou=iou)
        page_path = out / f'page_{page_idx + 1:03d}.json'
        page_path.write_text(
            json.dumps(
                {'page': page_idx + 1, 'image_size': [w, h], 'elements': records},
                indent=2,
                ensure_ascii=False,
            )
        )
        page_jsons.append(page_path)

        for j, rec in enumerate(records):
            rec_full = {
                'page': page_idx + 1,
                'class': rec['class'],
                'conf': rec['conf'],
                'bbox': rec['bbox'],
            }
            all_elements.append(rec_full)
            if not save_crops or rec['class'] not in crop_classes:
                continue
            x1, y1, x2, y2 = rec['bbox']
            target = fig_dir if rec['class'] == 'figure' else tbl_dir
            crop_path = target / f'page{page_idx + 1:03d}_{rec["class"]}_{j:02d}.png'
            cv2.imwrite(str(crop_path), img[y1:y2, x1:x2])
            if rec['class'] == 'figure':
                figure_crops.append(crop_path)
            else:
                table_crops.append(crop_path)

    return {
        'page_jsons': page_jsons,
        'figure_crops': figure_crops,
        'table_crops': table_crops,
        'all_elements': all_elements,
    }