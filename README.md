# skill

个人 Claude Agent skills 仓库。包含两个互相配套的 paper 精读工作流 skill：

## 目录

### [`paper-preread/`](./paper-preread/) — 论文精读端到端（v2）

把 arxiv 论文自动产出飞书精读文档的 6 阶段 skill：

1. **Phase 1** — arxiv 身份三向验证（OpenAlex + ar5iv + abs）
2. **Phase 2** — 7 步内容抓取（PDF + paper-extract + ar5iv_extended + figure_alias + paper_context）
3. **Phase 3** — 内容路由（1 agent 写 `_plan.json`）
4. **Phase 4** — 6 模块并行写作（背景 / 问题 / 结论 / 技术 / 实验 / 讨论）
5. **Phase 5** — panel-of-4 本地 review + 触发重写
6. **Phase 6** — 一次性写飞书 wiki 子文档

主入口：[`paper-preread/SKILL.md`](./paper-preread/SKILL.md)
关键脚本：`paper-preread/scripts/`（11 个：`download_arxiv_pdf.py` / `parse_ar5iv.py` / `parse_ar5iv_extended.py` / `build_figure_alias.py` / `build_paper_context.py` / `safe_io.py` / `review_loop.py` / `collect_modules.py` / `build_manifest.py` / `extract_pdf_text.py` / `extract_pdf_figures.py` / `extract_table_orig.py`）

### [`pdf-extract/`](./pdf-extract/) — PDF figure/table 抽取（v1）

论文 PDF → 高清 figure / table PNG + LaTeX 公式抽取。paper-preread 依赖此 skill。

主入口：[`pdf-extract/SKILL.md`](./pdf-extract/SKILL.md)
关键脚本：`pdf-extract/scripts/run.sh`（调用入口）、`pdf-extract/scripts/setup.sh`（首次安装 + 模型下载）
底层包：`pdf-extract/src/paper_extract/`（doclayout-yolo + ultralytics + paddleocr + unimernet）

## 安装（首次使用）

```bash
# pdf-extract 需要首次 setup 下载模型（5-10 min）
bash pdf-extract/scripts/setup.sh
source ~/.config/pdf-extract/config.sh

# paper-preread 无额外安装（依赖系统 python3 + pymupdf + lark-cli）
```

## 使用示例（精读一篇论文）

```bash
# 1. 在父 wiki 节点准备好
PARENT_TOKEN=<你的飞书 wiki 父节点 token>

# 2. 调用 paper-preread skill（v2）
# 用户输入：飞书 wiki 父节点 URL + 论文 arxiv 号清单
# 产出：每个论文一个飞书子文档，含 6 模块精读 + 与用户 5 agent 设计的映射
```

实测性能（v2）：单篇论文 ~30 min 端到端（vs v1 ~85 min）。

## 版本

| Skill | 版本 | 最近更新 |
|---|---|---|
| paper-preread | v2 (2026-08) | 7 步 Phase 2 + paper_sections.json 主输入 + safe_io 原子写 + panel-of-4 review |
| pdf-extract | v1 | doclayout-yolo + ultralytics + paddleocr + unimernet 流水线 |

## 配套工具（非本仓库但常组合用）

- `md2feishu.py` — markdown → 飞书 XML 转换器（位于 `~/.claude/work/<project>/`）
- `phase6_write_v2.py` — paper-preread Phase 6 的 markdown→XML+图文混排 orchestrator

## License

Private repo.
