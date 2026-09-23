# 叙光集服务器部署

最近部署日期：2026-09-23。服务器：`47.110.79.237`，Ubuntu 24.04、8 vCPU、28 GiB 内存。

## 当前状态

- 2026-09-23 补拍验证修复：旧分析的提示词版本与当前版本不同，曾被整体配置哈希校验误判为任务过期。补拍验证现在保留原分析与证据来源，按当前模型配置独立提取新素材并分区缓存；原视频、创作要求与最新成功分析保持一致时可继续使用原任务。需求或主片确实变更时继续拦截；验证期间再次上传补拍不会仅因 revision 增加被判过期。演示/真实模式继续隔离，晚到结果不覆盖已忽略或已解决的问题。
- 补拍执行异常与“画面未满足要求”分开记录；重试恢复排队状态并清除旧错误，前端不再将中断误显示为持续分析。主分支应用提交 `ad4eeaa`；本地后端全量 324 项及新增重试回归通过，前端状态测试 5 项、TypeScript/Vite 构建通过，服务器 Linux 41 项相关测试通过。数据库备份为 `/opt/xuguangji/backups/verification-context-r1-20260923/database.dump`，14 个项目与 4 个账号保留，HTTP 首页和健康检查 200、未登录项目接口 401，公网静态资源与本地构建一致。

- 2026-09-23 分析修复：全片审阅曾因第 5 条建议的 `duration_s=0` 连续两次被结构校验拒绝。现将时长按建议类型校验：纯删除/调序的 `reedit` 允许 0，`reshoot` 必须大于 0，均不超过 30 秒且必须为有限数；不自动填充时长。模型修复请求包含具体字段路径、类型和应用定义的约束，仍最多修复一次。日志不保存拒绝值或原始模型输出。
- 真实恢复中另发现模型误写长证据编号。审阅输入现使用 `shot_N` / `evidence_N` 短引用，去除缩略图和存储路径等无关字段；程序逐项核对引用及镜头归属后精确还原数据库 ID，不猜测、不丢弃错误引用。语义修复会指出具体字段及对应镜头可用证据。同一有效镜头被重复设为相关镜头时规范化为空；同镜头的多条有效证据全部校验后，沿用原诊断逻辑挑选最多两条关键证据，避免重复引用阻断整条分析。分镜分析动态约束原片绝对时间、采样窗口边界和 `end > start`，时间错误也进入一次定向格式修复。
- 相同配置与素材的失败重试会校验并复用成功窗口，仅补跑失败窗口；无法安全映射缓存时重新分析。视觉提示词版本继续为 `vlog-review-v2.1`，本次修改的是全片审阅规则及格式修复逻辑。
- 修复验证：本地后端 297 项测试、服务器 Linux 138 项相关测试、前端 TypeScript 与 Vite 构建通过；最后的文字引用转换另在本地及 Linux 各通过 55 项相关回归。切换前无运行/排队任务，数据库备份在 `/opt/xuguangji/backups/review-schema-r4-20260923/database.dump`；14 个项目与 4 个账号的归属/认证数据保持不变。上一发布 `review-schema-r3-20260923` 及品牌发布 `storylight-20260923` 均保留用于回退，公网首页及 health 返回 200，未登录项目接口仍为 401。

- 品牌已统一为“叙光集”，登录页、侧栏与标签页采用“叙事画框＋光点”图标。品牌更新仅调整展示名称与图形；保留 `xuguangji` 服务名、目录、会话标识与数据库，现有账号和项目继续使用。

