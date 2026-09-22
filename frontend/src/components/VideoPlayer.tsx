import { useEffect, useRef } from "react";
import type { Asset } from "../types";
import { Icon } from "./Icon";
import { time } from "../api/client";

export function VideoPlayer({
  asset,
  seek,
}: {
  asset?: Asset;
  seek?: { at: number; nonce: number };
}) {
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const element = video.current;
    if (!element || !seek) return;
    const jump = () => {
      element.currentTime = seek.at;
      void element.play().catch(() => {});
    };
    if (element.readyState >= 1) jump();
    else {
      element.addEventListener("loadedmetadata", jump, { once: true });
      return () => element.removeEventListener("loadedmetadata", jump);
    }
  }, [seek, asset?.id]);
  return (
    <div className="player-shell">
      <div className="player-heading">
        <span>
          <i className="live-dot" /> 原片预览
        </span>
        <span className="mono">
          {asset ? `${asset.width} × ${asset.height}` : "SOURCE VIEW"}
        </span>
      </div>
      <div className="video-stage">
        {asset?.preview_url ? (
          <video
            key={asset.id}
            ref={video}
            src={asset.preview_url}
            controls
            playsInline
            preload="metadata"
            poster={asset.thumbnail_url || undefined}
          />
        ) : (
          <div className="player-empty">
            <Icon name="film" size={38} />
            <p>{asset ? "正在准备可播放的视频" : "从左侧选择一个镜头"}</p>
            <small>证据中的时间点会带你回到这里</small>
          </div>
        )}
      </div>
      <div className="player-footer">
        <div>
          <Icon name="film" />
          <span>{asset?.original_name || "等待素材"}</span>
        </div>
        <span className="mono">{asset ? time(asset.duration_s) : "00:00"}</span>
      </div>
      {asset && (
        <div className="audio-note">
          <Icon name="volume" size={14} />
          {!asset.has_audio
            ? "无音轨 · 只分析画面"
            : asset.audio_status === "analyzed"
              ? "音频已转写"
              : asset.audio_status === "failed"
                ? "音频分析失败 · 诊断会保留不确定性"
                : "音频未分析 · 尚未配置转写服务"}
          {asset.synthetic_media && <span>程序生成的演示分镜卡</span>}
        </div>
      )}
    </div>
  );
}
