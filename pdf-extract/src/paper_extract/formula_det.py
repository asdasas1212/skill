"""公式检测：YOLOv8 ft 检测 inline + isolated formula bbox。

模型输出 2 类：0 inline, 1 isolated。
"""

from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .layout import render_pdf

FORMULA_CLASSES = {0: 'inline', 1: 'isolated'}


def _load_model(model_path: Optional[str] = None):
    from ultralytics import YOLO
    if model_path is None:
        from .models import get_formula_det_model_path
        model_path = get_formula_det_model_path()
    return YOLO(model_path)


def detect(
    model,
    img: np.ndarray,
    conf: float = 0.25,
    iou: float = 0.45,
    img_size: int = 768,
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
            'subtype': FORMULA_CLASSES[int(c)],
            'conf': round(float(s), 3),
            'bbox': [int(x) for x in b],
        })
    return out


def extract(
    pdf_path: str,
    out_dir: str,
    *,
    dpi: int = 200,
    model_path: Optional[str] = None,
    conf: float = 0.25,
    iou: float = 0.45,
    save_crops: bool = True,
) -> dict:
    """跑公式检测，落 formulas/<file>.png。

    Returns:
        dict: {
          'crops': [Path, ...],   # 按 page 顺序
          'detections': [dict, ...],  # 全量检测结果
        }
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fml_dir = out / 'formulas'
    if save_crops:
        fml_dir.mkdir(parents=True, exist_ok=True)

    model = _load_model(model_path)
    crops = []
    detections = []

    for page_idx, img, w, h in render_pdf(pdf_path, dpi=dpi):
        for k, det in enumerate(detect(model, img, conf=conf, iou=iou)):
            x1, y1, x2, y2 = det['bbox']
            det_full = {
                'page': page_idx + 1,
                'subtype': det['subtype'],
                'conf': det['conf'],
                'bbox': det['bbox'],
            }
            detections.append(det_full)

            if save_crops:
                p = fml_dir / (
                    f'page{page_idx + 1:03d}_{k:02d}_{det["subtype"]}_'
                    f'conf{int(det["conf"] * 100)}.png'
                )
                cv2.imwrite(str(p), img[y1:y2, x1:x2])
                det_full['image'] = str(p)
                crops.append(str(p))
            else:
                det_full['image'] = None
                crops.append(None)

    return {'crops': crops, 'detections': detections}