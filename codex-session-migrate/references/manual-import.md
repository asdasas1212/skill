# 非 Git 或不适用内置移交时的迁移

此流程基于 2026-11-19 实际使用的 Codex app-server 接口。`thread/fork`、`thread/resume` 的 path 行为和历史分页随版本变化；执行前用目标二进制生成 schema，不把本文当永久协议。

## 1. 冻结范围与只读定位

记录源主机、源 ID、标题、最新完成轮 ID、cwd、runtime workspace roots、源与目标 Codex home。源会话还在工作且用户要求等待时，只做只读盘点，并在当前任务用 `wait_threads` 等到完成；不要用定时自动化跟踪一次运行。

用 `read_thread`/`thread/read` 获取实际 rollout 路径，必要时只按该 ID 搜索 `sessions` 与 `archived_sessions`，不要遍历输出整个用户的历史。定位附件和可视化路径；只加入当前会话引用的内容。根据 fileChange 和实际写文件命令找产物，最终仍需检查磁盘文件。终端搜索读过的源码也可能是继续工作所需的上下文。

选择目标新目录，检查 `os.statvfs(path).f_flag & os.ST_RDONLY`、`os.access(path, os.W_OK)` 和 free bytes。已有项目目录可能是只读挂载或旧路径别名。记录 `realpath`；同一目录的别名不能被误判为 cwd 不一致。

## 2. 构建可校验快照

文件操作与会话历史操作分开。输入明确的 `items.json`：

```json
{
  "items": [
    {"source": "/source/project/designs", "target": "workspace/designs"},
    {"source": "/source/.codex/sessions/date/rollout.jsonl", "target": "session/source-rollout.jsonl"},
    {"source": "/source/.codex/attachments/selected-id", "target": "codex-assets/attachments/selected-id"}
  ]
}
```

脚本在源主机运行；路径属于该主机。`target` 只能是归档内相对路径。

```bash
python3 scripts/file_bundle.py pack --spec items.json --output /scratch/session-bundle.tar.gz
```

对普通源码仓库可额外加 `--git-repo /source/project/repo=workspace/repo`。它收集 `git ls-files -c -o --exclude-standard -z` 和 `.git`，保留现有 index，不执行 add/commit/reset。ignored 目录内的必要源码（例如第三方 encoder）须显式加到 items。执行前只读检查 `.git` 是否自包含；脚本拒绝 worktree、submodule、alternates 和进行中的 lock。

快照写入归档 SHA-256 与逐文件 manifest；额外记录 `git rev-parse HEAD`、`git status --porcelain=v1`，必要时保存 `git diff --binary` 与 `git diff --cached --binary` 以验证内容。普通源码复制后的路径配置不等于训练环境已经可运行。

通过已有 SSH 路径传输。源和目标彼此不直连时，可以用本机中转：

```bash
scp -3 source-host:/scratch/session-bundle.tar.gz target-host:/writable/migration/session-bundle.tar.gz
```

此语法假设路径没有特殊字符；否则采用参数化 subprocess/SFTP 或本地暂存传输，不把未转义路径插入 shell。

```bash
python3 scripts/file_bundle.py unpack \
  --archive /writable/migration/session-bundle.tar.gz \
  --destination /writable/migration/restored \
  --sha256 CHECKSUM_FROM_PACK
```

目标目录必须不存在，失败时保留诊断而不复用半成品目录。默认不删除源文件。

## 3. 重映射导入副本与附件

将旧 cwd 及历史别名映射到新 workspace，映射文件如：

```json
{
  "/source/original/project": "/destination/migration/workspace",
  "/source/alias/project": "/destination/migration/workspace"
}
```

```bash
python3 scripts/file_bundle.py rewrite \
  --input restored/session/source-rollout.jsonl \
  --output restored/session/import-rollout.jsonl \
  --mapping path-map.json
```

`rewrite` 是按最长旧路径优先的一次文本替换，不会再次处理新写入的目标路径。它会修改副本中所有匹配文本，包括历史命令和输出；因此保留原始字节和映射作为审计依据。必要时对指定 Markdown 文档做同样处理，完成后另外校验这些有意变化的文件。

