---
name: pdf-extract
description: 从文献 PDF 抽取 figures / tables / captions / formulas + LaTeX，基于自研 paper_extract Python package（doclayout-yolo + ultralytics + paddleocr + unimernet，**零 GitHub clone 依赖**）。模块化：layout / ocr / formula_det / formula_rec 四模块可独立调用。适用场景：用户提供 PDF，需要结构化元素抽取；或被 paper-preread 等 skill 复用。
requires:
  python: "3.10"
  conda_manager: miniforge 或 miniconda
  conda_env: pdf-extract-kit-1.0
  pip_packages: [PyMuPDF, opencv-python, numpy, huggingface_hub, doclayout-yolo, ultralytics, paddleocr, paddlepaddle, unimernet, Pillow, rich]
  models_hf_repo: opendatalab/PDF-Extract-Kit-1.0
  network: huggingface.co + pypi（清华镜像可，国内推荐）
---

# pdf-extract skill

## 能力

输入 PDF 路径，输出 `{figures, tables, captions, formulas, summary.json}` 五件套。

## 安装（新机器一次性）

```bash
~/.claude/skills/pdf-extract/scripts/setup.sh
```

setup.sh 会：
1. 探测/装 miniforge（已有则跳过）
2. 创建 conda env `pdf-extract-kit-1.0`
3. `pip install -e <skill-dir>` 安装 paper_extract package（**所有依赖走 PyPI**，不 clone 任何 GitHub 仓）
4. 预下载 ~800 MB 模型到 `~/.cache/paper-extract/models/`（从 HuggingFace）
5. 写 `~/.config/pdf-extract/config.sh`

## 调用

```bash
source ~/.config/pdf-extract/config.sh
paper-extract <pdf> --out <dir>                 # 全套
paper-extract <pdf> --out <dir> --no-formulas   # 跳过公式
paper-extract <pdf> --out <dir> --no-ocr        # 跳过 OCR
paper-extract <pdf> --out <dir> --layout-only   # 只要 bbox
paper-extract <pdf> --out <dir> --no-figures    # 只要 table
```

## Python API（模块化）

```python
from paper_extract import extract_layout, extract_formula_det, recognize_formulas

# 只要 figure/table bbox + crops
extract_layout(pdf, out_dir)

# 只要公式 bbox
_, crops = extract_formula_det(pdf, out_dir)

# 只要公式 LaTeX（crops 已有）
latices = recognize_formulas(crops)

# 一键全套
from paper_extract import extract_all
extract_all(pdf, out_dir, layout=True, ocr=False, formulas=True)
```

## 自定义

```bash
export PAPER_EXTRACT_CACHE=/shared/cache   # 模型共享缓存（多机共享）
export PAPER_EXTRACT_PY=/path/to/python    # 覆盖默认 python 路径
```

## 卸载

```bash
conda env remove -n pdf-extract-kit-1.0
rm -rf ~/.cache/paper-extract ~/.config/pdf-extract
```

## 已知边界

- 公式 caption 配对是 y 距离最近匹配——同页多个 figure/table 紧邻时可能配错
- paddlepaddle 不支持 Apple Silicon MPS，OCR 始终走 CPU
- UniMERNet tiny 公式识别置信度随公式复杂度变化大；低 conf 公式以原图为准