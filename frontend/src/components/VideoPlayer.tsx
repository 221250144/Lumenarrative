import { useEffect, useRef } from "react";
import type { Asset } from "../types";
import { Icon } from "./Icon";
import { time } from "../api/client";
import { preciseTime } from "../lib/evidence";

export type PlaybackRange = {
  at: number;
  end?: number;
  nonce: number;
  label?: string;
};

export function VideoPlayer({
  asset,
  seek,
  onClearRange,
}: {
  asset?: Asset;
  seek?: PlaybackRange;
  onClearRange?: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const range = useRef(seek);
  range.current = seek;
  useEffect(() => {
    const element = video.current;
    if (!element || !seek) return;
    const jump = () => {
      element.currentTime = Math.max(
        0,
        Math.min(seek.at, element.duration || seek.at),
      );
      void element.play().catch(() => {});
    };
    if (element.readyState >= 1) jump();
    else {
      element.addEventListener("loadedmetadata", jump, { once: true });
      return () => element.removeEventListener("loadedmetadata", jump);
    }
  }, [seek, asset?.id]);
  useEffect(() => {
    const element = video.current;
    if (!element) return;
    let frame = 0;
    const constrain = () => {
      const current = range.current;
      if (current?.end !== undefined) {
        // Source ranges have an exclusive out point: keep the preceding frame
        // visible instead of seeking into the next shot at the cut.
        const stopAt =
          current.end - Math.min(0.025, (current.end - current.at) / 4);
        if (element.currentTime >= stopAt) {
          element.pause();
          if (element.currentTime > stopAt) element.currentTime = stopAt;
        }
      }
    };
    const tick = () => {
      constrain();
      if (!element.paused) frame = requestAnimationFrame(tick);
    };
    const start = () => {
      const current = range.current;
      if (
        current?.end !== undefined &&
        (element.currentTime >= current.end - 0.05 ||
          element.currentTime < current.at)
      )
        element.currentTime = current.at;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(tick);
    };
    element.addEventListener("play", start);
    element.addEventListener("timeupdate", constrain);
    return () => {
      cancelAnimationFrame(frame);
      element.removeEventListener("play", start);
      element.removeEventListener("timeupdate", constrain);
    };
  }, [asset?.id, asset?.preview_url]);
  return (
    <div className="player-shell">
      <div className="player-heading">
        <span>
          <i className="live-dot" />{" "}
          {seek?.end !== undefined
            ? seek.label || "关键片段回看"
            : "Vlog 原片预览"}
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
            <p>{asset ? "正在准备可播放的视频" : "上传或选择一条 Vlog"}</p>
          </div>
        )}
      </div>
      {seek?.end !== undefined && (
        <div className="playback-range" role="status">
          <span className="mono">
            {preciseTime(seek.at)} — {preciseTime(seek.end)}
          </span>
          <button
            className="small-button"
            onClick={() => {
              range.current = undefined;
              onClearRange?.();
              void video.current?.play().catch(() => {});
            }}
          >
            继续看全片
          </button>
        </div>
      )}
      <div className="player-footer">
        <div>
          <Icon name="film" />
          <span>{asset?.original_name || "等待 Vlog"}</span>
        </div>
        <span className="mono">{asset ? time(asset.duration_s) : "00:00"}</span>
      </div>
    </div>
  );
}
