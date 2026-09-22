# 旭光集 · Lumenarrative

以帧补光，以叙成章。

Insta360 Think Bold 参赛项目。

面向短视频创作者的本地 Web 原型：输入创作意图，上传素材或剪辑初稿，查看带原片时间点的证据与叙事缺口，规划重剪、补拍或外部 AI 生成，上传新素材验证，再导出基础粗剪。

根据上级目录的《叙全-Agent编码实施任务书.md》实施；产品名以用户最新指示“旭光集”为准。提案和成员联系方式留在上级目录，不属于代码项目，不应随仓库公开。

## 当前可用状态

|模块|状态|
|---|---|
|React 四页工作台|项目创建/列表、叙事工作台、补全任务、粗剪对比|
|真实视频处理|FFprobe 校验、流式落盘、预览转码、镜头变化检测、重叠窗口、带源时间的采样帧、音轨提取|
|结构化分析|需求、证据、匹配、缺口、人工确认/忽略、需求修正；结果绑定项目 revision|
|计划与验证|现有素材修复优先、预算去重、外部生成提示词与参考帧、逐项验收、重新匹配原需求|
|粗剪|EDL 校验、顺序/入出点编辑、FFmpeg 直切 MP4、无音轨补静音、历史版本对比|
|后台任务|真实阶段与数量、SSE、断线轮询、失败重试、本地重启后显式标记中断|
|千问|已接入百炼专属业务空间；`qwen-plus` 文本分析与 `qwen3-vl-plus` 图片理解已通过真实调用和结构校验|
|ASR|可配置兼容 multipart `/audio/transcriptions` 的服务；未配置/失败明确显示，不编造对白；尚未验证真实服务|
|影石 SDK|`unavailable`，只提供适配接口。普通影石导出视频属于文件导入|
|PostgreSQL / Redis / Celery|已在 Ubuntu 服务器通过 systemd 部署并验证真实任务；Docker Compose 路径尚未实际启动验收|

配置模板默认 **演示数据模式**；本机 `.env` 已配置为千问真实模式。演示素材为本地程序生成的几何分镜卡，故事标签来自固定夹具，不能当成模型识别结果或准确率证据。上传、转码、原片定位和 MP4 导出仍是真实执行。普通用户视频在演示模式只返回“未进行视觉理解”，不会假装已经识别内容。切换真实模式后，不会在调用失败时退回演示数据。

## 本地启动

依赖：macOS/Linux、Python 3.12（由 uv 管理）、Node.js 22.12+ 或 24、FFmpeg 和 ffprobe。此实现已在本机 Python 3.12、Node 24、FFmpeg 9 验证。

```bash
# 从 xuguangji 目录执行
bash scripts/setup.sh
bash scripts/dev.sh
```

打开 <http://127.0.0.1:5173>；API 文档 <http://127.0.0.1:8000/docs>。

`setup.sh` 创建虚拟环境、安装锁定依赖、在不存在时复制 `.env.example` 为 `.env`，执行 Alembic 迁移并安装前端依赖。不会替换已有 `.env`。`dev.sh` 同时启动前后端，Ctrl+C 结束。仅绑定回环地址；默认本地单用户。

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

Compose 路径暂未实机验收；本地已验证路径使用 SQLite + 一个进程内后台线程。不能把本地队列当成多进程分布式队列；正式多人部署需额外的认证、访问控制、任务租约和运维恢复机制。

## 目录与架构

```text
frontend/src/
  pages/          项目、工作台、任务、对比
  components/     视频播放器、图标
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
VLM_MODEL=qwen3-vl-plus
LLM_MODEL=qwen-plus
```

重启 API；Compose 下也需重启 worker。页面“运行与接入状态”显示配置目的地与模式，不显示密钥。真实模式会将采样帧及文本发送至配置的模型服务；只有你创建分析/验证任务时才调用。

接口采用千问官方 [Chat Completions 兼容协议](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)，通过 Base64 图片与源时间标签传入画面。专属域名按控制台完整复制，`WorkspaceId`、地域和密钥须对应；其他部署请使用自己账号提供的地址。上述两个模型已在本机真实调用通过，其他账号仍需确认模型权限与可用额度。

