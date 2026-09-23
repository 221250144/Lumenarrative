# 叙光集 · Lumenarrative

**以帧补光，以叙成章。**

NJU人型token队 · 赛道一：AI + 影像产品开发

叙光集是面向 Vlog 创作者的镜头诊断与补拍助手。输入是一条**已经剪好的 Vlog**，可以包含实拍或 AI 生成的画面。系统检测转场、拆分镜头，结合全片内容给出最多 5 条具体的补拍或重剪建议，并将建议绑定到原片时间段与关键证据。

确认建议后，用户可以上传补拍片段进行复核，也可以生成、预览并下载 AI 候选片段。**重剪仅提出建议；应用不提供时间线剪辑、成片版本管理或最终成片导出。** 最终修改由用户在其他剪辑软件中完成。

首次运行或使用参赛源码包，请先阅读 [提交与运行说明](docs/SUBMISSION.md)。代码仓库与内部服务名沿用 `xuguangji`，中文产品名为“叙光集”；将目录命名为 `赛道一_NJU人型token队_叙光集` 不影响运行。

## 功能与边界

|模块|当前实现|
|---|---|
|账号与项目管理|注册、登录、退出、修改密码；按用户隔离项目及其素材、分析、任务和生成记录；支持项目搜索、重命名与确认删除|
|视频预处理|FFprobe 校验、预览转码、转场候选检测、短于 0.5 秒的镜头与相邻镜头合并、关键帧抽取、音轨提取|
|Vlog 审看|主片概括、章节、镜头摘要、最多 5 条建议；每条最多 2 段关键证据；按原片时间回看、人工确认或忽略|
|补拍与重剪建议|给出建议动作、景别、时长、位置和验收条件；重剪建议可复制，供外部剪辑软件使用|
|AI 候选片段|`happyhorse-1.1-i2v` 首帧图生视频；已合并至 `main`，支持生成记录、预览、下载和提交复核|
|补充片段复核|用户上传实拍或 AI 生成片段，按原补拍任务逐项分析，保留通过、部分满足、不确定或未满足等结果|
|后台任务|阶段进度、SSE 与断线轮询、失败信息及重试；任务与消息集中在浮层中|

“生成成功”不等于“符合补拍要求”，复核通过也不会自动将片段剪入原片。内部分析快照用于结果追溯，不是成片版本管理功能。

项目删除为软删除：项目入口立即不可访问，底层记录及媒体保留，不保证释放磁盘。有排队或执行中的任务时需等待结束再删除。账号隔离与迁移说明见 [账号与项目管理](docs/ACCOUNTS.md)。

## 本地快速开始

需要安装 **uv、Python 3.12、Node.js 22.12+（推荐使用 Node.js 24 运行附带测试）、npm、FFmpeg 和 ffprobe**。Python 可由 uv 创建环境时安装。源码包不包含 `.venv`、`node_modules` 等依赖目录，首次安装需要联网下载依赖。

### macOS

在仓库根目录执行：

```bash
bash scripts/setup.sh
bash scripts/dev.sh
```

`setup.sh` 创建 `.venv`、安装锁定依赖、在 `.env` 不存在时复制模板、执行数据库迁移并安装前端依赖；不会覆盖已有 `.env`。FFmpeg 未安装时可使用 `brew install ffmpeg`。

### Linux

使用 Linux 专用依赖锁文件；先安装系统的 FFmpeg、uv 和 Node.js，再在仓库根目录执行：

```bash
uv venv --python 3.12 .venv
uv pip sync backend/requirements-linux.lock --python .venv/bin/python
test -f .env || cp .env.example .env
PYTHONPATH=backend .venv/bin/alembic -c backend/alembic.ini upgrade head
npm --prefix frontend ci
bash scripts/dev.sh
```

