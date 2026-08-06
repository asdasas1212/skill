---
name: pdf-extract
description: 从文献 PDF 抽取 figures / tables / captions / formulas + LaTeX，基于自研 paper_extract Python package（doclayout-yolo + ultralytics + paddleocr + unimernet，**零 GitHub clone 依赖**）。模块化：layout / ocr / formula_det / formula_rec 四模块可独立调用。适用场景：用户提供 PDF，需要结构化元素抽取；或被 paper-preread 等 skill 复用。
---

# pdf-extract skill

## 能力

输入 PDF 路径，输出 `{figures, tables, captions, formulas, summary.json}` 五件套。

## 安装（新机器一次性，后续复用）

```bash
npx github:asdasas1212/skill install
```

安装器把可复用运行时放在 `~/.paper-preread/`，把模型放在
`~/.paper-preread/models/`。重复安装 skill 只同步变化，不重建环境或重复下载模型。
独立的 uv、Python 3.10、Python 包和模型均由这条命令自动准备，不要求用户预装或理解 Python 环境。
未发布 npm 包或从源码运行时，执行本 skill 的 `scripts/setup.sh`，效果相同。

## 调用

```bash
~/.local/bin/paper-preread extract <pdf> --out <dir>                 # 全套
~/.local/bin/paper-preread extract <pdf> --out <dir> --no-formulas   # 跳过公式
~/.local/bin/paper-preread extract <pdf> --out <dir> --no-ocr        # 跳过 OCR
~/.local/bin/paper-preread extract <pdf> --out <dir> --layout-only   # 只要 bbox
~/.local/bin/paper-preread extract <pdf> --out <dir> --no-figures    # 只要 table
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

删除 `~/.paper-preread/` 可移除独立运行时与模型；删除前先确认该目录没有用户产物。

## 已知边界

- 公式 caption 配对是 y 距离最近匹配——同页多个 figure/table 紧邻时可能配错
- paddlepaddle 不支持 Apple Silicon MPS，OCR 始终走 CPU
- UniMERNet tiny 公式识别置信度随公式复杂度变化大；低 conf 公式以原图为准