- 前端生产构建、FastAPI、PostgreSQL 16、Redis 7、Celery 和 FFmpeg 已部署。Nginx、数据库、Redis、API 和 worker 已启用开机自启。
- 当前代码来自主分支 `main`，发布目录为 `verification-context-r1-20260923`（应用提交 `ad4eeaa`）。已支持注册、登录、退出、修改密码，项目与素材/任务按用户隔离，项目卡片支持重命名和确认删除。11 个旧项目已保留并归属 `caozheng`；首次密码仅保存于本地比赛目录的私密账号文件，没有写入仓库。
- 提示词版本更新为 `vlog-review-v2.1`，参与分析配置及视觉证据缓存键。旧结果保留、读取时自动缩短时间格式；字幕误判需要用户重新发起分析，不能复用旧视觉证据。字幕接地修复发布当时未自动执行收费分析或生成。
- 视频采样帧理解与新素材视觉验收为 `qwen3.8-max`，全片文字审阅为 `qwen-plus`。此前服务器真实图片请求返回一条通过 schema 校验的证据，用时 39.467 秒；此检查不代表质量或并发性能基准。当时的合并未重新执行付费分析、生成或验收。
- 账号隔离版本在本地及服务器 Linux 均通过 213 项测试，Edge 桌面及手机预览验证账号隔离、项目改名和删除。本次品牌更新通过 21 项账号与迁移回归检查、前端 TypeScript 检查与 Vite 构建，验证新版登录页、线上名称及图标；现有 11 个项目与 2 个账号保持不变。没有执行付费模型调用。
- 保持 `http://47.110.79.237`，不跳转 HTTPS。网页使用应用账号登录；Nginx Basic Auth 仍关闭。公网页面和健康检查返回 200，未登录的项目接口返回 401。
- 当前电脑绕过代理的直连测试仍超时，这与浏览器实际可访问的结果不同，不能据此认定安全组未放行。若某个网络无法访问，应分别检查客户端网络路径和服务器入口。
- 数据库、Redis、后端与管理预览端口只监听回环地址。模型密钥只在受保护的服务端配置中。
- HTTPS 与证书续期未启用；仓库保留可选脚本，只有后续明确改用 HTTPS 时再执行。

## 目录与服务

|路径或服务|用途|
|---|---|
|`/opt/xuguangji/current`|指向当前发布目录的符号链接|
|`/opt/xuguangji/releases/verification-context-r1-20260923`|当前主分支代码，补拍验证配置兼容及状态修复|
|`/opt/xuguangji/venv`|Python 3.12 运行环境|
|`/opt/xuguangji/certbot`|Certbot 5.8.0 独立环境|
|`/etc/xuguangji/app.env`|数据库与百炼配置，`root:xuguangji`、`0640`|
|`/var/lib/xuguangji/media`|上传、采样帧、代理及导出媒体|
|`xuguangji-api.service`|FastAPI，监听 `127.0.0.1:8000`|
|`xuguangji-worker.service`|Celery，8 个 worker 进程，全局 8 个模型请求名额|
|Nginx `127.0.0.1:8080`|仅用于 SSH 隧道的完整网页入口|

本次使用 systemd 原生部署；Docker Hub 在服务器上连接超时，没有运行 Docker Compose。发布包通过 SSH 上传，不在服务器保存 GitHub 登录凭据。原有本地项目数据未迁移；本次保留服务器已有项目与历史结果，仅新增明确标注的三镜头合成验证项目。切换前数据库与媒体备份保存在 `/opt/xuguangji/backups/vlog-v2-20260922`。

## SSH 隧道访问

在存放私钥的「影石比赛」目录执行：

```bash
ssh -i _NJU_Token.pem -N \
  -L 127.0.0.1:18080:127.0.0.1:8080 \
  root@47.110.79.237
```

浏览器打开 `http://127.0.0.1:18080`，使用应用账号登录。隧道必须保持运行；这个 localhost 地址只有建立隧道的电脑可以使用。普通使用直接访问公网 HTTP 地址即可，无需建立隧道。

## HTTP 配置

Nginx 使用 `deploy/nginx-http.conf.template` 和 `deploy/nginx-app.conf`，监听 80 端口并直接提供前端及 API，`auth_basic off`。前端为不支持 `crypto.randomUUID()` 的 HTTP 上下文提供基于 `crypto.getRandomValues()` 的 UUIDv4 实现，素材上传和分析请求仍使用幂等键。

## 可选 HTTPS（当前未启用）

1. 在阿里云 ECS 中找到该实例的安全组，允许入方向 TCP 80 和 TCP 443，来源 `0.0.0.0/0`。后端 8000、管理 8080、数据库 5432 和 Redis 6379 无需对公网开放。
2. 从服务器外访问 `http://47.110.79.237/.well-known/acme-challenge/connectivity-check`，应返回 `xuguangji-ready`。
3. 登录服务器执行：

```bash
bash /opt/xuguangji/current/deploy/enable-https.sh 47.110.79.237
```

脚本先做 Let's Encrypt 测试环境验证，再申请受信任证书；通过 Nginx 配置检查后启用 HTTPS，安装每 12 小时检查一次的续期 timer，并执行一次续期演练。执行后 HTTP 会跳转到 HTTPS，访问方式仍为免登录。当前用户要求使用 HTTP，因此未执行此流程。

