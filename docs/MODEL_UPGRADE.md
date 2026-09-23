# 视频理解模型更新

本文保留 2026-09-22 的模型升级与发布记录。文中的发布目录、无登录访问及 HTTP 状态码属于当时环境，不表示当前系统免登录。当前主分支已支持用户隔离并合入 HappyHorse；全新环境请按 [README](../README.md) 配置，账号行为见 [账号与项目管理](ACCOUNTS.md)。源码交付不需要连接本文中的团队服务器。

2026-09-22：主分支及由此创建的 HappyHorse 实验分支均默认使用 `qwen3.8-max` 进行采样帧理解与新素材视觉验收。全片基于证据的文字审阅仍为 `qwen-plus`。模型名变更会改变分析配置哈希，新分析重新提取证据，历史结果保留原模型来源。

已使用当前百炼业务空间真实调用 `CompatibleProvider.analyze_clip`：`qwen3.8-max` 接受图片、非流式 JSON 输出，返回一条通过 Pydantic 校验的视觉证据，约 22.35 秒。这是接口兼容性检查，不是质量或性能基准。

本地 `.env`、服务器 `/etc/xuguangji/app.env` 会覆盖代码默认值；运行环境也需将 `VLM_MODEL` 设置为 `qwen3.8-max`。保留全局 8 个理解请求名额。之前 `qwen3-vl-plus` 的加速比不适用于新模型。

服务器已发布 `3d2c520a82874aae29fcaa1a3d7e08f9a2b90ff2` 至 `/opt/xuguangji/releases/qwen38-20260922-2`，`current` 已切换，API 与 worker 均重新载入上述配置。发布包在 Linux 上通过 90 项测试；服务器以真实百炼凭据调用 `CompatibleProvider.analyze_clip`，一张蓝底黄色方块合成帧返回 1 条通过 schema 校验的证据，用时 39.467 秒。仅做接口兼容性验证，没有据此评价真实 Vlog 效果。

数据库和队列空闲后执行切换，环境及 PostgreSQL 备份位于 `/opt/xuguangji/backups/qwen38-20260922-2`；原发布目录保留以便回退。worker 进程池经 Celery inspect 确认为 8。公网 `http://47.110.79.237/`、`/api/v1/health`、`/api/v1/projects` 均返回 200，没有认证挑战或 HTTPS 跳转；服务器和用户既有媒体数据均保留。

参考：[百炼结构化输出](https://help.aliyun.com/en/model-studio/qwen-structured-output)。
