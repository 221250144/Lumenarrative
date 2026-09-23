# 叙光集 · Lumenarrative

以帧补光，以叙成章。

Insta360 Think Bold 参赛项目。

面向 Vlog 创作者的 Web 应用：上传一条已经剪辑好的 Vlog，先按转场切分内部镜头，再结合全片给出最多 5 条具体补拍或重剪建议。每条建议只保留 1–2 段关键证据，说明修改位置、主体动作、景别、秒数与验收条件。

产品只提供分析和补全建议、AI 候选片段生成，以及用户上传补拍视频后的分析。不提供站内剪辑、成片版本管理或成片导出；用户下载所需的 AI 片段后，在其他剪辑软件中完成修改。重剪建议可复制。

主分支已集成自动生成补全片段：确认补拍建议后，在“补拍与重剪”任务卡选择参考首帧，使用 `happyhorse-1.1-i2v` 生成候选视频，再预览、下载并提交验收。需要在服务端启用 `VIDEO_GENERATION_ENABLED=true`，详见 [HappyHorse 视频生成](docs/HAPPYHORSE_EXPERIMENT.md)。

最新设计见 [Vlog 系统架构 v2](docs/VLOG_ARCHITECTURE.md)，本次按最新需求收窄旧任务书的通用素材流程；产品名为“叙光集”。提案和成员联系方式留在上级目录，不属于代码项目，不应随仓库公开。

## 当前可用状态

|模块|状态|
|---|---|
|React 三页工作台|项目创建/列表、Vlog 审看、补拍与重剪建议|
|账号与项目管理|注册、登录、退出、修改密码；按用户隔离项目、素材和任务；项目重命名、确认删除|
|真实视频处理|FFprobe 校验、预览转码、硬切与黑场转场候选、非重叠镜头、镜头内部最多 4 帧/窗口、音轨提取|
|结构化分析|主 Vlog 概括、章节、镜头摘要、最多 5 条定位建议与双证据；人工确认/忽略、revision 快照|
|计划与验证|每条建议对应具体补拍/重剪任务、最多两张参考帧、逐项验收；旧任务保留兼容|
|AI 视频补全|HappyHorse 首帧生成、3–15 秒候选片段、历史记录、下载及验收；不自动修改原片|
|任务与消息|后台进度及历史报错收进浮层；当前操作错误可关闭，不在页面顶部占位|
|后台任务|真实阶段与数量、SSE、断线轮询、失败重试、本地重启后显式标记中断|
|千问|已接入百炼专属业务空间；`qwen-plus` 文本分析与 `qwen3.8-max` 图片理解已通过真实调用和结构校验|
|ASR|可配置兼容 multipart `/audio/transcriptions` 的服务；未配置/失败明确显示，不编造对白；尚未验证真实服务|
|影石 SDK|`unavailable`，只提供适配接口。普通影石导出视频属于文件导入|
|PostgreSQL / Redis / Celery|已在 Ubuntu 服务器通过 systemd 部署并验证真实任务；Docker Compose 路径尚未实际启动验收|

配置模板默认 **演示数据模式**；本机 `.env` 已配置为千问真实模式。演示素材为本地程序生成的几何分镜卡，故事标签来自固定夹具，不能当成模型识别结果或准确率证据。上传、转码和原片定位仍是真实执行。普通用户视频在演示模式只返回“未进行视觉理解”，不会假装已经识别内容。切换真实模式后，不会在调用失败时退回演示数据。

## 本地启动

依赖：macOS/Linux、Python 3.12（由 uv 管理）、Node.js 22.12+ 或 24、FFmpeg 和 ffprobe。此实现已在本机 Python 3.12、Node 24、FFmpeg 9 验证。

```bash
# 从 xuguangji 目录执行
bash scripts/setup.sh
bash scripts/dev.sh
```

打开 <http://127.0.0.1:5173>；API 文档 <http://127.0.0.1:8000/docs>。

`setup.sh` 创建虚拟环境、安装锁定依赖、在不存在时复制 `.env.example` 为 `.env`，执行 Alembic 迁移并安装前端依赖。不会替换已有 `.env`。`dev.sh` 同时启动前后端，Ctrl+C 结束。仅绑定回环地址；首次使用先注册账号。已有项目的归属迁移见 [账号与项目管理](docs/ACCOUNTS.md)。

也可分别启动：

```bash
PYTHONPATH=backend .venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
# 另一个终端
npm --prefix frontend run dev
```

## Docker Compose

服务器的 systemd 部署、访问入口与维护步骤见 [服务器部署说明](docs/SERVER_DEPLOYMENT.md)。