本地依赖包含 `httpx[socks]`，支持本机配置的 SOCKS 代理。环境变量中的代理设置由 HTTP 客户端读取，不需要把代理地址写进源码。

`MODEL_TIMEOUT_S` 默认 90 秒，`MODEL_CONCURRENCY` 默认 2（每个 worker 进程）。限流/暂时性 HTTP 错误最多尝试 3 次，退避 1/2 秒。JSON schema 错误最多修复一次，仍失败则报错。日志仅记录模型名、耗时、输入帧数、输出状态和可用 token 用量，不写密钥或完整私有帧。

可选 ASR：`ASR_BASE_URL`、`ASR_API_KEY`、`ASR_MODEL`。只支持返回带时间戳 `segments` 的兼容服务，不推断千问任意 ASR 型号都适用这一协议。无音轨直接跳过，未配置或失败保留状态。音频提取结果保留在本地素材目录。

## 使用流程

1. 创建项目，描述观众需要知道的内容，选择独立素材/剪辑初稿/混合输入及目标时长。混合输入需要指定主初稿。
2. 上传视频，选择来源类型。等待预处理完成，可播放预览视频。首次上限为 20 个视频、总时长 600 秒、单文件 256 MB；支持可解码的 MP4、MOV、WebM、MKV、AVI。
3. 点击“开始叙事诊断”。查看素材证据，点击时间点跳转；检查创作需求，修改或确认后重新分析。模型建议与用户明确要求区分记录。
4. 核实缺口，选择“确实需要修改”或“忽略”，可保留人工原因。未确认和不确定问题不会自动进入必要计划。
5. 在“补全与修改”设置人工时间预算，比较重剪、已有素材补入、补拍与外部生成方案。参考帧可打开保存；生成仅提供提示词，不在应用内自动生成视频。
6. 上传补充片段并验证，或关联已上传的新素材。显示逐项检查和新证据。失败/不确定不会关闭缺口；通过仅代表对应任务与需求通过，仍需重新诊断全局。
7. 在“粗剪与对比”生成 MP4 和 EDL JSON；也可调整顺序及入出点。未通过验收的任务提交不会自动进入粗剪，手动时间线仍以用户选择为准。已烘焙的字幕/音乐不能恢复为原始工程。

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
|`SAMPLE_FPS`|1|稀疏采样；高优先级候选缺口局部复核使用 4 fps|
|`FFMPEG_BIN` / `FFPROBE_BIN`|命令名|可指定安装位置|

## 检查

```bash
bash scripts/check.sh
# 分别执行
PYTHONPATH=backend .venv/bin/pytest backend/tests -q
npm --prefix frontend run build
```

测试在独立临时数据库与媒体目录执行，不操作工作区用户素材。真实媒体测试使用 FFmpeg 生成测试视频，上传后探测导出的实际 MP4；模型语义使用明确标注的夹具，不能替代真实模型效果评估。Provider 协议测试使用 HTTP 模拟响应。真实账号接入测试与自动化测试分开执行，详情见 `docs/VERIFICATION.md`。

## 当前限制

- 千问真实调用已打通；尚无实拍标注评测集与影石 SDK，因此不宣称叙事识别准确率或设备接入成功。纯色测试仅验证接入和处理链路。
- 加密复核目前只覆盖前两个素材的前两个窗口，检索覆盖会记录；不是对整片所有动作的完整复核。多段分析失败仍会保留部分覆盖，并将相关结论列为复核。
- 计划采用可解释的固定候选与人工时间估计。已有素材补入在未证明有可用素材时不自动推荐；外部生成工具可用性需要创作者核实。首版未实现模型生成的复杂多任务依赖求解和成本自定义。
- 人工修正已覆盖创作需求及缺口状态；证据事实的逐条人工改写界面尚未实现。
- 粗剪只做直切和基础编排，默认不加音乐；未实现专业剪辑轨道、自动字幕渲染、自动视频生成与远程拍摄控制。
- 应用本身仍是单用户原型；服务器通过 Nginx 团队密码保护入口，尚无独立成员账号与权限隔离。Docker 组合及 Redis/Celery 中断恢复尚需目标环境验证。
- 行业调研、问卷、PPT、1 分钟路演视频和公开仓库发布属于后续比赛材料，本次未生成或上传。