打开 [本地应用](http://127.0.0.1:5173)，首次使用在登录页**自行注册账号**。全新安装没有预置账号、密码或已有项目。API 文档为 <http://127.0.0.1:8000/docs>，健康检查为 <http://127.0.0.1:8000/api/v1/health>。`Ctrl+C` 停止开发服务。

本地默认使用 SQLite 和进程内后台队列，无需额外安装 PostgreSQL、Redis 或 Celery 服务。前后端仅监听本机回环地址；数据写入被 Git 忽略的 `data/`。Windows 原生环境未验收，可在具备上述依赖的 Linux/WSL 环境中按 Linux 步骤运行。

## 演示模式与真实模型

`.env.example` 默认 `MODEL_PROVIDER=mock`，不含任何模型密钥。该模式可以体验账号、项目、视频上传、预处理和固定演示流程，不调用付费模型。首页的“体验演示项目”与场景按钮使用程序生成的几何分镜卡及固定标注，不能作为模型识别准确率证据。普通上传视频在该模式下不会获得真实视觉理解结论。

要分析自己的 Vlog，在本地 `.env` 中配置有权限的模型服务，然后重启 API；使用 Celery 时也要重启 worker：

```dotenv
MODEL_PROVIDER=qwen
# 使用自己账号控制台提供的完整兼容接口地址。
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_API_KEY=填入你自己的密钥
VLM_MODEL=qwen3.8-max
LLM_MODEL=qwen-plus
```

使用百炼专属业务空间时，应将 `MODEL_BASE_URL` 替换为对应地域和业务空间的完整地址；模型名称、权限、额度及地域需与自己的账号匹配。应用接入的是 Chat Completions 兼容协议，以采样帧和文本执行视频理解，真实调用失败会显示错误，不会静默切回演示结果。密钥仅保存在后端环境中，不要写入前端或提交到 Git。

### AI 视频生成

```dotenv
VIDEO_GENERATION_ENABLED=true
VIDEO_GENERATION_MODEL=happyhorse-1.1-i2v
# 留空时由 MODEL_BASE_URL 的 /compatible-mode/v1 推导同空间 /api/v1。
VIDEO_GENERATION_BASE_URL=
```

模板中的生成开关默认开启，但 **mock 模式或未配置真实密钥时仍不可生成**。真实生成还需要百炼模型权限与额度、有效的已确认补拍任务、来源可追溯的参考首帧，以及未过期的分析和补全计划。重剪任务不支持生成；不符合条件时页面会说明原因。

支持请求 3–15 秒、480P/720P/1080P 的候选片段；生成与分析会使用外部模型服务额度。当前为单首帧生成，不能保证片段结尾与后一镜头自然衔接。详见 [HappyHorse 视频生成](docs/HAPPYHORSE_EXPERIMENT.md)。

### 可选音频识别

`ASR_BASE_URL`、`ASR_API_KEY`、`ASR_MODEL` 用于兼容 multipart `/audio/transcriptions`、并返回带时间戳 `segments` 的服务。默认未配置 ASR，音轨提取不代表已完成对白或音乐理解；音频未分析时不能据此断言原片没有对白或音乐。真实 ASR 服务尚未完成接入验收。

## 推荐体验流程

1. 注册并登录，创建 Vlog 项目，填写名称、审看重点和风格。
2. 上传一条已剪好的完整 Vlog。等待预处理，检查镜头列表、时间范围与回放。
3. 在真实模型环境中发起分析，查看建议并点击关键证据回看原片；结合创作意图确认或忽略建议。
4. 生成补拍与重剪清单。对重剪任务复制建议，在外部剪辑软件中操作。
5. 对补拍任务上传补充视频，或选择参考首帧生成 AI 候选，再提交复核。
6. 阅读逐项复核结果，下载需要的 AI 片段，在外部软件中完成最终剪辑。

新增补充素材不会自动替换主片。更换主 Vlog、修改创作需求或已有更新分析后，应使用匹配的新分析和清单。新建 AI 生成任务要求模型配置与原分析一致；补拍复核可按当前模型重新理解补充片段，单纯升级真实模型或提示词不必重建原任务，主片、需求和最新分析等关联校验仍然生效。

默认容量：每项目最多 20 个文件、累计 600 秒、单文件 256 MB；支持 FFmpeg 可解码的 MP4、MOV、WebM、MKV、AVI。影石素材需要先导出普通视角视频，不直接解析 INSV/INSP，未接入影石 SDK。

## 技术结构

前端使用 React、TypeScript、Vite；后端使用 FastAPI、Pydantic、SQLAlchemy、Alembic；视频处理由 FFmpeg/ffprobe 完成。真实模型将视觉理解与全片文字审阅分开，默认配置分别为 `qwen3.8-max` 和 `qwen-plus`。

```text
frontend/src/            项目、审看、补拍任务及账号界面
frontend/tests/          前端结果状态回归测试
backend/app/api/         REST、SSE、媒体访问及生成接口
backend/app/providers/   模型、ASR、存储及素材源适配
backend/app/services/    媒体处理、诊断、规划、复核及生成
backend/app/workflows/   后台工作流与结果快照
backend/app/workers/     本地队列与 Celery 入口
backend/migrations/     数据库迁移
backend/tests/          账号隔离、媒体链路、结构校验及工作流测试
scripts/                安装、开发、检查工具
demo/                   固定演示案例说明
docs/                   提交说明、架构、账号与验证记录
```

媒体时间以原片相对秒 `[start, end)` 表示。镜头边界是检测候选，不保证帧级精确；显示时间保留到小数点后一位，内部计算仍保存精度。旧剪辑实现与历史表仅用于兼容和退役验证，当前产品不开放成片剪辑/导出入口。

### 常用配置

|变量|默认值|用途|
|---|---|---|
|`DATABASE_URL`|`sqlite:///./data/xuguangji.db`|本地数据库|
|`DATA_DIR`|`./data`|原片、代理、关键帧及生成素材|
|`QUEUE_MODE`|`local`|本地队列；可选 `celery`|
|`MODEL_PROVIDER`|`mock`|演示模式；真实接入可选 `qwen`/`compatible`|
|`MODEL_CONCURRENCY`|8|同一部署共享的模型并发槽位上限|
|`MODEL_TIMEOUT_S`|900|单次模型响应读取等待；`0` 关闭此读取限制|
|`MEDIA_CONCURRENCY` / `FFMPEG_THREADS`|2 / 4|并行媒体命令数与每条命令线程预算|
|`VIDEO_GENERATION_CONCURRENCY`|1|独立的视频生成并发上限|
|`AUTH_SESSION_DAYS`|14|账号会话有效期|
|`AUTH_COOKIE_SECURE`|false|本地 HTTP 配置；HTTPS 部署时设为 true|

900 秒不是整个分析流程的总时长限制；连接、上传等仍有独立超时。并发数可按本机资源和模型服务限流调整，8 路请求不代表所有设备都能获得相同加速。完整配置见 [.env.example](.env.example)，设计见 [并发说明](docs/CONCURRENCY.md)。

## 检查与测试

安装依赖后在仓库根目录执行：

```bash
# 后端测试 + TypeScript 检查与前端构建
bash scripts/check.sh

# 前端补拍复核状态测试（Node.js 24）
node --test frontend/tests/verification.test.ts
```

后端测试使用独立临时数据库与媒体目录；真实媒体测试用 FFmpeg 生成测试视频，模型协议测试使用模拟响应。自动化测试通过不代表模型建议全部正确，也不等于已完成所有浏览器、真实 ASR 或大规模用户验收。历史验证记录见 [VERIFICATION.md](docs/VERIFICATION.md)，其中旧版本的剪辑、导出及免登录行为不属于当前产品。

## 可选部署与已知限制

仓库提供 [Docker Compose](docker-compose.yml) 和 [服务器部署说明](docs/SERVER_DEPLOYMENT.md)。Compose 包括 PostgreSQL、Redis、迁移、API、worker 与 Web，**该路径尚未完成容器实机验收**；首次评审建议使用上述本地流程。部署文档用于参考，不是运行源码包的必做步骤。

- 转场检测与关键帧抽样可能漏掉快速动作、复杂叠化或细小文字；模型也可能混淆字幕与场景内容、推断未呈现的事件。建议及时间边界仍需回看核实。
- 没有实拍标注评测集，因此不宣称叙事识别准确率。AI 生成画面是创作候选，不能证明真实到访或事件发生。
- 未实现手动分镜拆合、逐条改写证据、专业剪辑轨道、字幕编辑、相机遥控或影石 SDK 接入。
- 用户管理为基础账号隔离；没有邮箱找回密码、角色权限管理或企业级身份体系。多 API 实例需进一步完善共享限流、存储及恢复机制。
- 真实模型依赖网络、账号权限与额度；生成提交状态不明确时可能阻止重新提交，以避免重复计费。

进一步阅读：[提交说明](docs/SUBMISSION.md) · [系统架构](docs/VLOG_ARCHITECTURE.md) · [账号与项目管理](docs/ACCOUNTS.md) · [AI 生成](docs/HAPPYHORSE_EXPERIMENT.md)
