"""paper-extract: 文献 PDF 结构化元素抽取。

模块化 API:
    from paper_extract import extract_layout, extract_formula_det
    from paper_extract import recognize_formulas, extract_all

CLI:
    paper-extract <pdf> --out <dir> [--no-formulas] [--no-ocr] [--layout-only]

零外部仓库依赖：
- PyPI: doclayout-yolo / ultralytics / paddleocr / paddlepaddle / unimernet / PyMuPDF
- HuggingFace: opendatalab/PDF-Extract-Kit-1.0 (模型权重)
"""

from .layout import extract as extract_layout
from .formula_det import extract as extract_formula_det
from .formula_rec import recognize as recognize_formulas
from .pipeline import extract as extract_all

__version__ = '0.1.0'
__all__ = [
    'extract_layout',
    'extract_formula_det',
    'recognize_formulas',
    'extract_all',
]