# 旭光集服务器部署

部署日期：2026-09-22。服务器：`47.110.79.237`，Ubuntu 24.04、8 vCPU、28 GiB 内存。

## 当前状态

- 前端生产构建、FastAPI、PostgreSQL 16、Redis 7、Celery 和 FFmpeg 已部署。Nginx、数据库、Redis、API 和 worker 已启用开机自启。
- 服务器通过本地接口和 SSH 隧道验证了真实千问诊断、后台队列、MP4 导出及 HTTP Range 播放；Linux 上 17 项后端测试通过。
- 公网 TCP 80 连接超时，服务器 Nginx 正常监听且主机 INPUT 策略为 ACCEPT。需要在阿里云实例安全组放行 TCP 80、443，再完成 HTTPS 签发及外网验收；当前不宣称公网可用。
- 团队入口使用 Nginx Basic Auth。数据库、Redis、后端与管理预览端口只监听回环地址。登录密码和模型密钥不在仓库内。
- 当前可通过 SSH 隧道访问。证书申请脚本与自动续期配置已准备，尚待公网端口放行后执行。

## 目录与服务

|路径或服务|用途|
|---|---|
|`/opt/xuguangji/current`|指向当前发布目录的符号链接|
|`/opt/xuguangji/releases/c398b58-20260922`|本次应用代码及前端构建|
|`/opt/xuguangji/venv`|Python 3.12 运行环境|
|`/opt/xuguangji/certbot`|Certbot 5.8.0 独立环境|
|`/etc/xuguangji/app.env`|数据库与百炼配置，`root:xuguangji`、`0640`|
|`/etc/xuguangji/htpasswd`|网页访问密码的 bcrypt 哈希，`root:www-data`、`0640`|
|`/var/lib/xuguangji/media`|上传、采样帧、代理及导出媒体|
|`xuguangji-api.service`|FastAPI，监听 `127.0.0.1:8000`|
|`xuguangji-worker.service`|Celery，2 个 worker 进程|
|Nginx `127.0.0.1:8080`|仅用于 SSH 隧道的完整网页入口|

本次使用 systemd 原生部署；Docker Hub 在服务器上连接超时，没有运行 Docker Compose。发布包通过 SSH 上传，不在服务器保存 GitHub 登录凭据。原有本地项目数据未迁移，服务器只创建了一个明确标注的纯色视频验证项目。

## SSH 隧道访问

在存放私钥的「影石比赛」目录执行：

```bash
ssh -i _NJU_Token.pem -N \
  -L 127.0.0.1:18080:127.0.0.1:8080 \
  root@47.110.79.237
```

浏览器打开 `http://127.0.0.1:18080`，输入单独交付的团队账号密码。隧道必须保持运行；这个 localhost 地址只有建立隧道的电脑可以使用。

## 完成公网 HTTPS

1. 在阿里云 ECS 中找到该实例的安全组，允许入方向 TCP 80 和 TCP 443，来源 `0.0.0.0/0`。后端 8000、管理 8080、数据库 5432 和 Redis 6379 无需对公网开放。
2. 从服务器外访问 `http://47.110.79.237/.well-known/acme-challenge/connectivity-check`，应返回 `xuguangji-ready`。
3. 登录服务器执行：

```bash
bash /opt/xuguangji/current/deploy/enable-https.sh 47.110.79.237
```

脚本先做 Let's Encrypt 测试环境验证，再申请受信任证书；通过 Nginx 配置检查后启用 HTTPS，安装每 12 小时检查一次的续期 timer，并执行一次续期演练。HTTP 会跳转到 HTTPS，所有应用页面和接口均要求团队密码。

IP 证书需使用 `shortlived` profile，Certbot webroot 方式要求 5.4 及以上版本，参见 [Let's Encrypt 官方说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)。切勿将只有证书申请脚本准备好当作 HTTPS 已验收。

## 日常维护

```bash
systemctl status xuguangji-api xuguangji-worker nginx
journalctl -u xuguangji-api -u xuguangji-worker -n 100 --no-pager
systemctl restart xuguangji-api xuguangji-worker
systemctl list-timers xuguangji-cert-renew.timer
```

修改 `/etc/xuguangji/app.env` 后重启 API 和 worker。更换网页密码可在服务器运行 `htpasswd -B /etc/xuguangji/htpasswd xuguangji`，交互输入新密码即可，无需把密码写到命令行参数。

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

- Linux 后端测试：17 项通过。
- 网页与 API 匿名访问返回 401，带团队凭据请求成功。
- 健康检查：`provider=qwen`、`model_configured=true`、`queue_mode=celery`。
- 3 秒程序生成的纯色视频：预处理、真实千问分析、导出作业全部 `succeeded`，视觉证据标记为真实模型，失败区间为空。
- 导出下载后 FFprobe 检出 H.264 + AAC，时长约 3.02 秒；Range 请求返回 206，EDL 包含一段有效素材。
- 测试材料是合成色块，验证部署链路，不代表实拍叙事识别效果。
