"""模型懒加载与缓存管理。

查找顺序：
1. $PAPER_EXTRACT_REPO/models/<...>  （覆盖默认 PDF-Extract-Kit 仓路径）
2. ~/PDF-Extract-Kit/models/<...>   （历史路径，已有 800 MB 模型）
3. ~/.cache/paper-extract/models/<...>  （首次跑 lazy 从 HuggingFace 下）
"""

import os
from pathlib import Path

CACHE_ROOT = Path(
    os.environ.get('PAPER_EXTRACT_CACHE', Path.home() / '.cache' / 'paper-extract')
)
HF_REPO = 'opendatalab/PDF-Extract-Kit-1.0'

# 历史路径（兼容 PDF-Extract-Kit 时代用户已下载的模型）
LEGACY_PEK_REPO = Path.home() / 'PDF-Extract-Kit'

_PATTERNS = {
    'layout':      'Layout/YOLO/doclayout_yolo_ft.pt',
    'formula_det': 'MFD/YOLO/yolo_v8_ft.pt',
    'formula_rec': 'MFR/unimernet_tiny',
    'ocr_det':     'OCR/PaddleOCR/det/ch_PP-OCRv4_det',
    'ocr_rec':     'OCR/PaddleOCR/rec/ch_PP-OCRv4_rec',
}


def _find_local(key: str) -> Path | None:
    """检查本地已下载模型。"""
    rel_path = _PATTERNS[key]
    env_repo = os.environ.get('PAPER_EXTRACT_REPO')
    if env_repo:
        p = Path(env_repo) / 'models' / rel_path
        if p.exists():
            return p
    legacy = LEGACY_PEK_REPO / 'models' / rel_path
    if legacy.exists():
        return legacy
    cached = CACHE_ROOT / 'models' / rel_path
    if cached.exists():
        return cached
    return None


def _download(key: str) -> Path:
    """从 HuggingFace 下载缺失的模型到 ~/.cache/paper-extract/models/。"""
    from huggingface_hub import snapshot_download

    rel_path = _PATTERNS[key]
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    (CACHE_ROOT / 'models').mkdir(parents=True, exist_ok=True)
    model_path = f'models/{rel_path}'
    snapshot_download(
        repo_id=HF_REPO,
        local_dir=str(CACHE_ROOT),
        allow_patterns=[model_path, f'{model_path}/*'],
    )
    return CACHE_ROOT / 'models' / rel_path


def _ensure(key: str) -> Path:
    p = _find_local(key)
    if p is None:
        p = _download(key)
    if not p.exists():
        raise FileNotFoundError(
            f'model {key} not found at {p}. Try re-running setup.sh.'
        )
    return p


def get_layout_model_path() -> str:
    return str(_ensure('layout'))


def get_formula_det_model_path() -> str:
    return str(_ensure('formula_det'))


def get_formula_rec_model_dir() -> str:
    return str(_ensure('formula_rec'))


def get_ocr_det_model_dir() -> str:
    return str(_ensure('ocr_det'))


def get_ocr_rec_model_dir() -> str:
    return str(_ensure('ocr_rec'))


def cache_root() -> Path:
    return CACHE_ROOT
