---
name: paper-preread
description: 论文精读 + 飞书 wiki 子文档生成 skill（v2）— 从 arxiv 论文到飞书精读文档端到端。v2 重构后流程：(1) 三向验证 arxiv_id → (2) PDF 抓 + 7 步结构化抽取（输出 paper_sections.json 结构化正文 + paper_context.json 共享摘要 + figures_alias.json 短名映射）→ (3) 1 个路由 agent 基于 paper_sections.json 写 _plan.json → (4) 6 个写作 agent 并行基于 paper_context.json 写六个模块 JSON → (5) 1 个 panel-of-4 agent 基于 paper_context.json 评分 + 触发项覆盖重写 → (6) Phase 6 用 figures_alias.json 短名写飞书子文档。pymupdf4llm 的 paper.md 在 v2 中角色降级为 fallback。强调"贴原图不写 native table"。适用场景：用户提供飞书 wiki 父节点 URL + 论文清单（带 arxiv 号），逐篇生成 VLM 视角白话精读文档并自评优化，目标 20-30 min 跑完一篇。
---

# 论文精读 + 飞书文档生成 Skill（v2）

## v2 总览（7 阶段）

| # | Phase | 步骤 | 主输入 | 输出 |
|---|---|---|---|---|
| 1 | 论文身份验证 | (3 个 curl) | arxiv_id | 验证过的 arxiv_id |
| 2 | 论文内容抓取 | 2.1 download_pdf | arxiv_id | paper.pdf |
| | | 2.2 paper-extract --no-formulas | paper.pdf | figures/ tables/ summary.json |
| | | 2.3 extract_pdf_text | paper.pdf | paper.md paper_meta.json |
| | | 2.4 parse_ar5iv | arxiv_id | meta.json figs.json imgs/ |
| | | **2.5 parse_ar5iv_extended** | arxiv_id | **paper_sections.json** |
| | | **2.6 build_figure_alias** | figures/ tables/ | **figures_alias.json** |
| | | **2.7 build_paper_context** | paper_sections.json | **paper_context.json** |
| 3 | 内容路由 | 1 agent | paper_sections.json + paper_context.json + paper_meta.json + summary.json + figures_alias.json | `_plan.json` |
| 4 | 精读撰写 | 6 agent 并行 | `_plan.json` + **paper_context.json (主)** + paper_sections.json (deep dive) + paper.md (fallback) + figures/tables/ | 6 个 `_modules/<模块>.json` |
| 5 | 本地 review | 1 panel-of-4 agent | **paper_context.json (事实核对)** + 6 个 _modules/*.json + figures_alias.json | 6 个 _modules/*.json |
| 6 | 一次性写飞书 | Phase 6 orchestrator | 6 个 _modules/*.json + **figures_alias.json (短名解析)** + figures/tables/ | 飞书 wiki 子文档 |

⭐ Phase 2 的 2.5 / 2.6 / 2.7 是 v2 引入的必跑步骤（不是可选），不是 v1 的 fallback。

## 数据契约（v2 ⭐）

每个数据文件的唯一真源 + 谁是它的读者：

| 数据文件 / 目录 | 谁生产 | 谁读 | 角色 |
|---|---|---|---|
| **paper_sections.json** | parse_ar5iv_extended.py | Phase 3 + 4 agents | **正文结构化主输入**（sections + paragraphs + inline_equations + tables with cells） |
| **paper_context.json** | build_paper_context.py | Phase 4 + 5 agents | **共享摘要**（每 section 500 字 gist + key numbers + figure caption table） |
| **figures_alias.json** | build_figure_alias.py | Phase 4 + 5 + 6 agents | **短名映射**（page007_figure_02.png → fig-03.png） |
| paper.pdf | download_arxiv_pdf.py | pdf-extract + (rarely) agents | PDF 源文件 |
| paper.md | extract_pdf_text.py | (fallback only) | pymupdf4llm 抽取，**v2 角色降级为 fallback** |
| paper_meta.json | extract_pdf_text.py | Phase 3 routing | section 标题树 + PDF 页码 |
| summary.json | paper-extract | Phase 3 routing | figure/table/formula caption 简表 |
| meta.json / figs.json | parse_ar5iv.py | (legacy, 兼容性保留) | figure caption + fig_id + spacer |
| figures/ tables/ | paper-extract | Phase 4 (Read 看图) + Phase 6 (media-insert) | PDF 高清原图 PNG |
| formulas/ | paper-extract | (可选) | 公式 crop（v2 中以 paper_sections.json 的 `<math alttext>` 为主） |
| manifest.json | build_manifest.py | collect_modules.py / review_loop.py | 6 模块清单 + 触发规则 + phase_contracts |
| `_plan.json` | Phase 3 agent | Phase 4 agents | section → module 路由 |
| `_modules/<模块>.json` | Phase 4 agents | Phase 5 + 6 | 6 块模块 JSON |

**paper.md 降级说明**：v1 时 paper.md 是 Phase 3/4 的主输入；v2 后 agent 主读 paper_sections.json + paper_context.json（结构化 + 摘要），仅当 ar5iv 渲染失败时回退到 paper.md。**所有 SKILL.md 文档里 `paper.md` 出现时都带 `(fallback)` 标注**。

## 触发条件

用户提供：飞书 wiki 父节点 URL/node_token + 论文清单（带 arxiv 号）；或单篇 arxiv_id + 飞书父节点。

## 环境依赖

- **paper-preread CLI runtime**：首次运行 `npx github:asdasas1212/skill install`；发布 npm 后可改用 `npx paper-preread-cli install`。安装器自动准备独立的 uv、Python 3.10、Python 包和模型，用户不需要手工配置 Python。运行时与模型持久化在 `~/.paper-preread/`，skill 更新不会重复安装
- **Python runtime**：由安装器统一管理 PyMuPDF、pymupdf4llm 与 PDF 抽取依赖；不要要求用户安装 Conda、虚拟环境或混用系统 Python
- **lark-cli（可选）**：Phase 6 直接写飞书时使用；缺失时生成 `phase6_export.json`，后续安装后续跑

## 工作流程（6 阶段具体步骤）

### 1. 论文身份验证

文档给的 arxiv 号经常错（30-50%），必须三向验证：

```bash
curl -s "https://api.openalex.org/works?filter=default.search:<unique_short_phrase>&sort=cited_by_count:desc&per_page=1" | python3 -c "import sys,json; print(json.load(sys.stdin))"
curl -sL https://ar5iv.labs.arxiv.org/html/<arxiv_id> | grep -oE '<title>[^<]*</title>'
curl -sL https://arxiv.org/abs/<arxiv_id> | grep -oE 'citation_title" content="[^"]*"'
```

### 2. 论文内容抓取（7 步）

```bash
# 七步都使用 ~/.paper-preread/venv，默认跳过公式识别以节省时间
paper-preread prepare <arxiv_id> --out <out_dir>

# 确实需要 UniMERNet 公式识别时：
paper-preread prepare <arxiv_id> --out <out_dir> --with-formulas
```

命令依次生成 paper.pdf、figures/tables/summary.json、paper.md、paper_meta.json、
meta.json、figs.json、paper_sections.json、figures_alias.json 和 paper_context.json。

**Phase 2 结束检查清单**：

```bash
ls {paper.pdf, paper_sections.json, paper_context.json, figures_alias.json, summary.json, paper_meta.json, figures/ tables/} | grep -v ^$ && echo "✓ Phase 2 全部产物就绪"
```

**已知边界**：
- `parse_ar5iv_extended.py`：HTML 渲染版，**结构化提取**（继承自 parse_ar5iv.py + 加表格 cells / sections 段落 / inline equations）；ar5iv v2 未渲染时输出残缺 → fallback 到 paper.md
- `extract_pdf_text.py`：~95% 正文文字准确；公式（PDF 里是图片）拿不到——已被 paper_sections.json 取代；自动清 4 类 noise；清不掉的自定义 watermark 需手工加 regex 到 `is_noise()`
- `paper-extract`：borderless 表格（CVPR/学术论文）100% 检出；caption OCR 偶有错（用 figs.json 交叉验证）；**默认 `--no-formulas`**（公式从 ar5iv 取，更快更准）；有 GPU 时检测到 CUDA 自动恢复公式识别 stage（v2 保持 optional 能力，不强制 GPU）

### 3. 内容路由（1 agent）

**输入**：**paper_sections.json (主)** + paper_context.json + paper_meta.json + summary.json + figures_alias.json + (paper.md fallback)
**输出**：`<out_dir>/_plan.json`

```json
{
  "paper_id": "<arxiv_id>",
  "modules": {
    "背景": {
      "sections": [{"title": "...", "page": N, "reason": "..."}],
      "elements": [{"type": "figure|table|formula", "id": "...", "reason": "..."}]
    },
    "问题": { "sections": [...], "elements": [...] },
    "结论": { "sections": [...], "elements": [...] },
    "技术": { "sections": [...], "elements": [...] },
    "实验": { "sections": [...], "elements": [...] },
    "讨论": { "sections": [...], "elements": [...] }
  }
}
```

**关键规则**：同一 element 可进多模块；每个模块至少 1 项；`reason` 必填。

**Agent prompt 模板**：
```
你是论文精读编辑，专做**内容路由**。
最终产物是一篇 VLM 视角白话精读文，6 个模块：背景 / 问题 / 结论 / 技术 / 实验 / 讨论。
你的任务：决定每个 sections/elements 进哪个模块，让下游写模块的 agent 拿到对的料。

# 先理解再路由
1. **主读** `<out_dir>/paper_context.json`（每 section 500 字 gist + key numbers + figure caption table）
2. **deep dive** 用 paper_context.json.sections[].id 在 `<out_dir>/paper_sections.json` 里翻全段落 / 公式 / 表格 cells
3. **fallback** 仅当 paper_sections.json 不可用（ar5iv 渲染失败）时读 `<out_dir>/paper.md`
4. 读 `<out_dir>/paper_meta.json` 看 PDF 页码定位
5. 读 `<out_dir>/summary.json` 看所有 figure/table/formula 的 caption
6. 用 Read 看 `figures/` `tables/` 里 PNG 实际内容（caption 可能 OCR 错）

# 6 个模块的定位（**不要给空模块**）
- **背景**：研究领域 + 大问题 + 这篇 paper 想做什么 —— 给"VLM 读者进入状态"用的 context
- **问题**：现有方法的关键缺陷 + 这篇 paper 想填的具体 gap —— Figure 1（对比图）通常在这里
- **结论**：一句话总结 + 关键数字 + 性能提升 —— result 曲线可贴这里
- **技术**：整体架构 + 核心创新 + 关键技术细节 —— **架构图 + 公式 LaTeX 都进这里**
- **实验**：数据集 + 评测 + 主结果 + ablation —— **table 原图都进这里**（不写 native table）
- **讨论**：局限性 + 失败案例 + 未来工作 —— qualitative 例子图可贴这里

# 路由原则
1. **同一 element 可进多模块**：架构图同时进"技术"+"问题"（如果它展示痛点），
   BLEU 对比图同时进"背景"+"结论"（如果它展示 baseline 弱）
2. **每个模块至少 1 个 section 或 element**（不能空）
3. **每个 assignment 写 1 句 reason**：说明为什么这个 section/element 属于这个模块
4. **section 路由**：
   - "Introduction" 通常给"背景"+"问题"
   - "Method / Model / Architecture / Approach" 给"技术"
   - "Experiments / Results / Ablation" 给"实验"
   - "Conclusion" 同时给"结论"+"讨论"
5. **element 路由**（根据 caption + 实际内容判断）：
   - caption 含 "framework / architecture / model / overview" → 技术
   - caption 含 "ablation / comparison / benchmark" → 实验
   - caption 含 "example / qualitative / case study" → 讨论

# 输出
写 `<out_dir>/_plan.json`：...
```

**校验**：写完 _plan.json 后 agent 自查（每个 module 有 reason、无空模块、每张图/table 至少分配一次）。

### 4. 精读撰写（6 agent 并行）

**输入**：`_plan.json` + **paper_context.json (主)** + paper_sections.json (deep dive) + paper.md (fallback) + figures/tables/
**输出**：
```
<out_dir>/_modules/
├── 背景.json
├── 问题.json
├── 结论.json
├── 技术.json
├── 实验.json
└── 讨论.json
```

**做法**：用 Agent 工具并行 spawn 6 个 agent，每个写一个文件（无冲突、无合并）。

**每个文件 schema**：
```json
{
  "module_id": "<模块名>",
  "content_md": "## ...\n\n![Figure N](figures/...)\n\n$$...$$",
  "figure_refs": [{"id", "path", "caption"}],
  "table_refs": [{"id", "path", "caption"}],
  "formula_refs": [{"id", "latex"}],
  "source_sections": ["Introduction"]
}
```

**Agent prompt 模板**：
```
你是论文写作专家，专写【<模块>】。读者是 VLM 背景的研究生/工程师——
他们懂 encoder-decoder、attention、VQA、captioning，但**不熟悉**这篇 paper 的子领域。

# 任务
不是把材料凑起来，而是先**理解**这篇 paper 在做什么、为什么这样做、解决了什么问题，
再用读者熟悉的概念**重新写作**。输出是一段让 VLM 背景读者读完能 grasp 这篇 paper 的文字。

# 喂料（v2 顺序 —— 先摘要、再详情、再 fallback）
1. **主读** `<out_dir>/paper_context.json` —— 从 sections 数组里挑出与本模块相关的 chapter/段落 gist（≤ 500 char 每 section），key_numbers 字段提供核对数字
2. **deep dive** 按 section ID 在 `<out_dir>/paper_sections.json` 里查全段落（paragraphs 数组）、公式（inline_equations）、表格 cells —— 写模型细节时必用
3. **fallback** 仅当 paper_sections.json 不可用时读 `<out_dir>/paper.md`
4. 读 `<out_dir>/_plan.json` 里 <模块> 的：
   - sections: 你负责的章节（粗略指引范围）
   - elements: 你要引用的图/表/公式（caption/latex/path，用 **fig-NN.png 短名** 而不是 page007_figure_02.png 长名）
5. 用 Read 工具看 `figures/` `tables/` 里 PNG 的**实际内容**
   （caption 可能 OCR 错，必须亲眼看）

# 写作要求
1. **先理解后写**：动笔前先在脑里跑一遍"这篇 paper 想说什么"
2. **类比优先**：用 VLM 熟悉概念解释新概念
   （例：把 DETR 类比成 "anchor-free 的 set prediction"；把 LoRA 类比成 "在原权重上训一个低秩残差"）
3. **解释"为什么"**：每个方法选择都要说 motivation，不要只描述做了什么
4. **不堆术语**：术语第一次出现时一句话解释，之后直接用
5. **结构**：
   - 引用块 `> ...` 解释图的核心思想
   - callout 标核心痛点 / 反直觉发现
   - 公式用 `$$...$$`（从 paper_sections.json 的 inline_equations.latex 取，不贴公式图）
   - 表贴原图 `![...](figures/tbl-01.png)` (短名) + caption_text，**绝不写 native table**

# 🔒 写 JSON 走 safe_io.py write CLI（v2 强制：禁止 Write 工具写 _modules/*.json）

**绝不**用 Write 工具写 `<out_dir>/_modules/<模块>.json`。原因：Write 不做 JSON 转义，agent 半手写 JSON 时漏 escape `"` → 文件半坏 → Phase 5/6 反复 patch（**历史已验证**：讨论 agent 37 min 卡住就是这原因）。

**写路径（强制）**：
1. 用 Write 工具把待序列化的 dict 写到临时文件 `/tmp/<模块>.dict.json`（这只是个 string 容器，不需要合法 JSON 格式）
2. 用 Bash 调 safe_io write CLI 完成原子写 + 校验：
   ```bash
   python3 scripts/safe_io.py write <out_dir>/_modules/<模块>.json \
       --from /tmp/<模块>.dict.json
   ```
3. safe_io 内部用 `json.loads`（拒绝格式错的）→ `json.dumps`（自动正确 escape `"` `\` 等）→ 写到 `.tmp` → atomic rename → post-write `json.load` 校验
4. 返回 `✓ wrote <path>` 才算完成

**为什么这样设计**：
- json.loads + json.dumps 这条 chain 已经把所有 ASCII 引号 / 控制字符 / 斜杠问题接住了 —— 这是 JSON 规范的 v2 hard guarantee
- agent 不需要"记得"任何引号规则；它可以写任意奇怪的 content_md（包含 `"` `\` 换行），safe_io 会自动正确 escape
- 文件不是合法 JSON 的唯一失败模式是 agent 用 Write + 半手写 JSON 字符串 —— 直接禁用 Write 工具消除这个路径

# 输出
写到 `<out_dir>/_modules/<模块>.json`：
{
  "module_id": "<模块>",
  "content_md": "<你写的 markdown>",
  "figure_refs": [{"id", "path", "caption"}],
  "table_refs":  [{"id", "path", "caption"}],
  "formula_refs": [{"id", "latex"}],
  "source_sections": ["<你实际参考的 sections>"]
}
figure_refs / table_refs / formula_refs 只列你**实际在 content_md 里用了**的。
```

**校验**：
```bash
python3 scripts/collect_modules.py <out_dir>    # exit 0 全齐 / exit 1 有缺
```

### 5. 本地 review loop（panel-of-4 单 agent）

**输入 / 修改数据**：**paper_context.json (key_numbers / figure caption table 用来事实核对)** + 6 个 `_modules/<模块>.json`
**输出**：6 个全 pass 的 _modules/*.json

**判断 pass / 不合格**：
- **pass** = panel 评分后无触发项（balanced：≥2 medium_or_low 才触发；0 触发即 pass）
- **不合格** = 有触发项

**迭代次数**（`max_iter=2` 默认）：
- Round 0：初次评分。**pass 则不迭代，直接进 Phase 6**
- Round 1：不合格时，重写触发项 → 重评分。pass 则停
- Round 2：仍不合格时，再重写 → 重评分。**无论结果都停**

**做法**（使用本 skill 的 agent 跑）：
1. Round 0：spawn **1 个 panel-of-4 agent**（同时输出 4 视角评分，避免 4 个独立 agent 各自的 wall clock）→ `python3 scripts/review_loop.py <scores.json> --rule balanced` 聚合
2. 无触发 → pass，直接进 Phase 6
3. 有触发 → `format_optimization_prompt()` 生成 prompt → spawn agent **覆盖整个** `_modules/<触发模块>.json`（不是只覆盖 content_md，要保住 figure_refs / table_refs / formula_refs 与 content_md 中 `![]()` 实际引用一致）
4. 终止：pass / `max_iter=2` / 人工叫停

**4 视角 panel-of-4**（同一个 agent 内部并行思考 4 视角）：

| # | 视角 | 关注 |
|---|---|---|
| A | VLM 方向新手 | clarity（白话是否够易懂） |
| B | CVPR/NeurIPS 审稿人 | correctness（核对 paper_context.json 的 key_numbers） |
| C | VLN 领域学生 | completeness + depth |
| D | figure-auditor | 视觉错配（每个 PNG 是否真对应 caption） |

**为什么 panel-of-4 比 4 个独立 agent 好**：
- 4 个独立 agent 各自 5-10 min → wall clock = max，最长一个拖到 10 min
- 1 个 panel 内并行思考 4 视角 → ~5 min wall clock（5-10× 提速）

**panel agent 输出 schema**：

```json
{
  "perspective": "panel",
  "module_scores": {
    "<模块>": {
      "correctness": "high" | "medium" | "low",
      "clarity": "high" | "medium" | "low",
      "completeness": "high" | "medium" | "low",
      "comments": {
        "correctness": "（视角 B + D 综合）",
        "clarity": "（视角 A 主评）",
        "completeness": "（视角 C 主评）"
      }
    },
    ...
  }
}
```

如果未来要回退到 4 个独立 agent，spawn 4 个分别填 `perspective="vlm_novice"/"cvpr_reviewer"/...`，output 一起传给 `review_loop.py`。

### 6. 一次性写飞书

**输入**：6 个全 pass 的 `_modules/<模块>.json` + **figures_alias.json (短名解析 → media-insert)** + figures/tables/
**输出**：飞书 wiki 子文档 + doc_id

**做法**：默认先生成计划，不做远端写入；确认后显式加 `--commit`。
```bash
cd <out_dir>    # cwd 必须是这里
paper-preread phase6 --out-dir . --parent <wiki-url> --profile auto
# 检查 phase6_export.json 后执行：
paper-preread phase6 --out-dir . --parent <wiki-url> --profile auto --commit
```

`lark-cli` 缺失时，第一条命令仍会产出完整文字/图片操作清单并标记
`needs_lark_cli`，不丢失 Phase 3–5 产物。安装飞书 CLI 并授权后，用同一命令续跑。
`--profile auto` 会对所有 profile 做只读父节点探测；只有一个账户可访问时自动选择，
多个账户都可访问且无法判定时要求显式传 profile，避免写错账户。

**输出数据**：飞书 doc_id，可去 `lark-cli docs +fetch --doc <doc_id>` 校验。

## 关键命令速查

```bash
# === Phase 1 验证 ===
curl -s "https://api.openalex.org/works?filter=default.search:<phrase>&per_page=1"
curl -sL https://ar5iv.labs.arxiv.org/html/<id> | grep -oE '<title>[^<]*</title>'
curl -sL https://arxiv.org/abs/<id> | grep -oE 'citation_title" content="[^"]*"'

# === Phase 2 内容抓取（v2 7 步，同一持久 runtime） ===
paper-preread prepare <arxiv_id> --out <out_dir>

# === Phase 3-5 校验 ===
python3 scripts/build_manifest.py --verify
python3 scripts/collect_modules.py <out_dir>                           # Phase 4 后
python3 scripts/review_loop.py _review_panel.json                      # Phase 5 评分聚合

# === Phase 4 / 5 写 _modules/*.json 的唯一安全路径（v2 强制） ===
# 用 Write 把 dict 写到临时文件，再用 safe_io.write CLI 原子写
python3 scripts/safe_io.py write <out_dir>/_modules/<模块>.json --from /tmp/<模块>.dict.json

# === Phase 6 飞书（先计划，后提交） ===
paper-preread phase6 --out-dir . --parent <wiki-url> --profile auto
paper-preread phase6 --out-dir . --parent <wiki-url> --profile auto --commit
```

## 脚本清单（11 个 + 1 个外置）

| 脚本 | 用途 | 阶段 |
|---|---|---|
| `scripts/download_arxiv_pdf.py` | arxiv_id → paper.pdf | Phase 2.1 |
| `scripts/extract_pdf_text.py` | paper.pdf → paper.md (fallback) + paper_meta.json | Phase 2.3 |
| `scripts/parse_ar5iv.py` | arxiv_id → meta.json + figs.json + imgs/ | Phase 2.4 |
| **`scripts/parse_ar5iv_extended.py`** ⭐ | arxiv_id → paper_sections.json (sections + paragraphs + equations + tables) | **Phase 2.5** |
| **`scripts/build_figure_alias.py`** ⭐ | figures/ tables/ → figures_alias.json (短名映射) | **Phase 2.6** |
| **`scripts/build_paper_context.py`** ⭐ | paper_sections.json → paper_context.json (共享 gist + key numbers + fig captions) | **Phase 2.7** |
| `scripts/collect_modules.py` | 校验 6 个 _modules/*.json（含 PNG 路径 + JSON 引号 warn + 模块清单来自 manifest.json） | Phase 4 后置 |
| `scripts/review_loop.py` | 4-agent / panel-of-4 评分聚合（balanced 触发）+ 触发项重写 prompt 生成 | Phase 5 |
| **`scripts/safe_io.py`** ⭐ | 原子写 JSON + JSON 合法性 + ASCII 双引号警告 | 任意阶段 |
| **`scripts/build_manifest.py`** ⭐ | 验证 manifest.json 一致性 | 任意阶段 |
| `manifest.json` | 模块清单 + 触发规则 + phase_contracts（**单一事实源**，collect/review 自动读） | 任意阶段 |
| `scripts/extract_pdf_figures.py` | (fallback) | 仅 pdf-extract 不可用时 |
| `scripts/extract_table_orig.py` | (fallback) | 仅 pdf-extract 不可用时 |
| `外置: pdf-extract skill` | paper-extract CLI (figures/ tables/ + progress + GPU optional) | Phase 2.2 |
| `scripts/phase6_write.py` | 生成/执行可续跑的飞书图文写入计划 | Phase 6 |

## 踩过的坑

### 1. **表格：贴原图不写 native table**
凭记忆凑数据：列名错（加了原表没有的列如 SPL）、数字小数 vs 百分数（OSR=0.21 应是 21.4）。
**必须用 paper-extract 拿 table 原图（borderless 也能 100% 检出），或直接贴原图。**
PyMuPDF `find_tables()` 不适用——只识别有边框表格；LaTeX 渲染的 PDF（CVPR/IEEE）无边框。

### 2. **arxiv.org 外网图片抓取超时**
`media-insert --file` 飞书服务器抓 2MB 图超时。必须用 figures_alias.json 短名 + 本地 path 走 `media-insert --file ./figures/fig-03.png`。

### 3. **media-insert 只能插末尾**
图文混排只能：append 文字 → media-insert 图 → append 文字 → media-insert 图... 交替。

### 4. **--file 路径只接受 cwd 相对路径**
绝对路径 `/tmp/...` 报 `unsafe file path`。subprocess.run 必须传 `cwd=<out_dir>`。

### 5. **page 索引 0 vs 1**
- `fitz` 0-indexed（`doc[6]` = PDF 第 7 页）
- `pymupdf4llm` 1-indexed

### 6. ⭐ **paper_sections.json 是 v2 主输入，不要回到 paper.md**
v1 时期 agent 看 paper.md，pymupdf4llm 在 layout-rich 页（abstract 图 / 表格密集页）会把单元格切成碎行（OpenVLA paper.md 第 33-40 行就是例子）。
v2 用 parse_ar5iv_extended.py 从 ar5iv LaTeX→HTML 提取 sections + paragraphs，结构干净。
**Phase 2 跑完立即看 `ls paper_sections.json` 确认生成；没生成就 fallback 走 paper.md（也接受降级方案）。**

### 7. ⭐ **_modules/*.json 写入必须走 safe_io.write CLI（v2 系统级强制）**
v1 用"不要用 ASCII 双引号"约束 agent → 不可靠（agent 忘记就破文件）。
v2 改路径：
- **禁止** Write 工具写 `_modules/*.json`（直接禁用失败模式路径）
- **强制** 走 `safe_io.py write <path> --from <tmp.json>`：内部用 json.loads + json.dumps 自动正确 escape，atomic .tmp replace，post-write json.load 校验
- agent 写任意 content_md（含 `"` `\` 换行）都能成功；JSON 规范 + json.dumps 已经 hard-guarantee 正确性

## 性能预期（v2）

| 阶段 | v1 实测 | v2 估算 | 提速手段 |
|---|---|---|---|
| paper-extract | 5.5 min | ~2 min | `--no-formulas` 默认 + progress log + imgsz 降（公式从 ar5iv 取） |
| Phase 3 routing | ~1 min | ~30s | agent 读 paper_context.json (5-10k chars gist) 而非 paper.md (23k chars) |
| Phase 4 writing (6 agents) | ~5 min | ~3 min | 主读 paper_context.json，deep dive 用 paper_sections.json 按 section ID 翻；不再 6 agent 各读 23k paper.md |
| Phase 5 review | ~10 min | ~5 min | panel-of-4 单 agent 替代 4 个独立 agent（wall clock = max → 1 个 agent 内并行思考） |
| Phase 5 rewrite (37 min outlier) | 37 min | 2-5 min | JSON 安全硬约束 + safe_io 原子写 + 改写整个 module JSON 不只 content_md |
| Phase 6 | ~8 min | ~5 min | figures_alias.json 短名 + phase6_write.py 已 manifest 驱动 |
| **总计** | **~85 min** | **~20-30 min** | 总体提速 3-4× |

GPU 路径保留（optional）：有 CUDA 时自动启用 paper-extract 公式 stage，进一步压 1-2 min。无 GPU 完全兼容 CPU 路径。

## 版本演进

- **v1**：6 阶段，paper.md 主输入，4 个独立 review agent，无 paper_context 共享，process 在 30+ min
- **v2**（本版）：7 阶段、7 步 Phase 2、paper_sections.json / paper_context.json / figures_alias.json 新数据契约、panel-of-4 review、目标 20-30 min
