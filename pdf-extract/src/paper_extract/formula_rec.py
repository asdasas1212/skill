"""公式识别：UniMERNet 把公式图 → LaTeX 源码。

UniMERNet 是 Donut 风格的 encoder-decoder，直接调 unimernet PyPI 包。
不依赖 pdf_extract_kit 仓。
"""

import argparse
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
from PIL import Image

_MODEL = None
_PROCESSOR = None
_DEVICE = None
_CFG = None


def _load(model_dir: str):
    global _MODEL, _PROCESSOR, _DEVICE, _CFG
    if _MODEL is not None:
        return

    import unimernet.tasks as tasks
    from unimernet.common.config import Config
    from unimernet.processors import load_processor

    args = argparse.Namespace(
        cfg_path=str(Path(model_dir) / 'unimernet_tiny.yaml'),
        options=None,
    )
    cfg = Config(args)
    cfg.config.model.pretrained = str(Path(model_dir) / 'pytorch_model.pth')
    cfg.config.model.model_config.model_name = model_dir
    cfg.config.model.tokenizer_config.path = model_dir
    _CFG = cfg

    task = tasks.setup_task(cfg)
    _DEVICE = torch.device('cpu')
    _MODEL = task.build_model(cfg).to(_DEVICE)
    _MODEL.eval()
    _PROCESSOR = load_processor(
        'formula_image_eval',
        cfg.config.datasets.formula_rec_eval.vis_processor.eval,
    )


def _load_image(path: str) -> Optional[Image.Image]:
    img = cv2.imread(path)
    if img is None:
        return None
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def recognize(
    image_paths: list[str],
    model_dir: Optional[str] = None,
    *,
    batch_size: int = 1,
) -> list[str]:
    """输入公式图路径列表，返回 LaTeX 字符串列表（按顺序对齐）。"""
    if model_dir is None:
        from .models import get_formula_rec_model_dir
        model_dir = get_formula_rec_model_dir()
    _load(model_dir)

    results = []
    for path in image_paths:
        if path is None:
            results.append('')
            continue
        pil = _load_image(path)
        if pil is None:
            results.append('')
            continue
        tensor = _PROCESSOR(pil).unsqueeze(0).to(_DEVICE)
        with torch.no_grad():
            out = _MODEL.generate({'image': tensor})
        results.append(out['pred_str'][0])
    return results


def extract_with_latex(
    image_paths: list[str],
    out_json: str,
    model_dir: Optional[str] = None,
) -> list[dict]:
    """批量识别并写 JSON 到 out_json（[{image, latex}, ...]）。"""
    latices = recognize(image_paths, model_dir=model_dir)
    records = [
        {'image': p, 'latex': l}
        for p, l in zip(image_paths, latices)
        if p is not None
    ]
    Path(out_json).write_text(
        __import__('json').dumps(records, indent=2, ensure_ascii=False)
    )
    return records