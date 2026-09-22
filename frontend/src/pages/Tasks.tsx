import { useState } from "react";
import type { Project, Asset, Plan, Task, Job } from "../types";
import { Icon } from "../components/Icon";
import { TaskGeneration } from "../components/TaskGeneration";
import { keyEvidence, preciseTime } from "../lib/evidence";

const labels: Record<string, string> = {
  reedit: "重剪现有素材",
  import_existing: "补入已有素材",
  reshoot: "实拍补拍",
  generate: "AI 生成补全",
};
const statuses: Record<string, string> = {
  queued: "等待验证",
  running: "正在验证",
  passed: "通过验收",
  partial: "部分满足",
  failed: "未通过验收",
  uncertain: "无法确认",
};
export function Tasks({
  project,
  assets,
  jobs,
  plan,
  onPlan,
  onSubmit,
  onUpload,
  onDemo,
  onEdit,
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
  onDemo: (task: string, correct: boolean) => void;
  onEdit: () => void;
  onCopy: (text: string) => void;
  onRefresh: () => Promise<void>;
  busy: boolean;
  canPlan: boolean;
}) {
  const [budget, setBudget] = useState(plan?.budget_min?.toString() || "");
  const [filter, setFilter] = useState("all");
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
          <span className="eyebrow">MAKE EVERY SHOT COUNT</span>
          <h1>Vlog 补拍与重剪清单</h1>
          <p>对照具体位置补拍，或尝试 AI 生成候选镜头，再逐项验收。</p>
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
          <button
            className="primary"
            disabled={busy || !canPlan}
            onClick={() => onPlan(budget === "" ? null : Number(budget))}
          >
            <Icon name="layers" />
            生成计划
          </button>
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
        <div className="stat-note">
          <Icon name="sun" size={28} />
          <p>
            补得恰到好处，
            <br />
            也是一种创作。
          </p>
        </div>
      </div>
      {plan?.uncovered_gap_ids.length ? (
        <div className="notice">
          <Icon name="alert" />
          存在待确认或预算内未覆盖的问题。推荐任务不会被当作全部缺口已解决。
        </div>
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
              isDemo={!!project.demo_scenario}
              onSubmit={onSubmit}
              onUpload={onUpload}
              onDemo={onDemo}
              onEdit={onEdit}
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
              ? "无需补拍时，可在“版本与导出”中审看现有 Vlog。"
              : "先在“Vlog 审看”中完成分镜分析并核实建议，再生成具体清单。"}
          </p>
        </div>
      )}
      {plan && <p className="method-note">{plan.note}</p>}
    </div>
  );
}

function TaskCard({
  task: t,
  index,
  assets,
  jobs,
  busy,
  isDemo,
  onSubmit,
  onUpload,
  onDemo,
  onEdit,
  onCopy,
  onRefresh,
}: {
  task: Task;
  index: number;
  assets: Asset[];
  jobs: Job[];
  busy: boolean;
  isDemo: boolean;
  onSubmit: (task: string, asset: string) => void;
  onUpload: (task: string, file: File) => void;
  onDemo: (task: string, correct: boolean) => void;
  onEdit: () => void;
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
            TASK {String(index + 1).padStart(2, "0")}
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
          <small>
            可复制到其他生成工具，也可使用下方 HappyHorse 直接生成。
          </small>
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
          <button className="primary full-width" onClick={onEdit}>
            前往 Vlog 重剪 <Icon name="arrow" />
          </button>
        ) : (
          <>
            <label className={"upload-button " + (busy ? "disabled" : "")}>
              <Icon name="upload" />
              上传补充片段并验证
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
                验证
              </button>
            </div>
            {isDemo && (
              <div className="demo-submit">
                <span>固定演示：</span>
                <button disabled={busy} onClick={() => onDemo(t.id, true)}>
                  补入正确镜头
                </button>
                <button disabled={busy} onClick={() => onDemo(t.id, false)}>
                  试试无关镜头
                </button>
              </div>
            )}
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
            <p>{latest.reason || "正在根据验收条件核实新素材…"}</p>
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
            {latest.verification_status === "passed" && (
              <small>
                补充片段已通过验收。重新诊断后可导出并对比修改效果。
              </small>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
