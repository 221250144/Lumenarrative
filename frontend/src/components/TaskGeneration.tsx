import { useEffect, useRef, useState } from "react";
import { api, post, watchJob } from "../api/client";
import { createIdempotencyKey } from "../api/idempotency";
import { preciseTime } from "../lib/evidence";
import { verificationPresentation } from "../lib/verification";
import type { Asset, GenerationOptions, Job, Task } from "../types";
import { Icon } from "./Icon";

const active = (job: Job) => ["queued", "running"].includes(job.status);

export function TaskGeneration({
  task,
  assets,
  liveJobs,
  busy,
  onRefresh,
  onSubmit,
}: {
  task: Task;
  assets: Asset[];
  liveJobs: Job[];
  busy: boolean;
  onRefresh: () => Promise<void>;
  onSubmit: (taskId: string, assetId: string) => void;
}) {
  const [options, setOptions] = useState<GenerationOptions | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState(5);
  const [resolution, setResolution] =
    useState<GenerationOptions["resolution"]>("720P");
  const [frameIndex, setFrameIndex] = useState(0);
  const [selectedResult, setSelectedResult] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const submitLock = useRef(false);
  const alive = useRef(true);
  const refreshRef = useRef(onRefresh);
  refreshRef.current = onRefresh;
  const endpoint = `/completion-tasks/${task.id}`;
  const pendingIntent = useRef<{ fingerprint: string; key: string } | null>(
    null,
  );

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    void Promise.all([
      api<GenerationOptions>(`${endpoint}/generation-options`),
      api<Job[]>(`${endpoint}/generations`),
    ])
      .then(([config, history]) => {
        if (!mounted) return;
        const latest = history[0] || config.latest_job;
        setOptions(config);
        setPrompt(latest?.prompt || config.prompt);
        setDuration(
          Math.max(
            3,
            Math.min(
              15,
              Math.round(latest?.duration_s || config.duration_s || 5),
            ),
          ),
        );
        setResolution(latest?.resolution || config.resolution || "720P");
        setFrameIndex(
          Math.max(
            0,
            config.reference_frames.findIndex(
              (frame) =>
                frame.asset_id === latest?.reference_asset_id &&
                frame.time_s === latest?.reference_time_s,
            ),
          ),
        );
        setJobs(
          history.length
            ? history
            : config.latest_job
              ? [config.latest_job]
              : [],
        );
        setOpen(history.length > 0 || !!config.latest_job);
      })
      .catch((e: Error) => {
        if (mounted) setError(e.message);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [endpoint]);

  useEffect(() => {
    // Also follow retries started from the app's shared failed-job list.
    const relevant = liveJobs.filter(
      (job) => job.type === "generation" && job.task_id === task.id,
    );
    if (!relevant.length) return;
    setJobs((current) => {
      const updates = new Map(relevant.map((job) => [job.id, job]));
      return [
        ...relevant.filter(
          (job) => !current.some((item) => item.id === job.id),
        ),
        ...current.map((job) =>
          updates.has(job.id) ? { ...job, ...updates.get(job.id) } : job,
        ),
      ];
    });
  }, [liveJobs, task.id]);

  const pendingIds = jobs
    .filter(active)
    .map((job) => job.id)
    .join(",");
  useEffect(() => {
    if (!pendingIds) return;
    let mounted = true;
    const stops = pendingIds.split(",").map((id) =>
      watchJob(id, (job) => {
        if (!mounted) return;
        setJobs((current) =>
          current.map((item) => (item.id === job.id ? job : item)),
        );
        if (!active(job)) {
          void refreshRef.current().catch((e: Error) => {
            if (alive.current) setError(e.message);
          });
          void api<GenerationOptions>(`${endpoint}/generation-options`)
            .then((config) => {
              if (alive.current) setOptions(config);
            })
            .catch(() => {});
        }
      }),
    );
    return () => {
      mounted = false;
      stops.forEach((stop) => stop());
    };
  }, [pendingIds, endpoint]);

  async function reload() {
    if (!alive.current) throw new DOMException("会话已关闭", "AbortError");
    const [config, history] = await Promise.all([
      api<GenerationOptions>(`${endpoint}/generation-options`),
      api<Job[]>(`${endpoint}/generations`),
    ]);
    if (!alive.current) throw new DOMException("会话已关闭", "AbortError");
    setOptions(config);
    setJobs(history);
    return config;
  }

  async function generate() {
    const frame = options?.reference_frames[frameIndex];
    if (submitLock.current || !frame || !options?.available || pendingIds)
      return;
    submitLock.current = true;
    setSubmitting(true);
    setError("");
    try {
      const body = {
        prompt: prompt.trim(),
        duration_s: duration,
        resolution,
        reference_asset_id: frame.asset_id,
        reference_time_s: frame.time_s,
      };
      const fingerprint = JSON.stringify(body);
      const storageKey = `xuguangji.generation.${task.id}`;
      // Keep a submission key across transport failures and page refreshes so
      // retrying the same paid request cannot submit a second generation.
      let intent = pendingIntent.current;
      try {
        const saved = sessionStorage.getItem(storageKey);
        if (saved) intent = JSON.parse(saved);
      } catch {
        /* The in-memory key still protects retries if storage is blocked. */
      }
      if (!intent || intent.fingerprint !== fingerprint || !intent.key) {
        intent = { fingerprint, key: createIdempotencyKey() };
      }
      pendingIntent.current = intent;
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(intent));
      } catch {
        /* Optional persistence. */
      }
      const result = await post<{ job_id: string }>(
        `${endpoint}/generations`,
        body,
        intent.key,
      );
      if (!alive.current) return;
      const job = await api<Job>(`/jobs/${result.job_id}`);
      if (!alive.current) return;
      pendingIntent.current = null;
      try {
        sessionStorage.removeItem(storageKey);
      } catch {
        /* Optional persistence. */
      }
      setJobs((current) => [
        job,
        ...current.filter((item) => item.id !== job.id),
      ]);
      setSelectedResult("");
      await refreshRef.current();
    } catch (e) {
      if (!alive.current) return;
      setError(e instanceof Error ? e.message : "提交生成任务失败");
      await reload().catch(() => {});
    } finally {
      submitLock.current = false;
      setSubmitting(false);
    }
  }

  async function retry(job: Job) {
    if (submitLock.current || job.generation_retryable === false) return;
    submitLock.current = true;
    setSubmitting(true);
    setError("");
    try {
      await post(`/jobs/${job.id}/retry`);
      if (!alive.current) return;
      await reload();
      if (!alive.current) return;
      await refreshRef.current();
    } catch (e) {
      if (!alive.current) return;
      setError(e instanceof Error ? e.message : "重试生成任务失败");
      await reload().catch(() => {});
    } finally {
      submitLock.current = false;
      setSubmitting(false);
    }
  }

  const currentJob = jobs.find(active) || jobs[0];
  const completed = jobs.filter(
    (job) => job.status === "succeeded" && job.asset_id,
  );
  const resultJob =
    completed.find((job) => job.id === selectedResult) || completed[0];
  const resultAsset = assets.find((asset) => asset.id === resultJob?.asset_id);
  const submission = resultAsset
    ? task.submissions.find((item) => item.asset_id === resultAsset.id)
    : undefined;
  const verification = submission
    ? verificationPresentation(submission)
    : undefined;
  const locked = busy || submitting || !!pendingIds;
  const validDuration =
    Number.isInteger(duration) && duration >= 3 && duration <= 15;
  const unavailable =
    options && (!options.available || !options.reference_frames.length);
  const blockedReason = submitting
    ? "正在提交生成任务，请稍候。"
    : pendingIds
      ? "这条建议已有片段正在生成，完成后可查看结果。"
      : unavailable
        ? options.reason || "当前任务没有可用的首帧参考，暂时无法生成。"
        : busy
          ? "其他操作正在处理中，请稍后生成。"
          : !prompt.trim()
            ? "请填写补全镜头描述。"
            : !validDuration
              ? "片段时长需为 3–15 秒的整数。"
              : !options?.reference_frames[frameIndex]
                ? "请选择一张可用的生成首帧。"
                : "";
  const blockedReasonId = `generation-blocked-${task.id}`;
  const generationTermsId = `generation-terms-${task.id}`;

  return (
    <details
      className="generation-panel"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <Icon name="spark" size={17} />
        <span>AI 生成补全片段</span>
        <span className="badge">AI 候选</span>
      </summary>
      <div className="generation-body">
        {loading ? (
          <p className="generation-status" role="status">
            <span className="spinner" />
            正在准备生成选项…
          </p>
        ) : null}
        {error && !options && (
          <p className="generation-error" role="alert">
            {error}
          </p>
        )}
        {!options && !loading && (
          <button
            className="small-button"
            onClick={() => {
              setError("");
              void reload()
                .then((config) => {
                  setPrompt(config.prompt);
                  setDuration(
                    Math.max(
                      3,
                      Math.min(15, Math.round(config.duration_s || 5)),
                    ),
                  );
                  setResolution(config.resolution || "720P");
                })
                .catch((e: Error) => setError(e.message));
            }}
          >
            重新加载
          </button>
        )}
        {options && (
          <>
            <fieldset
              className="generation-form"
              disabled={locked || !options.available}
            >
              {!!options.reference_frames.length && (
                <>
                  <legend>选择生成首帧</legend>
                  <div className="generation-frames">
                    {options.reference_frames.map((frame, index) => (
                      <label
                        key={`${frame.asset_id}:${frame.time_s}`}
                        className={frameIndex === index ? "selected" : ""}
                      >
                        <input
                          type="radio"
                          name={`generation-frame-${task.id}`}
                          checked={frameIndex === index}
                          onChange={() => setFrameIndex(index)}
                        />
                        <img
                          src={frame.url}
                          alt={frame.caption || `参考帧 ${index + 1}`}
                          loading="lazy"
                        />
                        <span>
                          {frameIndex === index ? "✓ 已选首帧" : "设为首帧"} ·{" "}
                          {preciseTime(frame.time_s)}
                        </span>
                      </label>
                    ))}
                  </div>
                </>
              )}
              <label className="generation-prompt">
                补全镜头描述
                <textarea
                  rows={6}
                  maxLength={2000}
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                />
              </label>
              <div className="generation-settings">
                <label>
                  片段时长（3–15 秒）
                  <input
                    type="number"
                    min={3}
                    max={15}
                    step={1}
                    value={Number.isNaN(duration) ? "" : duration}
                    onChange={(event) =>
                      setDuration(
                        event.target.value === ""
                          ? NaN
                          : Number(event.target.value),
                      )
                    }
                  />
                </label>
                <label>
                  清晰度
                  <select
                    value={resolution}
                    onChange={(event) =>
                      setResolution(
                        event.target.value as GenerationOptions["resolution"],
                      )
                    }
                  >
                    <option value="480P">480P</option>
                    <option value="720P">720P</option>
                    <option value="1080P">1080P</option>
                  </select>
                </label>
              </div>
            </fieldset>
            <p className="generation-note" id={generationTermsId}>
              生成会消耗百炼视频生成额度。
            </p>
            {error && (
              <p className="generation-error" role="alert">
                {error}
              </p>
            )}
            {blockedReason && (
              <p
                className="generation-blocked"
                role="status"
                id={blockedReasonId}
              >
                {blockedReason}
              </p>
            )}
            <button
              className="primary full-width"
              disabled={!!blockedReason}
              aria-describedby={
                blockedReason
                  ? `${generationTermsId} ${blockedReasonId}`
                  : generationTermsId
              }
              onClick={() => void generate()}
            >
              {submitting || pendingIds ? (
                <span className="spinner" />
              ) : (
                <Icon name="spark" size={16} />
              )}
              {submitting
                ? "正在提交…"
                : pendingIds
                  ? "片段生成中…"
                  : jobs.length
                    ? "再生成一个片段"
                    : "生成补全片段"}
            </button>
          </>
        )}
        {currentJob && active(currentJob) && (
          <div className="generation-progress" role="status">
            <strong>{currentJob.stage || "正在生成视频"}</strong>
            {currentJob.total_units > 0 && (
              <progress
                max={currentJob.total_units}
                value={currentJob.completed_units}
              />
            )}
          </div>
        )}
        {currentJob?.status === "failed" && (
          <div className="generation-error" role="alert">
            <strong>本次生成未完成</strong>
            <p>
              {currentJob.error_message || "生成服务暂时不可用，请稍后重试。"}
            </p>
            {currentJob.generation_retryable !== false && (
              <button
                className="small-button"
                disabled={locked}
                onClick={() => void retry(currentJob)}
              >
                <Icon name="refresh" size={13} />
                重试此任务
              </button>
            )}
            {currentJob.generation_retryable === false && (
              <small>
                {options?.reason ||
                  "此任务无法直接重试，请查看任务状态后再操作。"}
              </small>
            )}
          </div>
        )}
        {resultJob && (
          <div className="generation-result">
            <div className="generation-result-heading">
              <strong>
                <Icon name="film" size={15} />
                生成结果
              </strong>
              <span className="badge">
                AI 生成 ·{" "}
                {verification?.label || "待分析"}
              </span>
            </div>
            {completed.length > 1 && (
              <select
                aria-label="选择历史生成结果"
                value={resultJob.id}
                onChange={(event) => setSelectedResult(event.target.value)}
              >
                {completed.map((job, index) => (
                  <option key={job.id} value={job.id}>
                    生成片段 {completed.length - index}
                    {index === 0 ? " · 最新" : ""}
                  </option>
                ))}
              </select>
            )}
            {resultAsset ? (
              <>
                <video
                  key={resultAsset.id}
                  src={resultAsset.preview_url || resultAsset.original_url}
                  poster={resultAsset.thumbnail_url || undefined}
                  controls
                  playsInline
                  preload="metadata"
                />
                <div className="generation-result-actions">
                  <a
                    className="small-button"
                    href={resultAsset.original_url}
                    download={resultAsset.original_name}
                  >
                    <Icon name="download" size={14} />
                    下载片段
                  </a>
                  <button
                    className="small-button"
                    disabled={
                      busy ||
                      resultAsset.status !== "ready" ||
                      verification?.pending
                    }
                    onClick={() => onSubmit(task.id, resultAsset.id)}
                  >
                    <Icon name="check" size={14} />
                    {verification?.pending
                      ? "正在分析…"
                      : submission
                        ? "重新分析片段"
                        : "分析此片段"}
                  </button>
                </div>
              </>
            ) : (
              <p className="generation-note">
                片段已生成，正在刷新素材。
                <button
                  className="text-button"
                  onClick={() =>
                    void refreshRef
                      .current()
                      .catch((e: Error) => setError(e.message))
                  }
                >
                  刷新结果
                </button>
              </p>
            )}
          </div>
        )}
      </div>
    </details>
  );
}
