# paper-preread CLI + skills

论文精读运行时与个人 Agent skills。通过 npm 安装论文 CLI：

只需要 Node.js 18 或更高版本，不要求用户预装 Python、pip、Conda、Homebrew 或 uv。

```bash
npm install -g paper-preread-cli
paper-preread install
paper-preread doctor
```

安装器会自行下载独立的 `uv` 和 Python 3.10，然后安装全部 Python 包及模型。运行时、
Python 依赖和模型持久化在 `~/.paper-preread/`，重复安装或升级 skill
不会重新创建环境；模型文件存在时不会重复下载。

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

### [`codex-session-migrate/`](./codex-session-migrate/) — Codex 跨机器会话迁移

迁移 Codex 会话历史、上传附件与指定工作文件，支持非 Git 工作目录的手动导入。
包含迁移流程、分页历史与 provider 差异排查、一次脱敏实测记录，以及文件打包校验和
app-server RPC 辅助脚本。此 skill 使用 Python 3 标准库，无需安装上述论文运行时。

主入口：[`codex-session-migrate/SKILL.md`](./codex-session-migrate/SKILL.md)。
调用示例：`使用 $codex-session-migrate，等源会话运行完成后，将它及生成文件迁移到目标机器。`

安装到本机 Codex 技能目录（从仓库根目录执行，目标不存在时）：

```bash
mkdir -p ~/.codex/skills
cp -R codex-session-migrate ~/.codex/skills/codex-session-migrate
```

该 skill 不随 `paper-preread-cli` 的安装器安装。辅助脚本验证：

```bash
python3 -m unittest discover -s codex-session-migrate/tests -v
```

## 安装（首次使用）

```bash
npm install -g paper-preread-cli
paper-preread install
```

开发仓库本地验证可用 `node ./bin/paper-preread.mjs doctor`。跳过首次模型下载可加
`--skip-models`；第一次抽取时仍会按需下载并缓存。

安装完成后，Phase 2 的七个确定性步骤由同一个命令完成，全部使用持久 runtime：

```bash
paper-preread prepare 2501.00001 --out ./paper-output
```

## 使用示例（精读一篇论文）

```bash
# 1. 在父 wiki 节点准备好
PARENT_TOKEN=<你的飞书 wiki 父节点 token>

# 2. 调用 paper-preread skill（v2）
# 用户输入：飞书 wiki 父节点 URL + 论文 arxiv 号清单
# 产出：每个论文一个飞书子文档，含 6 模块精读 + 与用户 5 agent 设计的映射
```

Phase 6 默认只生成 `phase6_export.json`，不会写远端：

```bash
paper-preread phase6 --out-dir ./paper-output --parent "$PARENT_TOKEN" --profile auto
paper-preread phase6 --out-dir ./paper-output --parent "$PARENT_TOKEN" --profile auto --commit
```

未安装 `lark-cli` 时计划仍会保留并标记 `needs_lark_cli`。之后安装并完成授权，
重复同一条 `--commit` 命令即可继续。

实测性能（v2）：单篇论文 ~30 min 端到端（vs v1 ~85 min）。

## 版本

| Skill | 版本 | 最近更新 |
|---|---|---|
| paper-preread | v2 (2026-08) | 7 步 Phase 2 + paper_sections.json 主输入 + safe_io 原子写 + panel-of-4 review |
| pdf-extract | v1 | doclayout-yolo + ultralytics + paddleocr + unimernet 流水线 |
| codex-session-migrate | 2026-11-19 | 跨主机会话历史与文件迁移、完整性校验及实测记录 |

## 配套工具（非本仓库但常组合用）

- `lark-cli` — 可选；用于 Phase 6 直接写飞书。未安装时先生成可续跑导出计划。

## License

Private repo.
