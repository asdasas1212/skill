# 宿主机写入入口、共享盘与文件名兼容

用于容器读取目录为只读，但用户提供宿主机或其他机器写入入口的情况。这里的方法来自 2026-11-19 实测案例，主机与路径使用通用示例名；每次重新验证，不应写死机器或假定挂载永远不变。

## 先验证映射

示例映射：`host-write:/shared/workspaces/user`，写入后在 `target-host:/mnt/storage/workspaces/user` 可见。

- 宿主机路径为 CIFS 挂载，挂载可写；普通 SSH 用户无目录访问权，但既有 Docker 权限可以通过已缓存镜像与新建 bind mount 访问已授权目录。
- 现有容器曾把同一宿主机路径绑定到 `/workspace/user`。宿主机之后挂载了 CIFS，旧容器的 bind mount 仍看到旧的底层目录，不能据 Docker inspect 的 Source 字符串认为两者一致。
- 临时容器重新 bind 用户提供的宿主机路径后，看到的文件与存储卷原生读取路径一致；既有报告哈希及新建唯一探针都验证通过。

优先直接用用户已有可写入口。若仅现有 Docker 权限可用，可用已缓存镜像启动短生命周期工具容器，`--network none`，只 bind 本次输入与目标路径，不更改现有容器、不启动其默认训练入口、不挂 Docker socket、不使用 privileged。镜像通过目标现有容器的 image ID 获取，避免拉取或猜测。工具容器退出后自动移除。

唯一探针只写本次创建的短文本，检查另一路径出现同内容，然后删除该探针。路径能列出相同文件只是证据之一，不能替代写后可见性验证。

## SMB/CIFS 不能当作完整 POSIX 工作区

通过 SMB 写入、从 GPFS 原生路径读取时，可能发生文件名编码转换。本次 3 个 MuJoCo `.obj` 文件的路径含冒号 `:`，通过 SMB 看名称正常，原生 GPFS 读取却显示为私用字符 U+F022，Git 因而报告文件删除。大小写、执行权限和 symlink 也应按实际文件清单检查，不要只在写入端验哈希。

处理原则：

1. 完整 POSIX tar 归档保存在用户指定的共享盘，哈希核对；归档内部保留原文件名、权限和 Git metadata。
2. 设计文档、实验代码和结果可以展开供查看，但报告中明确兼容问题，不能将有名称差异的展开副本标为逐文件完整。
3. 需要继续编辑、运行 Git 的会话使用目标机可写的 Linux 文件系统副本，并说明最终 cwd；用户要求严格使用某目录时，先说明实际限制，不能隐瞒替代位置。
4. 不为解决挂载只读而重启正在工作的容器、全局 remount 或修改其他会话配置。

本次在目标机的可写项目目录（如 `/srv/projects/example-project/migration-workspace`）解包通过 4,212 文件及 Git staged/unstaged 校验；用户指定的共享目录保存了完整归档与可查看展开副本。

## Git 验证

SMB 固定的 UID/GID 可能触发 dubious ownership。只对明确校验的仓库使用进程级 `git -c safe.directory=/exact/repo`；不要设 `safe.directory=*`。文件系统无法保留执行位时，可用进程级 `-c core.filemode=false` 帮助区分内容差异，但报告该限制，不静默改全局 Git 设置。带冒号路径导致的缺失不能用忽略 filemode 掩盖。
