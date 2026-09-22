import { useState } from "react";
import type { Project, Asset, Plan, Task } from "../types";
import { Icon } from "../components/Icon";

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
  plan,
  onPlan,
  onSubmit,
  onUpload,
  onDemo,
  onEdit,
  onCopy,
  busy,
  canPlan,
}: {
  project: Project;
  assets: Asset[];
  plan: Plan | null;
  onPlan: (budget: number | null) => void;
  onSubmit: (task: string, asset: string) => void;
  onUpload: (task: string, file: File) => void;
  onDemo: (task: string, correct: boolean) => void;
  onEdit: () => void;
  onCopy: (text: string) => void;
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
          <h1>补全与修改计划</h1>
          <p>优先用已有镜头解决问题，把精力留给最值得补充的一镜。</p>
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
          ["generate", "AI 生成"],
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
              assets={assets}
              busy={busy}
              isDemo={!!project.demo_scenario}
              onSubmit={onSubmit}
              onUpload={onUpload}
              onDemo={onDemo}
              onEdit={onEdit}
              onCopy={onCopy}
            />
          ))}
        </div>
      ) : (
        <div className="large-empty">
          <Icon name="layers" size={40} />
          <h3>{plan ? "当前筛选下没有任务" : "先听听镜头在说什么"}</h3>
          <p>
            {plan
              ? "无需补充时，可以直接生成粗剪审看。"
              : "完成诊断并核实问题后，在这里生成可执行的修改计划。"}
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
  busy,
  isDemo,
  onSubmit,
  onUpload,
  onDemo,
  onEdit,
  onCopy,
}: {
  task: Task;
  index: number;
  assets: Asset[];
  busy: boolean;
  isDemo: boolean;
  onSubmit: (task: string, asset: string) => void;
  onUpload: (task: string, file: File) => void;
  onDemo: (task: string, correct: boolean) => void;
  onEdit: () => void;
  onCopy: (text: string) => void;
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
      <p>{t.instruction}</p>
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
          {t.reference_frames.map((frame, i) => (
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
        {t.acceptance_checks.map((c, i) => (
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
          <small>在外部工具生成视频后，回到这里上传验证。</small>
        </details>
      )}
      <div className="task-submit">
        {t.type === "reedit" ? (
          <button className="primary full-width" onClick={onEdit}>
            前往粗剪调整 <Icon name="arrow" />
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
            {latest.new_evidence?.map((e) => (
              <span className="verification-evidence" key={e.id}>
                {e.action} · {e.source_start_s.toFixed(1)}–
                {e.source_end_s.toFixed(1)}s
              </span>
            ))}
            {latest.verification_status === "passed" && (
              <small>任务验收通过。请重新诊断，确认全部需求并更新粗剪。</small>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
