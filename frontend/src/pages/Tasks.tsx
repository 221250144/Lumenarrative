import { useState } from "react";
import type { Project, Asset, Plan, Task, Job } from "../types";
import { Icon } from "../components/Icon";
import { TaskGeneration } from "../components/TaskGeneration";
import { keyEvidence, preciseTime } from "../lib/evidence";

const labels: Record<string, string> = {
  reedit: "重剪建议",
  import_existing: "补入已有素材",
  reshoot: "实拍补拍",
  generate: "AI 生成补全",
};
const statuses: Record<string, string> = {
  queued: "等待补拍分析",
  running: "正在分析补拍",
  passed: "符合补拍要求",
  partial: "部分满足",
  failed: "未满足补拍要求",
  uncertain: "需要人工复核",
};
export function Tasks({
  project,
  assets,
  jobs,
  plan,
  onPlan,
  onSubmit,
  onUpload,
  onCopy,
  onRefresh,
  busy,
  canPlan,
}: {
  project: Project;
  assets: Asset[];
  jobs: Job[];
  plan: Plan | null;
  onPlan: (budget: number | null) => void;
  onSubmit: (task: string, asset: string) => void;
  onUpload: (task: string, file: File) => void;
  onCopy: (text: string) => void;
  onRefresh: () => Promise<void>;
  busy: boolean;
  canPlan: boolean;
}) {
  const [budget, setBudget] = useState(plan?.budget_min?.toString() || "");
  const [filter, setFilter] = useState("all");
  const validBudget =
    budget === "" ||
    (Number.isInteger(Number(budget)) &&
      Number(budget) >= 0 &&
      Number(budget) <= 600);
  const planDisabledReason = busy
    ? "正在处理，请稍后生成清单。"
    : !canPlan
      ? "请先在“Vlog 审看”中完成当前主片的分析。"
      : !validBudget
        ? "可投入时间需为 0–600 分钟的整数，也可以留空。"
        : "";
  const tasks =
    plan?.tasks.filter(
      (t) =>
        filter === "all" ||
        (filter === "selected" ? t.selected : t.type === filter),
    ) || [];
  return (
    <div className="tasks-page">
      <div className="workspace-title">
        <div>
          <h1>Vlog 补拍与重剪清单</h1>
        </div>
        <div className="budget-control">
          <label>
            可投入时间
            <input
              type="number"
              min="0"
              max="600"
              placeholder="不限"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
            />
            <span>分钟</span>
          </label>
          <div className="plan-action">
            <button
              className="primary"
              disabled={!!planDisabledReason}
              aria-describedby={
                planDisabledReason ? "plan-blocked-reason" : undefined
              }
              onClick={() => onPlan(budget === "" ? null : Number(budget))}
            >
              <Icon name="layers" />
              生成清单
            </button>
            {planDisabledReason && (
              <small
                className="action-hint"
                id="plan-blocked-reason"
                role="status"
              >
                {planDisabledReason}
              </small>
            )}
          </div>
        </div>
      </div>
      <div className="stat-row">
        <div>
          <span>推荐执行</span>
          <strong>
            {plan?.tasks.filter((t) => t.selected).length || 0}
            <small>个任务</small>
          </strong>
        </div>
        <div>
          <span>预计人工投入</span>
          <strong>
            {plan?.estimated_effort_min || 0}
            <small>分钟</small>
          </strong>
        </div>
        <div>
          <span>尚未覆盖</span>
          <strong>
            {plan?.uncovered_gap_ids.length || 0}
            <small>处缺口</small>
          </strong>
        </div>
      </div>
      {plan && (plan.note || plan.uncovered_gap_ids.length > 0) ? (
        <details className="context-note plan-context">
          <summary>
            清单说明
            {plan.uncovered_gap_ids.length
              ? ` · ${plan.uncovered_gap_ids.length} 处问题尚未覆盖`
              : ""}
          </summary>
          {plan.uncovered_gap_ids.length > 0 && (
            <p>
              部分问题仍待确认，或未包含在当前时间预算中，可逐条查看后再决定。
            </p>
          )}
          {plan.note && <p>{plan.note}</p>}
        </details>
      ) : null}
      <div className="filter-tabs">
        {[
          ["all", "全部方案"],
          ["selected", "推荐执行"],
          ["reedit", "重剪"],
          ["reshoot", "补拍"],
          ...(plan?.tasks.some((task) => task.type === "generate")
            ? [["generate", "历史生成方案"]]
            : []),
        ].map(([key, label]) => (
          <button
            className={filter === key ? "active" : ""}
            key={key}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tasks.length ? (
        <div className="task-grid">
          {tasks.map((t, i) => (
            <TaskCard
              key={t.id}
              task={t}
              index={i}
              assets={assets.filter(
                (asset) =>
                  asset.id !== project.constraints_json.primary_asset_id,
              )}
              jobs={jobs}
              busy={busy}
              onSubmit={onSubmit}
              onUpload={onUpload}
              onCopy={onCopy}
              onRefresh={onRefresh}
            />
          ))}
        </div>
      ) : (
        <div className="large-empty">
          <Icon name="layers" size={40} />
          <h3>{plan ? "当前筛选下没有任务" : "先审看你的 Vlog"}</h3>
          <p>
            {plan
              ? "可以切换筛选查看其他建议，或回到“Vlog 审看”回放原片。"
              : "先在“Vlog 审看”中完成分镜分析并核实建议，再生成具体清单。"}
          </p>
        </div>
      )}
    </div>
  );
}

function TaskCard({
  task: t,
  index,
  assets,
  jobs,
  busy,
  onSubmit,
  onUpload,
  onCopy,
  onRefresh,
}: {
  task: Task;
  index: number;
  assets: Asset[];
  jobs: Job[];
  busy: boolean;
  onSubmit: (task: string, asset: string) => void;
  onUpload: (task: string, file: File) => void;
  onCopy: (text: string) => void;
  onRefresh: () => Promise<void>;
}) {
  const [assetId, setAssetId] = useState("");
  const latest = t.submissions[0];
  return (
    <article className={"task-card " + (t.selected ? "recommended" : "")}>
      <div className="task-card-top">
        <div className="task-icon">
          <Icon
            name={
              t.type === "generate"
                ? "spark"
                : t.type === "reshoot"
                  ? "film"
                  : "layers"
            }
          />
        </div>
        <div>
          <span className="eyebrow">
            任务 {String(index + 1).padStart(2, "0")}
          </span>
          <h3>{labels[t.type]}</h3>
        </div>
        <span className={"badge " + (t.selected ? "lime" : "")}>
          {t.selected
            ? "推荐执行"
            : t.needs_confirmation
              ? "需确认"
              : "备选方案"}
        </span>
      </div>
      <h4>{t.requirement_description}</h4>
      {t.anchor && (
        <div className="task-anchor mono">
          <Icon name="film" size={13} />主 Vlog ·{" "}
          {preciseTime(t.anchor.start_s)}–{preciseTime(t.anchor.end_s)}
        </div>
      )}
      <p>{t.recommendation?.instruction || t.instruction}</p>
      {t.recommendation && (
        <div className="recommendation-box">
          <strong>
            {t.recommendation.kind === "reedit"
              ? "重剪执行要点"
              : "这次补拍要拍到"}
          </strong>
          {t.recommendation.subject_action && (
            <p>{t.recommendation.subject_action}</p>
          )}
          <div className="recommendation-meta">
            {t.recommendation.shot_scale && (
              <span>{t.recommendation.shot_scale}</span>
            )}
            {t.recommendation.duration_s > 0 && (
              <span>{t.recommendation.duration_s} 秒</span>
            )}
            {t.anchor && (
              <span>
                {t.recommendation.insert_position === "replace"
                  ? "替换此处"
                  : t.recommendation.insert_position === "before"
                    ? "插在之前"
                    : "插在之后"}{" "}
                · {preciseTime(t.anchor.insert_at_s)}
              </span>
            )}
          </div>
        </div>
      )}
      <div className="task-duration">
        <Icon name="clock" size={14} />
        预计人工投入 {t.estimated_effort_min} 分钟
        {t.type === "generate" && <span>不含生成等待</span>}
      </div>
      <div className="continuity-box">
        <strong>连续性要求</strong>
        <p>{t.continuity}</p>
      </div>
      {!!t.reference_frames?.length && (
        <div className="reference-frames">
          {t.reference_frames.slice(0, 2).map((frame, i) => (
            <a
              href={frame.url}
              key={i}
              target="_blank"
              rel="noreferrer"
              title={frame.caption}
            >
              <img src={frame.url} alt={frame.caption} />
              <span>参考帧 · {frame.time_s.toFixed(1)}s</span>
            </a>
          ))}
        </div>
      )}
      <div className="acceptance">
        <h5>如何判断补好了？</h5>
        {(t.recommendation?.acceptance_checks?.length
          ? t.recommendation.acceptance_checks
          : t.acceptance_checks
        ).map((c, i) => (
          <div key={c}>
            <span>{String(i + 1).padStart(2, "0")}</span>
            {c}
          </div>
        ))}
      </div>
      {t.prompt && (
        <details className="prompt-box">
          <summary>查看 AI 生成提示词</summary>
          <p>{t.prompt}</p>
          <button className="small-button" onClick={() => onCopy(t.prompt)}>
            <Icon name="copy" size={13} />
            复制提示词
          </button>
        </details>
      )}
      {["reshoot", "generate"].includes(t.type) && (
        <TaskGeneration
          task={t}
          assets={assets}
          liveJobs={jobs}
          busy={busy}
          onRefresh={onRefresh}
          onSubmit={onSubmit}
        />
      )}
      <div className="task-submit">
        {t.type === "reedit" ? (
          <>
            <button
              className="small-button"
              onClick={() =>
                onCopy(
                  [
                    t.requirement_description,
                    t.anchor
                      ? `原片位置：${preciseTime(t.anchor.start_s)}–${preciseTime(t.anchor.end_s)}`
                      : "",
                    t.recommendation?.instruction || t.instruction,
                    t.continuity,
                  ]
                    .filter(Boolean)
                    .join("\n"),
                )
              }
            >
              <Icon name="copy" size={13} /> 复制重剪建议
            </button>
          </>
        ) : (
          <>
            <label className={"upload-button " + (busy ? "disabled" : "")}>
              <Icon name="upload" />
              上传补拍视频并分析
              <input
                type="file"
                accept="video/*,.mkv,.avi"
                disabled={busy}
                hidden
                onChange={(e) => {
                  if (e.target.files?.[0]) onUpload(t.id, e.target.files[0]);
                  e.target.value = "";
                }}
              />
            </label>
            <div className="existing-submit">
              <select
                aria-label="选择已上传的补充素材"
                value={assetId}
                onChange={(e) => setAssetId(e.target.value)}
              >
                <option value="">选择已上传的新素材</option>
                {assets
                  .filter((a) => a.status === "ready")
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.original_name}
                    </option>
                  ))}
              </select>
              <button
                className="small-button"
                disabled={busy || !assetId}
                onClick={() => onSubmit(t.id, assetId)}
              >
                分析片段
              </button>
            </div>
          </>
        )}
        {latest && (
          <div
            className={
              "verification-result " +
              (latest.verification_status === "passed" ? "passed" : "")
            }
          >
            <strong>
              <Icon
                name={latest.verification_status === "passed" ? "check" : "eye"}
                size={16}
              />
              {statuses[latest.verification_status] ||
                latest.verification_status}
              {latest.stale ? " · 历史结果" : ""}
            </strong>
            <p>{latest.reason || "正在对照补拍要求分析新素材…"}</p>
            {latest.checks?.map((c) => (
              <div className="check-result" key={c.check}>
                <span className={c.status === "passed" ? "ready" : "dim"}>
                  {c.status === "passed" ? "✓" : "○"}
                </span>
                <span>
                  {c.check}
                  <small>{c.reason}</small>
                </span>
              </div>
            ))}
            {keyEvidence(
              latest.new_evidence?.map((e) => e.id) || [],
              latest.new_evidence || [],
            ).map((e) => (
              <span className="verification-evidence" key={e.id}>
                {e.action} · {e.source_start_s.toFixed(1)}–
                {e.source_end_s.toFixed(1)}s
              </span>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