IP 证书需使用 `shortlived` profile，Certbot webroot 方式要求 5.4 及以上版本，参见 [Let's Encrypt 官方说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)。切勿将只有证书申请脚本准备好当作 HTTPS 已验收。

## 日常维护

当前使用 [8 核并发配置](CONCURRENCY.md)：`WORKER_CONCURRENCY=8`、`MODEL_CONCURRENCY=8`、`MEDIA_CONCURRENCY=2`、`FFMPEG_THREADS=4`、`MODEL_TIMEOUT_S=900`；PostgreSQL 每进程连接池为 2+2。单次模型响应读取等待 15 分钟，连接/上传/连接池超时为 30/60/30 秒，整条分析无该总时长限制。worker 的 `CPUQuota=800%`，实测 `CPUQuotaPerSecUSec=8s`。同机所有进程必须使用同一 `DATA_DIR` 和限额设置。

视频生成使用现有 worker 与数据库，无新增数据库迁移：`VIDEO_GENERATION_ENABLED=true`、`VIDEO_GENERATION_MODEL=happyhorse-1.1-i2v`、`VIDEO_GENERATION_BASE_URL=`、`VIDEO_GENERATION_CONCURRENCY=1`、`VIDEO_GENERATION_POLL_S=15`、`VIDEO_GENERATION_TIMEOUT_S=900`。空的生成地址从现有百炼业务空间地址推导，沿用服务端密钥。生成并发独立于 8 路视频理解；刷新页面可恢复任务，云端已提交任务优先恢复查询与下载。

回退到合并前版本时，必须先确认没有排队、执行中或提交结果待核实的视频生成任务；旧 worker 不支持新生成任务，不能在仍有任务时直接切回旧发布目录。

并发升级前的数据库、媒体、环境配置与 worker unit 备份位于 `/opt/xuguangji/backups/parallel8-20260922`。切换前检查数据库任务以及 Redis queued/unacked 均为空；先确认 worker 已就绪，再恢复 API 入口。

`qwen3.8-max` 更新前的环境配置和 PostgreSQL 备份位于 `/opt/xuguangji/backups/qwen38-20260922-2`；本次没有数据库结构迁移或媒体改写。切换前及停 API 后，数据库 queued/running 和 Redis queued/unacked 均为 0。新 worker 就绪后实测进程池为 8；`VLM_MODEL=qwen3.8-max`、`LLM_MODEL=qwen-plus`、`MODEL_CONCURRENCY=8`，环境文件权限保持 `root:xuguangji 0640`。

```bash
systemctl status xuguangji-api xuguangji-worker nginx
journalctl -u xuguangji-api -u xuguangji-worker -n 100 --no-pager
systemctl restart xuguangji-api xuguangji-worker
systemctl list-timers xuguangji-cert-renew.timer
```

修改 `/etc/xuguangji/app.env` 后重启 API 和 worker。网页入口使用应用账号；注册和密码维护见 [账号与项目管理](ACCOUNTS.md)。

代码更新使用新的 release 目录，上传源代码和 `frontend/dist`，安装 Linux 锁文件中的依赖，链接受保护的 `.env`，执行 Alembic 迁移，再切换 `current` 并重启两个服务。更新前应等正在执行的作业结束，并备份 PostgreSQL 与 `/var/lib/xuguangji/media`；回退代码不能代替数据库恢复。当前未配置异地备份或业务监控告警。账号迁移前 PostgreSQL 完整备份位于 `/opt/xuguangji/backups/accounts-20260923-075536/database.dump`；同目录保留配置和上一发布路径。项目删除为软删除，不移除底层媒体文件。

纯前端发布可省去上述依赖安装、数据库迁移与服务重启：先确认新提交的后端、部署配置和依赖与运行版本完全一致，再将已验证的构建放入新 release，保留上一版哈希静态资源，并原子切换 `current`。Nginx 继续从该路径提供新前端，既有 API 和 worker 进程不受影响；回退时原子切回旧目录。

## Linux 依赖

`backend/requirements-linux.lock` 在现有版本约束下为 Linux x86_64 / Python 3.12 解析，补齐该平台需要的 `greenlet`。其他包版本与已验证的本地锁文件一致。

```bash
uv pip compile backend/requirements.in --python-version 3.12 \
  --python-platform x86_64-unknown-linux-gnu \
  --constraint backend/requirements.lock \
  -o backend/requirements-linux.lock
```

本次服务器的软件镜像缺失部分锁定版本，访问官方 PyPI 也有超时，因此在开发机从官方 PyPI 下载 Linux wheel，通过 SSH 上传后使用 `pip install --no-index --find-links` 安装。安装后 `pip check` 无缺失或冲突。Dockerfile 同样改用 Linux 锁文件，但 Docker 构建路径尚未实机验收。

## 实际验证

- `ad4eeaa`：截图中两条补拍任务已通过原重试接口恢复，作业均为 `succeeded / 验收完成`，错误已清空，无残留运行任务。新素材分别提取 4 条真实证据，逐项验收只引用本次新素材证据；原分析配置哈希未改写，验证记录保存当前模型、提示词版本及独立配置哈希，两份结果均非历史过期结果。两次上传文件内容相同；旧一次判为 `passed`，最新一次判为 `partial`（石板路纹理与行进过程不够清晰），保留模型原始结论，不将处理完成等同于素材全部合格。旧发布 `review-schema-r4-20260923` 保留用于回退。

- `911485c`：截图对应的杭州旅游 Vlog 原任务已恢复为 `succeeded`，项目最新结果指向该分析。25 个镜头画面分析完整、失败区间为空，5 条建议成功保存；前两轮部分缓存分别复用 23、24 个镜头，最终汇总复用全部 25 个镜头的 50 条证据。实际运行验证了零时长证据与不合法建议位置的定向修复。最终诊断接口的 577 段可读字段不再包含内部 UUID 或短引用标签。标签按对应镜头的真实时间精确转换，结构化 ID 保持不变，没有为排版再次调用模型；转换前原结果备份于本次备份目录中的 `analysis-before-readable.json`。

- `accounts-20260923`：本地及 Linux 均 213 项测试通过。旧 PostgreSQL 迁移至 `0002`，11 个项目保留并显式分配给 `caozheng`。线上验证未登录 401、登录后项目列表及视频 Range 206、另一账号读取旧项目 404、临时项目创建/改名/删除及登出失效；验收账号和空项目已清理，用户项目数量保持 11。公网 HTML 引用 `index-DECdNs8U.js` / `index-Ddul3El6.css`，与本地构建一致。

- `53f2e6d`：本地及 Linux 后端各 192 项测试通过；Linux 测试的 `0984b63` 与合并后的后端、前端源码逐文件一致，合并仅新增 PPT 文件。公网首页与 health 返回 200，无认证或 HTTPS 重定向；`index-BT21k_eh.js`、`index-CiRDzMdb.css` 与本地构建字节一致，新 JS 已无两个小标题。街舞项目历史诊断的 179 段阅读文字中无超过一位小数的秒数，数据库中 3 条原有精确时间建议仍保留，媒体 Range 返回 206。运行时提示词版本为 `vlog-review-v2.1`。
- 本次切换前及停止 API 后，数据库 queued/running 与 Redis queued/unacked 均为 0；完整 PostgreSQL、媒体与环境配置备份位于 `/opt/xuguangji/backups/subtitle-grounding-20260923-53f2e6d`。worker 确认就绪后启动 API，五项服务 active，环境文件保持不变；旧目录 `copy-cleanup-20260923` 保留，可原子切回。没有迁移数据库结构、重写用户结果或调用收费模型。
- `4c05a58` 为纯前端文案清理发布：TypeScript 检查及 Vite 构建通过，桌面和手机浏览器验证详见 [工作区细节调整](WORKSPACE_REFINEMENTS.md)。公网首页、health、projects 返回 200，项目数为 8；`index-C8LTXRMm.js`、`index-9tp9DRbt.css`、首页及 favicon 与本地构建字节一致。上一版哈希资源继续返回 200，原片和 preview 的 Range 均为 206。HTTP 无认证、不跳转 HTTPS。
- 本次使用原子目录切换，API/worker/Nginx 的 PID 保持 `2011/2012/1296`，五项关键服务的进程与启动时间均未变化；后端、部署配置逐文件与旧 release 相同，环境文件字节未变。没有执行迁移、数据库/媒体写入或付费请求。旧目录 `/opt/xuguangji/releases/analysis-focus-20260922` 保留用于回退。
- `1900fb7` 发布包 Linux 后端测试：182 项通过（42.32 秒），本地同样 182 项通过。公网 `index-CNg-vIz0.js`、`index-D29r07hZ.css` 和 favicon 的 SHA256 与本地构建一致，首页及健康检查返回 200；全部五个剪辑/版本/成片导出 GET/POST 入口返回 410，OpenAPI 不再公开剪辑接口。原片及 preview 的 Range 返回 206，生成选项/历史返回 200；生成、素材和补拍分析接口保留。HTTP 免登录、不跳转 HTTPS。
- 用户分析任务 `d704ba65-2a13-4e93-bee6-77022c5b2e3c` 自然完成后才开始切换；停 API 前后数据库 active jobs 与 Redis queued/unacked 全为 0，worker 8 并发就绪后恢复 API。本次环境文件字节级未变，16 张表的数据 SHA256 和 854 个媒体文件（共 354,966,101 字节）的清单发布前后完全相同。备份目录为 `/opt/xuguangji/backups/analysis-focus-20260922`，含 PostgreSQL dump 和环境文件，旧 release 保留。
- 新界面本地浏览器验收包含桌面固定工作区、手机无横向溢出、通知开关/错误恢复、复制重剪建议、AI 生成的时长校验与贴近按钮的禁用原因。所有预览服务只允许 GET，未创建付费任务；验证详情见 [工作区细节调整](WORKSPACE_REFINEMENTS.md)。
- `bfa869a` 合并发布包 Linux 后端测试：168 项通过（43.30 秒），本地同样 168 项通过。公网 `index-B2h1lp4o.js`、`index-C8HVj4WI.css` 和 favicon 的 SHA256 与本地构建一致；页面、health、projects 及生成选项/历史接口均返回 200，媒体 Range 返回 206，无认证或 HTTPS 跳转。旧补拍任务正确提示重新分析并生成计划，重剪任务正确禁用 AI 生成。HappyHorse Provider 对此前真实云端任务执行只读查询，返回 `SUCCEEDED`，本次没有新提交计费请求。
- 杭州历史数据 SHA256 发布前后均为 `407a458e363d75b0908700e895dc402ed03753835b79560fbbde90413cd21740`；原始 28 镜头显示为 25 段，最短展示段 1.1334 秒，来源覆盖完整且连续。切换前、停 API 后和发布完成后，数据库 active jobs 与 Redis queued/unacked 均为 0；worker 确认 8 并发后才恢复 API。环境配置仅新增六项视频生成字段，权限保持 `root:xuguangji 0640`。环境文件和 PostgreSQL 备份位于 `/opt/xuguangji/backups/happyhorse-main-20260922`，旧发布目录保留。
- 合并 UI 的本地只读验收复用此前生成的视频，验证首帧选择、时长校验、历史恢复、预览播放和下载链接；内置浏览器完整播放 5.16 秒，控制台无警告/错误。Safari 本机裸视频与面板预览出现黑屏，原因尚未确定，不能据内置浏览器的结果宣称所有浏览器均已通过。
- `501a1ba` 发布包 Linux 后端测试：125 项通过（41.52 秒）。公网 JS/CSS/favicon 的 SHA256 与本地构建一致；杭州项目原始 28 个镜头合并显示为 25 个，历史 AnalysisRun.data 与 Asset.meta 的 SHA256 发布前后相同。服务器运行时读取超时确认为 900 秒，其他环境配置逐行不变；worker 与模型并发均为 8。页面/API HTTP 200，媒体 Range 206，无认证或 HTTPS 跳转。该次环境配置与 PostgreSQL 备份位于 `/opt/xuguangji/backups/workspace-yellow-20260922`，原发布目录保留以便回退。
- `3c7b27e` 发布包 Linux 后端测试：103 项通过（39.22 秒）；该次已验证建议文案的内部编号转换为时间段，机器引用保持不变。
- `c807e6d` 发布包的 Linux 后端测试：90 项通过（38.64 秒）；服务器真实新模型兼容性结果保存在 `/var/lib/xuguangji/media/deployment/qwen38-20260922/result.json`。
- Celery 实际进程数 8、共享模型上限 8、FFmpeg 命令上限 2、编解码/滤镜线程预算 4，配置已核实；8 镜头真实百炼视觉提取由串行 32.324 秒降至并行 5.340 秒，HTTP 峰值确认为 8。
- 公网 HTTP 网页与 API 无认证请求返回 200，无 HTTPS 重定向和登录挑战。
- 前端 HTTP UUID fallback：原生分支、无 `randomUUID` 分支均通过校验，生成 1000 个不同的合法 UUIDv4；生产构建通过。
- 健康检查：`provider=qwen`、`model_configured=true`、`queue_mode=celery`。
- 3 秒三镜头合成视频：预处理切出 3 个镜头，真实千问观察和全片审阅、导出作业全部 `succeeded`；失败区间为空，没有为抽象测试画面强行生成补拍建议。
- 导出下载后 FFprobe 检出 H.264 + AAC，时长约 3.02 秒；Range 请求返回 206，EDL 包含一段有效素材。
- 测试材料是合成色块，验证部署链路，不代表实拍叙事识别效果。