```bash
cp .env.example .env  # 已有配置时不要覆盖
docker compose up --build
```

`migrate` 服务等待 PostgreSQL 健康后执行迁移；API 和 Celery worker 在迁移成功后启动，Redis 保存队列。Nginx 提供前端并代理 API/SSE。视频存储在共享 `media` 卷，数据库在 `postgres` 卷。访问地址仍为本地 5173，数据库和 Redis 不对宿主机暴露端口。

Compose 路径暂未实机验收；本地已验证路径使用 SQLite + 一个进程内后台线程。账号隔离覆盖 API、视频文件与任务事件；多机部署仍需调整共享限流、文件存储、任务租约和运维恢复机制。

## 目录与架构

```text
frontend/src/
  pages/          项目、审看工作台、补拍与重剪建议
  components/     视频播放器、AI 生成、任务与消息、图标
  api/            HTTP 客户端、SSE/轮询
  types/          前端数据契约
backend/app/
  api/            REST、SSE、媒体 Range 播放
  models/         SQLAlchemy 项目/素材/分析/证据/需求/匹配/缺口/计划/任务/验收/粗剪/作业
  schemas/        Pydantic 输入与模型输出验证
  providers/      千问兼容协议、演示夹具、ASR、存储、素材源适配
  services/       媒体预处理、诊断、规划、渲染
  workflows/      分析快照、增量复用、验收与渲染调度
  workers/        本地队列 / Celery
backend/migrations/  Alembic 冻结的初始迁移
backend/tests/       规则、媒体链路、版本隔离、Provider 协议测试
scripts/             安装、开发、检查
demo/                场景说明与演示步骤
docs/                实施边界与验证记录
```

所有媒体时间采用原片相对秒 `[start, end)`。代理视频不改变速度，并检查时长偏差；通过 FFmpeg 时间戳处理可变帧率。镜头边界和模型时间范围是候选，不宣称帧级精确。缺口记录已搜索/失败范围，音频未分析时不会据画面断言对白不存在。

后台任务创建时固定项目 revision、素材快照和 provider/模型/提示词/采样配置。旧任务完成只保留为历史版本。新增素材的证据可复用，需求和匹配重新计算。配置变化后旧分析任务不能跨模式重试，需发起新分析。用户确认与忽略通过独立修正层保留，后续模型分析不会覆盖。

## 模型配置

只修改本地 `.env`，不要把密钥放进前端、README 或提交到 Git：

```dotenv
MODEL_PROVIDER=qwen
MODEL_BASE_URL=https://你的WorkspaceId.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
MODEL_API_KEY=你的本地密钥
VLM_MODEL=qwen3.8-max
LLM_MODEL=qwen-plus
```

重启 API；Compose 下也需重启 worker。页面显示真实模型/演示模式，不显示密钥。创建分析、验收或视频生成任务时，会将对应的采样帧、参考首帧及文本发送至配置的模型服务。

接口采用千问官方 [Chat Completions 兼容协议](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)，通过 Base64 图片与源时间标签传入画面。专属域名按控制台完整复制，`WorkspaceId`、地域和密钥须对应；其他部署请使用自己账号提供的地址。上述两个模型已在本机真实调用通过，其他账号仍需确认模型权限与可用额度。

本地依赖包含 `httpx[socks]`，支持本机配置的 SOCKS 代理。环境变量中的代理设置由 HTTP 客户端读取，不需要把代理地址写进源码。

`MODEL_TIMEOUT_S` 默认 900 秒，控制单次模型响应读取等待；设为 `0` 可关闭读取等待限制。连接、上传与连接池分别保持 30/60/30 秒，整条后台分析没有该总时长限制。`MODEL_CONCURRENCY` 默认 8。同一 Vlog 的镜头并行理解，所有进程共享最多 8 个模型请求；视频处理最多 2 个 FFmpeg 同时运行，编解码与滤镜各设 4 线程预算。详见 [8 核并发设计](docs/CONCURRENCY.md)。限流/暂时性 HTTP 错误最多尝试 3 次，退避 1/2 秒。JSON schema 错误最多修复一次，仍失败则报错。日志仅记录模型名、耗时、输入帧数、输出状态和可用 token 用量，不写密钥或完整私有帧。

可选 ASR：`ASR_BASE_URL`、`ASR_API_KEY`、`ASR_MODEL`。只支持返回带时间戳 `segments` 的兼容服务，不推断千问任意 ASR 型号都适用这一协议。无音轨直接跳过，未配置或失败保留状态。音频提取结果保留在本地素材目录。

## 使用流程

