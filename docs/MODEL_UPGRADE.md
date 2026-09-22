# 视频理解模型更新

2026-09-22：主分支及由此创建的 HappyHorse 实验分支均默认使用 `qwen3.8-max` 进行采样帧理解与新素材视觉验收。全片基于证据的文字审阅仍为 `qwen-plus`。模型名变更会改变分析配置哈希，新分析重新提取证据，历史结果保留原模型来源。

已使用当前百炼业务空间真实调用 `CompatibleProvider.analyze_clip`：`qwen3.8-max` 接受图片、非流式 JSON 输出，返回一条通过 Pydantic 校验的视觉证据，约 22.35 秒。这是接口兼容性检查，不是质量或性能基准。

本地 `.env`、服务器 `/etc/xuguangji/app.env` 会覆盖代码默认值；运行环境也需将 `VLM_MODEL` 设置为 `qwen3.8-max`。保留全局 8 个理解请求名额。之前 `qwen3-vl-plus` 的加速比不适用于新模型。

参考：[百炼结构化输出](https://help.aliyun.com/en/model-studio/qwen-structured-output)。