若 session_meta 含 `history_base`，当前 rollout 只保存 fork 后的新增历史。递归带上祖先 rollout，保持原 ID 和 ordinal，不复制整个历史数据库。子记录中的 `end_byte_offset` 指向祖先原始字节边界：祖先路径重写会改变字节数，须将**原边界之前的前缀**单独重写并按 UTF-8 字节重新计算边界；不要一律写祖先当前文件长度，因为祖先可能在 fork 后继续工作。`end_ordinal_exclusive` 保持原逻辑边界。本次实测祖先没有后续内容，边界恰好为全文件长度。

在目标 Codex home 中恢复附件原相对目录，可保留绝对路径使图片解析。已有路径哈希不同则使用隔离的新目录并加入映射；不能覆盖。图片的 data URL 已在历史内不代表本地 `view_image` 引用也有效。

## 4. 先确认当前协议与 provider

在目标机执行：

```bash
codex app-server generate-json-schema --experimental --out /scratch/codex-migration-schema
```

读取生成的 `InitializeParams`、`ThreadListParams`、`ThreadForkParams`、`ThreadResumeParams`、`ThreadReadParams`，以及当前分页和改标题参数。不要复制另一台主机的 schema 作为本机能力证明。

只读取 config 的 model/provider 名称和可用模型元数据；不要输出 API key、token、完整 auth 文件。源 provider 在目标不存在时，`resume` 会失败。用 fork 的线程级 `modelProvider`/`model` override 选择目标已经配置且可用的设置；保留 reasoning effort 并验证返回值。若没有合理可用映射，保存已验证文件，说明具体缺项后再请用户选择或授权配置。

## 5. 注册目标临时历史，再 fork

下面是该版本上已验证的顺序，变更仅发生在目标机：

1. 检查源 ID 在目标 active/archived 历史及已加载会话中均未存在。若存在，先核对来源，使用当前 schema 支持的隔离导入/fork 路线；不要覆盖或随意改 session UUID。
2. 将 `import-rollout.jsonl` 复制到目标 Codex home 的规范目录，例如 `sessions/YYYY/MM/DD/rollout-<original-timestamp>-<source-id>.jsonl`。日期和时间从源元数据/原文件名获取。该文件是目标临时副本，源主机未变。
3. 用 `thread/list` 扫描修复元数据。若当前 schema 支持 `modelProviders: []`，可用它包含所有 provider 的历史，防止旧 provider 记录被过滤。对所需会话读取确认注册成功，不以列表第一项推断。
4. 使用 **`threadId` fork**；对已注册的 paginated thread 省略 `path`。传目标 cwd、runtime roots，必要时带线程级 provider/model override。`deferGoalContinuation: true` 在 schema 支持时防止自动启动目标续跑。
5. 保存返回的新目标 ID 和规范 rollout 路径，改标题，然后 `thread/read` 验证。不要发 `turn/start` 来“测试”。
6. 目标验证全部成功之后，可归档**仅在目标机创建**的旧 ID 临时副本。其 ID 与源 ID 相同，因此必须明确主机。保留源主机原会话。

使用请求文件避免 shell JSON 转义。示例 `requests.json`：

```json
[
  {"method": "thread/list", "params": {"limit": 100, "modelProviders": []}},
  {"method": "thread/fork", "params": {
    "threadId": "SOURCE_THREAD_ID",
    "cwd": "/destination/migration/workspace",
    "runtimeWorkspaceRoots": ["/destination/migration/workspace"],
    "deferGoalContinuation": true,
    "excludeTurns": false
  }}
]
```

```bash
python3 scripts/codex_rpc.py call \
  --requests requests.json --output import-results.json
```

运行一次后检查保存的响应，再用新 ID 发 `thread/name/set`、`thread/read`，最后单独归档临时副本。不要把需要前一响应中新 ID 的步骤硬编码进同一个请求列表。完整响应可能含对话内容，只存迁移目录，不上传 GitHub。

helper 默认新建 `codex app-server --stdio` 连接，退出只结束该子进程，不结束桌面端的其他会话。若目标部署不支持独立 stdio，改用该版本明确文档化的连接方式。实测 `app-server proxy` 的 initialize 曾超时，不能把等待误判为登录失效，也不能改写 daemon 文件解决。

