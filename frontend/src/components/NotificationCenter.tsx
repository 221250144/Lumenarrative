import { useEffect, useRef, useState } from "react";
import type { Job } from "../types";
import { Icon } from "./Icon";

const jobLabels: Record<string, string> = {
  preprocess: "视频处理",
  analysis: "Vlog 分析",
  verification: "补拍分析",
  verify: "补拍分析",
  generation: "AI 片段生成",
};

export function NotificationCenter({
  jobs,
  busy,
  error,
  toast,
  isDemo,
  onDismissError,
  onRetry,
}: {
  jobs: Job[];
  busy: string;
  error: string;
  toast: string;
  isDemo: boolean;
  onDismissError: () => void;
  onRetry: (job: Job) => void;
}) {
  const [open, setOpen] = useState(false);
  const [previewError, setPreviewError] = useState(false);
  const dock = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const active = jobs.filter((job) =>
    ["queued", "running"].includes(job.status),
  );
  const failed = jobs.filter((job) => job.status === "failed");
  const count = active.length + failed.length + (error ? 1 : 0);

  useEffect(() => {
    setPreviewError(!!error);
    if (!error) return;
    const timer = setTimeout(() => setPreviewError(false), 8000);
    return () => clearTimeout(timer);
  }, [error]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !dock.current?.contains(event.target))
        setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div className="notification-dock" ref={dock}>
      {!open && error && previewError && (
        <div className="notification-toast notification-error" role="alert">
          <Icon name="alert" size={16} />
          <span>{error}</span>
          <button
            className="icon-button"
            aria-label="收起错误提示"
            onClick={() => setPreviewError(false)}
          >
            <Icon name="close" size={15} />
          </button>
        </div>
      )}
      {!open && (busy || toast) && (
        <div className="notification-toast" role="status">
          {busy ? (
            <span className="spinner" />
          ) : (
            <Icon name="check" size={16} />
          )}
          <span>{busy ? `${busy}…` : toast}</span>
        </div>
      )}
      {open && (
        <section
          className="notification-panel"
          role="dialog"
          aria-label="任务与消息"
        >
          <div className="notification-heading">
            <strong>任务与消息</strong>
            <button
              className="icon-button"
              aria-label="关闭任务与消息"
              onClick={() => {
                setOpen(false);
                trigger.current?.focus();
              }}
            >
              <Icon name="close" size={16} />
            </button>
          </div>
          <div className="notification-list">
            {error && (
              <div className="notification-item notification-error">
                <strong>操作未完成</strong>
                <p>{error}</p>
                <button className="text-button" onClick={onDismissError}>
                  清除这条提示
                </button>
              </div>
            )}
            {active.map((job) => (
              <div className="notification-item" key={job.id}>
                <strong>
                  <span className="spinner" />{" "}
                  {jobLabels[job.type] || "后台任务"}
                </strong>
                <p>{job.stage || "正在排队…"}</p>
                {job.total_units > 0 && (
                  <div className="notification-progress">
                    <progress
                      value={job.completed_units}
                      max={job.total_units}
                      aria-label={job.stage || "任务进度"}
                    />
                    <span>
                      {job.completed_units} / {job.total_units}
                    </span>
                  </div>
                )}
              </div>
            ))}
            {failed.map((job) => {
              const retryable =
                job.type !== "generation" || job.generation_retryable !== false;
              return (
                <div className="notification-item" key={job.id}>
                  <strong>{jobLabels[job.type] || "后台任务"}未完成</strong>
                  <p>{job.error_message || "任务处理失败，请重试。"}</p>
                  {retryable ? (
                    <button
                      className="small-button"
                      disabled={!!busy}
                      onClick={() => onRetry(job)}
                    >
                      <Icon name="refresh" size={13} />
                      重试任务
                    </button>
                  ) : (
                    <small>当前任务无法直接重试，请先核查上次生成结果。</small>
                  )}
                </div>
              );
            })}
            {!count && (
              <p className="notification-empty">
                {busy || "当前没有待处理的任务或错误。"}
              </p>
            )}
            {isDemo && (
              <p className="notification-note">演示项目的分析来自固定样例。</p>
            )}
          </div>
        </section>
      )}
      <button
        className="notification-trigger"
        ref={trigger}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => {
          setOpen(!open);
          setPreviewError(false);
        }}
      >
        {active.length || busy ? (
          <span className="spinner" />
        ) : (
          <Icon name={failed.length || error ? "alert" : "layers"} size={16} />
        )}
        {active.length ? `${active.length} 个任务处理中` : "任务与消息"}
        {!!count && <span className="notification-count">{count}</span>}
      </button>
    </div>
  );
}
