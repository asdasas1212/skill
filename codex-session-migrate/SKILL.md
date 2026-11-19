---
name: codex-session-migrate
description: 迁移或复制 Codex 桌面端会话到另一台本地或 SSH 主机，同时保留对话历史、附件和指定工作文件。适用于跨机器续聊、非 Git 工作目录无法内置移交、分页历史导入及迁移完整性核验。
---

# Codex 跨机器会话迁移

交付一个能在目标主机被 Codex 列出、读取并继续使用的会话，以及用户要求的文件。区分会话迁移与训练环境、数据集、权重迁移；在报告中明确实际范围。默认保留源会话和源文件。

## 先定位并选择路线

1. 通过 `list_threads`、`read_thread`、`list_projects` 确认会话 ID、所属主机、当前工作目录与运行状态，不能仅凭同名标题操作。
2. 若用户要求运行完再迁移，以 `wait_threads` 跟踪，确认最新轮为 `completed` 且会话空闲后再快照。迁移前再次核对；若又开始运行，继续等待。内置 `handoff_thread` 会中断运行中的会话，不能用它试探支持情况。
3. 优先使用内置 `handoff_thread`：先只读确认当前工作目录确实属于 Git 仓库，且目标有工具可识别的匹配项目。工作目录下某个子目录是仓库，不代表工作目录本身满足条件。内置移交的生成文件、忽略文件和附件覆盖范围仍需核验。
4. 非 Git 工作目录、无法匹配的项目或内置移交不适用时，按 [手动导入流程](references/manual-import.md) 复制文件并在目标主机 fork 历史。新会话通常会获得新 ID。

## 迁移必须保留的边界

- 只操作选定会话和明确选定的文件；不整库覆盖 `state_*.sqlite`、`thread_history_*.sqlite`、`config.toml`、`auth.json` 或其他会话。
- 一次迁移授权不包含删除源文件、清理原会话、发送新提示词、启动训练或迁移模型供应商密钥。导入、读取和 fork 历史不需要发起模型推理。
- 分别检查 SSH 可达、目标目录可写、剩余空间和路径真实位置。`os.access` 之外检查挂载只读位；遇只读挂载，在用户授权位置选择新可写目录，记录原因与真实路径，不修改挂载设置。
- 复制当前源码时保留 tracked/untracked 文件及 Git index；Git HEAD 相同不能证明未提交内容相同。普通目录仓库可复制 `.git`；链接 worktree、submodule 或 `.git/objects/info/alternates` 必须另做自包含处理，不能复制一个指向旧机器的 `.git` 文件后宣称完成。
- 原始 rollout 原样备份。仅重写目标导入副本与明确选定的文档链接，采用一次替换，避免旧路径是新路径前缀时重复污染。不要重写源会话。
- 本地附件必须可解析；相同目标路径已有文件时核对哈希，冲突则使用隔离目录并更新副本引用，不覆盖。
- provider/model 以目标可用配置为准；优先保留源设置，缺失时使用明确可用的目标设置并说明差异。不要复制凭据、修改全局 provider 或悄悄改用未知模型。

## 工具与参考

先读 [手动导入流程](references/manual-import.md)，其中包括 schema 探测、分页历史、canonical rollout 路径、provider 不存在和项目归属失败的处理。

- `scripts/file_bundle.py`：`pack` 对明确文件清单打包并生成 SHA-256 manifest；`unpack` 在新目录解包并验证；`rewrite` 在保留原件的情况下按 JSON 映射重写一个副本。`pack --git-repo` 收集普通 Git 仓库的 tracked/untracked 文件和 `.git`，不会自动包含 ignored 依赖。
- `scripts/codex_rpc.py`：通过本机 `codex app-server --stdio` 执行显式提供的迁移/只读 RPC 请求，支持 `compare` 比较两份 `thread/read` 导出的轮次与条目。脚本不提供 `turn/start`、中断或删除接口。脚本应在实际拥有目标 Codex 数据目录的主机执行。
- [实测过程记录](references/migration-case.md)：一次非 Git 工作目录迁移的结果、失败原因及修复顺序。数字是案例证据，不是每次迁移的目标或固定要求。

示例中的路径与 provider 均需从本次环境解析。辅助脚本不代替会话空闲检查，也不自动重试变更请求。请求超时后先检查目标状态，再决定是否重试，避免重复 fork。

## 完成标准

- 校验压缩包 SHA-256、逐文件 manifest，并单独验证复制源码的 Git HEAD 和 staged/unstaged 状态。
- 通过 Codex 读取源和目标导出，比较轮次、完成状态及条目 ID/类型。当前接口若只能返回分页，先导出完整分页再比较；不得把摘要或空数组当完整历史。抽查最新最终回复、最早用户消息、附件和目标文档链接。
- 目标会话能通过 `list_threads` / `read_thread` 访问，工作目录可写且指向新文件。项目归属或侧边栏显示失败时如实记录，不把“历史导入成功”说成“项目归属成功”。
- 报告来源/目标主机、新旧会话 ID、文件位置、校验结果、model/provider 差异与未迁移内容。仅在目标导入成功后，才可归档本次创建的目标临时历史副本；这不是归档源主机会话的授权。