若 `thread/read` 与 `thread/turns/list` 均返回空历史，但 rollout 确实包含 `task_started` / `item_completed` 等事件，先检查投影是否尚未建立。本次目标版本需对**仅本次导入的临时副本**依次 `thread/resume` 祖先、再 resume 子线程，才把持久化事件建立为可分页历史；不发 `turn/start`。随后必须重读全部分页并与源导出比较，通过后才能 fork。不要把空数组当作可验证的成功结果。

请求超时或断开后禁止直接重试 fork：先 `thread/list` / `thread/read` 检查是否已经生成目标 ID。每个变更请求都记录结果；不做无限重试。

## 6. 验证历史与可见性

在源（或目标归档的原始临时副本）和目标分别导出 `thread/read`，如当前版本支持 `includeTurns: true` 且实际返回全部轮次，可保存完整响应。

```json
[{"method":"thread/read","params":{"threadId":"DESTINATION_THREAD_ID","includeTurns":true}}]
```

若当前版本返回分页，用生成的 schema 依次遍历 `thread/turns/list`、每轮 `thread/items/list`；逐页跟随 cursor、去重并保留原顺序。直到分页耗尽才能写成统一的 `{"thread":{"turns":[...]}}` 文件。读取 `itemsView` / `itemsPagination` 等字段确认条目完整，不能只拼装摘要。

```bash
python3 scripts/codex_rpc.py compare \
  --source source-read.json --destination destination-read.json \
  --output history-verification.json
```

helper 比较的是轮 ID、status 和每轮条目 ID/type，不宣称正文每字节一致；有意重映射的路径会改变文本。额外抽查最早和最新消息、最终回复、工具输出与图片。paginated fork 可能将历史存入规范历史存储，新的 rollout 文件只有少量控制记录；不能只数目标 JSONL 的 `response_item` 就判断历史为空。

可进一步递归比较每轮完整 JSON：先仅应用已记录的路径映射，再排除已证实的协议字段差异。本次源端每轮 `rootTurnId == id`，目标旧版本省略 `rootTurnId`；验证该等价关系后可忽略此字段，其他正文、附件和工具内容仍须一致。

较早轮次可以处于 `interrupted` 或 `failed`，迁移时应原样保留；不能为了让校验通过而删除。helper 接受这些已结束状态并逐一比较，拒绝 `inProgress`。本次快照开始前，最新轮仍须满足用户要求的完成条件。

最后用桌面工具 `list_threads` 指定目标 host、`read_thread` 指定新 ID 验证可见性。若 `move_thread_to_project` 报 sidebar 不可用，可先 `set_thread_title` / 刷新列表触发加载后再试一次；“source project could not be safely determined” 则说明历史导入未建立项目归属，保留可用聊天并如实记录，不直接编辑全局 UI JSON 或 SQLite。

本次旧目标版本的 paginated fork 只写 history_base，`thread/list` 会因空的本地用户预览过滤它，尽管按 ID 读历史完全正常。可在需要直接可见入口时置顶该迁移会话，并用 recent `list_threads` 的 pinnedThreads 验证，再如实说明项目归属限制；置顶不等于项目归属已修复。不要复制用户消息伪造新一轮，也不要为刷新列表启动推理。若为了诊断产生额外目标 fork，最终验证后仅归档本次目标临时线程。

## 错误定位

| 错误/现象 | 已验证的含义与处理 |
|---|---|
| `The source thread workspace is not a git repository` | 原 cwd 不在仓库；改用手动流程，不能在大用户目录临时 git init |
| `Read-only file system` / scp `dest open ... Failure` | 检查 mount 与目标路径；使用授权范围内的新可写目录 |
| `no rollout found for thread id ...` | 该版本要求先安装到规范 sessions 位置，再让 `thread/list` 注册 |
| `cannot resume paginated thread ... with stale path ...` | 记录已有 canonical path；省略 path，使用 ID，不移动已注册记录 |
| `Model provider ... not found` | 目标缺源 provider；使用可用的线程级 override，不复制密钥或全局配置 |
| cwd 文本不相等 | 先比 `realpath`，可能只是目录别名被 canonicalize |
| 目标 rollout 的 response_item 为 0 | 可能是分页历史存储；从 API 读取全部轮次比较 |
| 侧边栏项目归属失败 | 分别记录“历史可见”与“项目归属”；不宣称两者都完成 |