1. 创建 Vlog 项目，填写拍摄内容与想表达的重点；上传一条已经剪辑过的完整 Vlog。首次上传自动作为主片。
2. 等待预处理完成，在工作台按镜头查看缩略图和原片时间范围。每页默认展示 10 个镜头，点击后播放对应片段。
3. 点击分析，查看实际内容摘要、段落与最多 5 条值得改的意见。每条展开最多两段关键依据，明确“哪段画面、缺什么信息、怎么改”。音频或画面未完整分析时会提示不确定。
4. 人工确认或忽略意见。在补拍任务页查看具体动作、景别、秒数、插入位置和验收条件；未确认意见不自动选入执行计划。
5. 上传补充片段，或在已确认的补拍任务中展开“AI 生成补全片段”，选择首帧、调整描述与时长后生成。生成使用百炼额度，结果可预览、下载并提交验收。新增素材不会自动代替主 Vlog 或混入主片分析；验收通过后仍需要将它实际剪进视频。
6. 根据重剪建议，在其他剪辑软件中调整镜头；下载需要的 AI 候选片段，与实拍补充素材一起剪入成片。叙光集不管理剪辑版本或导出成片。
7. 旧项目可明确选择一个主 Vlog 后转换并重新分析，旧诊断保留为历史版本。

当前限制：每项目最多 20 个文件、总时长 600 秒、单文件 256 MB；支持可解码的 MP4、MOV、WebM、MKV、AVI。

支持 FFmpeg 默认编解码器；暂不直接解析 INSV/INSP 等专有容器。全景素材需先导出普通视角视频，来源标记为 `insta360_export`。

## 环境变量

完整变量见 `.env.example`。本地常用配置：

|变量|默认|用途|
|---|---|---|
|`DATABASE_URL`|`sqlite:///./data/xuguangji.db`|本地数据库；Compose 使用 PostgreSQL|
|`DATA_DIR`|`./data`|素材、代理、关键帧和导出目录|
|`QUEUE_MODE`|`local`|`local` 或 `celery`|
|`REDIS_URL`|`redis://localhost:6379/0`|Celery broker|
|`MODEL_PROVIDER`|`mock`|`mock`、`qwen`、`compatible`|
|`WINDOW_S` / `OVERLAP_S`|8 / 2|分析窗口与重叠秒数|
|`SAMPLE_FPS`|1|旧版兼容配置；Vlog 流程按镜头内每窗口最多 4 帧抽样|
|`FFMPEG_BIN` / `FFPROBE_BIN`|命令名|可指定安装位置|

## 检查

```bash
bash scripts/check.sh
# 分别执行
PYTHONPATH=backend .venv/bin/pytest backend/tests -q
npm --prefix frontend run build
```

测试在独立临时数据库与媒体目录执行，不操作工作区用户素材。真实媒体测试使用 FFmpeg 生成测试视频，检查预处理及素材 Range 下载；模型语义使用明确标注的夹具，不能替代真实模型效果评估。剪辑退役测试检查旧入口返回 410、禁止重试渲染，且历史数据库与文件保持不变。Provider 协议测试使用 HTTP 模拟响应。真实账号接入测试与自动化测试分开执行，详情见 `docs/VERIFICATION.md`。

## 当前限制

- 千问真实调用已打通；尚无实拍标注评测集与影石 SDK，因此不宣称叙事识别准确率或设备接入成功。纯色测试仅验证接入和处理链路。
- Vlog 使用按镜头抽样及全片上下文审阅；复杂叠化可能漏检，快速运动或闪光可能误分，关键帧可能遗漏动作。多段分析失败保留覆盖记录，相关结论需要人工复核。
- 计划采用可解释的固定候选与人工时间估计。已有素材补入在未证明有可用素材时不自动推荐；外部生成工具可用性需要创作者核实。首版未实现模型生成的复杂多任务依赖求解和成本自定义。
- 人工修正覆盖意见确认/忽略；手动分镜合并/拆分、证据事实逐条改写尚未实现。
- 剪辑、成片版本管理及成片导出已从产品移除，对应旧接口返回 410；历史表和媒体文件保留，AI 候选素材的预览与下载正常提供。没有专业剪辑轨道、字幕编辑或远程拍摄控制。
- 应用本身仍是共享工作区原型；服务器按团队要求使用 HTTP 免登录入口，尚无独立成员账号与权限隔离。Docker 组合及 Redis/Celery 中断恢复尚需目标环境验证。
- 行业调研、问卷、PPT、1 分钟路演视频和公开仓库发布属于后续比赛材料，本次未生成或上传。
