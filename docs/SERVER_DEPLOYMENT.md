# 旭光集服务器部署

部署日期：2026-09-22。服务器：`47.110.79.237`，Ubuntu 24.04、8 vCPU、28 GiB 内存。

## 当前状态

- 前端生产构建、FastAPI、PostgreSQL 16、Redis 7、Celery 和 FFmpeg 已部署。Nginx、数据库、Redis、API 和 worker 已启用开机自启。
- 当前代码版本为 `3d2c520a82874aae29fcaa1a3d7e08f9a2b90ff2`，视频采样帧理解与新素材视觉验收已切换为 `qwen3.8-max`；全片文字审阅保持 `qwen-plus`。服务器真实图片请求返回一条通过 schema 校验的证据，用时 39.467 秒；此检查不代表质量或并发性能基准。
- 服务器通过公网 HTTP 验证了新版 Vlog 切分、真实千问诊断、后台队列、MP4 导出及 HTTP Range 播放；Linux 上 90 项后端测试通过。
- 按用户要求使用 `http://47.110.79.237`，不跳转 HTTPS，不要求账号密码。公网页面、健康检查和项目接口均已通过当前电脑的系统代理返回 HTTP 200；Edge 浏览器也已实际打开页面。
- 当前电脑绕过代理的直连测试仍超时，这与浏览器实际可访问的结果不同，不能据此认定安全组未放行。若某个网络无法访问，应分别检查客户端网络路径和服务器入口。
- 数据库、Redis、后端与管理预览端口只监听回环地址。模型密钥只在受保护的服务端配置中。
- HTTPS 与证书续期未启用；仓库保留可选脚本，只有后续明确改用 HTTPS 时再执行。

## 目录与服务

|路径或服务|用途|
|---|---|
|`/opt/xuguangji/current`|指向当前发布目录的符号链接|
|`/opt/xuguangji/releases/qwen38-20260922-2`|当前应用代码及沿用的前端构建|
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

浏览器打开 `http://127.0.0.1:18080` 即可，无需登录。隧道必须保持运行；这个 localhost 地址只有建立隧道的电脑可以使用。普通使用直接访问公网 HTTP 地址即可，无需建立隧道。

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

当前使用 [8 核并发配置](CONCURRENCY.md)：`WORKER_CONCURRENCY=8`、`MODEL_CONCURRENCY=8`、`MEDIA_CONCURRENCY=2`、`FFMPEG_THREADS=4`、`MODEL_TIMEOUT_S=180`；PostgreSQL 每进程连接池为 2+2。worker 的 `CPUQuota=800%`，实测 `CPUQuotaPerSecUSec=8s`。同机所有进程必须使用同一 `DATA_DIR` 和限额设置。

并发升级前的数据库、媒体、环境配置与 worker unit 备份位于 `/opt/xuguangji/backups/parallel8-20260922`。切换前检查数据库任务以及 Redis queued/unacked 均为空；先确认 worker 已就绪，再恢复 API 入口。

`qwen3.8-max` 更新前的环境配置和 PostgreSQL 备份位于 `/opt/xuguangji/backups/qwen38-20260922-2`；本次没有数据库结构迁移或媒体改写。切换前及停 API 后，数据库 queued/running 和 Redis queued/unacked 均为 0。新 worker 就绪后实测进程池为 8；`VLM_MODEL=qwen3.8-max`、`LLM_MODEL=qwen-plus`、`MODEL_CONCURRENCY=8`，环境文件权限保持 `root:xuguangji 0640`。

```bash
systemctl status xuguangji-api xuguangji-worker nginx
journalctl -u xuguangji-api -u xuguangji-worker -n 100 --no-pager
systemctl restart xuguangji-api xuguangji-worker
systemctl list-timers xuguangji-cert-renew.timer
```

修改 `/etc/xuguangji/app.env` 后重启 API 和 worker。网页入口不使用账号密码。

代码更新使用新的 release 目录，上传源代码和 `frontend/dist`，安装 Linux 锁文件中的依赖，链接受保护的 `.env`，执行 Alembic 迁移，再切换 `current` 并重启两个服务。更新前应等正在执行的作业结束，并备份 PostgreSQL 与 `/var/lib/xuguangji/media`；回退代码不能代替数据库恢复。当前未配置异地备份或业务监控告警。

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

- Linux 后端测试：90 项通过。
- `c807e6d` 发布包的 Linux 后端测试：90 项通过（38.64 秒）；服务器真实新模型兼容性结果保存在 `/var/lib/xuguangji/media/deployment/qwen38-20260922/result.json`。
- Celery 实际进程数 8、共享模型上限 8、FFmpeg 命令上限 2、编解码/滤镜线程预算 4，配置已核实；8 镜头真实百炼视觉提取由串行 32.324 秒降至并行 5.340 秒，HTTP 峰值确认为 8。
- 公网 HTTP 网页与 API 无认证请求返回 200，无 HTTPS 重定向和登录挑战。
- 前端 HTTP UUID fallback：原生分支、无 `randomUUID` 分支均通过校验，生成 1000 个不同的合法 UUIDv4；生产构建通过。
- 健康检查：`provider=qwen`、`model_configured=true`、`queue_mode=celery`。
- 3 秒三镜头合成视频：预处理切出 3 个镜头，真实千问观察和全片审阅、导出作业全部 `succeeded`；失败区间为空，没有为抽象测试画面强行生成补拍建议。
- 导出下载后 FFprobe 检出 H.264 + AAC，时长约 3.02 秒；Range 请求返回 206，EDL 包含一段有效素材。
- 测试材料是合成色块，验证部署链路，不代表实拍叙事识别效果。
