import { useRef, useState, useEffect } from "react";
import type {
  Project,
  Asset,
  Diagnosis,
  Evidence,
  Requirement,
  Gap,
} from "../types";
import { Icon } from "../components/Icon";
import { VideoPlayer } from "../components/VideoPlayer";
import { time } from "../api/client";

const SOURCE_LABELS: Record<string, string> = {
  real_capture: "实拍素材",
  ai_generated: "AI 生成",
  edited_video: "剪辑初稿",
  insta360_export: "影石导出",
  unknown: "未指定来源",
};

export function Workbench({
  project,
  assets,
  diagnosis,
  onAnalyze,
  onUpload,
  onIntent,
  onRequirement,
  onGap,
  onPlan,
  onPrimary,
  busy,
}: {
  project: Project;
  assets: Asset[];
  diagnosis: Diagnosis | null;
  onAnalyze: () => void;
  onUpload: (files: File[], source: string) => void;
  onIntent: (text: string) => void;
  onRequirement: (id: string, data: Record<string, unknown>) => void;
  onGap: (id: string, status: string, reason: string) => void;
  onPlan: () => void;
  onPrimary: (id: string) => void;
  busy: boolean;
}) {
  const [selected, setSelected] = useState("");
  const [seek, setSeek] = useState<{ at: number; nonce: number }>();
  const [source, setSource] = useState("real_capture");
  const [tab, setTab] = useState("gaps");
  const [intent, setIntent] = useState(project.intent);
  const [dragging, setDragging] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    setIntent(project.intent);
  }, [project.id, project.intent]);
  const active = assets.find((a) => a.id === selected) || assets[0];
  const jump = (e: Evidence) => {
    setSelected(e.asset_id);
    setSeek({ at: e.source_start_s, nonce: Date.now() });
  };
  const gaps = diagnosis?.gaps || [];
  const necessary = gaps.filter(
    (g) => !g.optional && g.status !== "dismissed" && g.status !== "resolved",
  );
  const optional = gaps.filter((g) => g.optional);
  const ready =
    assets.length > 0 &&
    assets.some((a) => a.status === "ready") &&
    !assets.some((a) => ["queued", "processing"].includes(a.status));
  return (
    <>
      <div className="workspace-title">
        <div>
          <span className="eyebrow">STORY WORKSPACE</span>
          <h1>{project.title}</h1>
          <p>
            {project.input_mode === "clips"
              ? "独立素材"
              : project.input_mode === "rough_cut"
                ? "剪辑初稿 · 保持原顺序"
                : "初稿与素材 · 指定主初稿"}{" "}
            <span> / </span> {project.style} <span> / </span> 目标{" "}
            {project.target_duration_s} 秒
          </p>
        </div>
        <button
          className="primary"
          disabled={busy || !ready}
          onClick={onAnalyze}
        >
          <Icon name="spark" />
          {diagnosis ? "重新诊断" : "开始叙事诊断"}
        </button>
      </div>
      <div className="workflow-steps">
        {[
          ["01", "整理素材", assets.length > 0],
          ["02", "理解叙事", !!diagnosis],
          ["03", "补全与修改", false],
          ["04", "看见改变", false],
        ].map(([n, label, done]) => (
          <div key={String(n)} className={done ? "step done" : "step"}>
            <span>{done ? <Icon name="check" size={13} /> : n}</span>
            {label}
          </div>
        ))}
        <small>让创作意图贯穿每一步</small>
      </div>
      {diagnosis?.analysis.stale && (
        <div className="notice warning">
          <Icon name="alert" />
          素材或创作需求已更新。下面是历史诊断，请重新分析后再生成计划或粗剪。
        </div>
      )}
      <div className="workbench-grid">
        <aside className="asset-panel">
          <div className="panel-title">
            <h3>
              素材库 <span>{assets.length}</span>
            </h3>
            <button
              className="icon-button"
              title="上传素材"
              disabled={busy}
              onClick={() => uploadRef.current?.click()}
            >
              <Icon name="plus" />
            </button>
          </div>
          <label className="source-select">
            素材来源
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              {Object.entries(SOURCE_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div
            className={"dropzone " + (dragging ? "dragging" : "")}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              if (!busy) onUpload(Array.from(e.dataTransfer.files), source);
            }}
          >
            <button disabled={busy} onClick={() => uploadRef.current?.click()}>
              <Icon name="upload" size={23} />
              <strong>添加你的镜头</strong>
              <span>拖放视频或点击上传</span>
              <small>MP4 / MOV / WebM / MKV / AVI</small>
            </button>
          </div>
          <input
            ref={uploadRef}
            type="file"
            hidden
            multiple
            accept="video/*,.mkv,.avi"
            onChange={(e) => {
              if (e.target.files) onUpload(Array.from(e.target.files), source);
              e.target.value = "";
            }}
          />
          <div className="asset-list">
            {assets.map((asset, i) => (
              <div
                key={asset.id}
                className={
                  "asset-item " + (active?.id === asset.id ? "selected" : "")
                }
              >
                <button
                  onClick={() => {
                    setSelected(asset.id);
                    setSeek(undefined);
                  }}
                >
                  <div className="asset-thumb">
                    {asset.thumbnail_url ? (
                      <img src={asset.thumbnail_url} alt="" />
                    ) : (
                      <Icon name="film" />
                    )}
                    <span className="mono">{time(asset.duration_s)}</span>
                  </div>
                  <div className="asset-name">
                    <span className="asset-index">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <strong title={asset.original_name}>
                      {asset.original_name}
                    </strong>
                  </div>
                  <div className="asset-caption">
                    <span>
                      {asset.synthetic_media
                        ? "演示分镜"
                        : SOURCE_LABELS[asset.source_type]}
                    </span>
                    <span
                      className={asset.status === "ready" ? "ready" : "dim"}
                    >
                      {asset.status === "ready"
                        ? "已就绪"
                        : asset.status === "failed"
                          ? "处理失败"
                          : "处理中"}
                    </span>
                  </div>
                </button>
                {project.input_mode !== "clips" && (
                  <button
                    className="primary-select"
                    disabled={busy || asset.status !== "ready"}
                    onClick={() => onPrimary(asset.id)}
                  >
                    {project.constraints_json.primary_asset_id === asset.id
                      ? "✓ 当前剪辑初稿"
                      : "设为剪辑初稿"}
                  </button>
                )}
              </div>
            ))}
          </div>
          <div className="library-footer">
            <Icon name="folder" size={14} />
            {assets.length} 个素材 ·{" "}
            {time(assets.reduce((n, a) => n + a.duration_s, 0))}
            <span>本地保存</span>
          </div>
        </aside>
        <main className="preview-column">
          <VideoPlayer asset={active} seek={seek} />
          <section className="intent-card">
            <div className="panel-title">
              <h3>
                <Icon name="sun" /> 创作意图
              </h3>
              <span>故事的起点</span>
            </div>
            <textarea
              aria-label="创作意图"
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              rows={3}
            />
            <div className="intent-footer">
              <span>每一条诊断，都以你的表达目标为依据。</span>
              {intent !== project.intent && (
                <button
                  disabled={busy || !intent.trim()}
                  className="small-button"
                  onClick={() => onIntent(intent)}
                >
                  保存意图
                </button>
              )}
            </div>
          </section>
          <section className="evidence-section">
            <div className="panel-title">
              <h3>
                镜头里的线索 <span>{diagnosis?.evidence.length || 0}</span>
              </h3>
              <span>点击回看原片</span>
            </div>
            {diagnosis?.evidence.length ? (
              <div className="evidence-list">
                {diagnosis.evidence.map((e, i) => (
                  <button
                    className="evidence-row"
                    key={e.id}
                    onClick={() => jump(e)}
                  >
                    <span className="evidence-num mono">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <strong>{e.action}</strong>
                      <p>
                        {e.quality_issues.length
                          ? e.quality_issues.join(" · ")
                          : e.evidence_type === "audio"
                            ? "对白证据"
                            : "画面证据"}
                        {e.provenance.demo ? " · 固定演示标注" : ""}
                      </p>
                    </div>
                    <span className="time-pill mono">
                      <Icon name="play" size={10} />
                      {time(e.source_start_s)}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="inline-empty">
                完成诊断后，这里会出现带时间点的素材证据。
              </div>
            )}
          </section>
        </main>
        <aside className="diagnosis-panel">
          <div className="panel-title">
            <h3>
              <Icon name="spark" /> 叙事诊断
            </h3>
            {diagnosis && (
              <span className="badge">
                {diagnosis.analysis.provider === "mock"
                  ? "演示数据"
                  : "模型分析"}
              </span>
            )}
          </div>
          <div className="diagnosis-tabs">
            <button
              className={tab === "gaps" ? "active" : ""}
              onClick={() => setTab("gaps")}
            >
              表达缺口 {necessary.length > 0 && <span>{necessary.length}</span>}
            </button>
            <button
              className={tab === "requirements" ? "active" : ""}
              onClick={() => setTab("requirements")}
            >
              创作需求
            </button>
          </div>
          {!diagnosis ? (
            <div className="diagnosis-empty">
              <div className="empty-spark">
                <Icon name="spark" size={32} />
              </div>
              <h3>先理解，再补全。</h3>
              <p>
                上传镜头并写下创作意图，
                <br />
                让我们一起看看故事哪里
                <br />
                还可以表达得更清楚。
              </p>
              <div className="principle">
                <Icon name="check" size={14} /> 优先利用已有素材
              </div>
              <div className="principle">
                <Icon name="check" size={14} /> 每个判断都有依据
              </div>
              <div className="principle">
                <Icon name="check" size={14} /> 无需补充，也是好结果
              </div>
            </div>
          ) : tab === "requirements" ? (
            <div className="requirement-list">
              {diagnosis.requirements.map((r) => (
                <RequirementCard
                  key={r.id}
                  requirement={r}
                  disabled={busy || diagnosis.analysis.stale}
                  save={(data) => onRequirement(r.id, data)}
                />
              ))}
            </div>
          ) : (
            <>
              <div className="diagnosis-summary">
                <div
                  className={
                    "summary-icon " + (necessary.length ? "" : "clear")
                  }
                >
                  <Icon name={necessary.length ? "eye" : "check"} size={23} />
                </div>
                <div>
                  <strong>
                    {necessary.length
                      ? `${necessary.length} 处表达值得再看一眼`
                      : "当前没有必要补充的镜头"}
                  </strong>
                  <p>
                    {necessary.length
                      ? "先核实问题，再决定怎么修改。"
                      : "已有素材支持当前目标，仍可人工审看。"}
                  </p>
                </div>
              </div>
              <div className="gap-list">
                {gaps
                  .filter((g) => !g.optional)
                  .map((g) => (
                    <GapCard
                      key={g.id}
                      gap={g}
                      evidence={diagnosis.evidence}
                      jump={jump}
                      onChange={onGap}
                      disabled={busy || diagnosis.analysis.stale}
                    />
                  ))}
                {optional.length > 0 && (
                  <div className="optional-heading">
                    可选丰富 · 不影响必要任务
                  </div>
                )}
                {optional.map((g) => (
                  <GapCard
                    key={g.id}
                    gap={g}
                    evidence={diagnosis.evidence}
                    jump={jump}
                    onChange={onGap}
                    disabled={busy || diagnosis.analysis.stale}
                  />
                ))}
              </div>
              {diagnosis.analysis.coverage && (
                <div className="coverage-note">
                  <Icon name="eye" size={14} />
                  <div>
                    已检索 {diagnosis.analysis.coverage.ranges.length} 个素材
                    {!diagnosis.analysis.coverage.visual_complete
                      ? " · 存在分析失败范围"
                      : ""}
                    {!diagnosis.analysis.coverage.audio_complete
                      ? " · 音频覆盖不完整"
                      : ""}
                    <small>{diagnosis.analysis.coverage.sampling_note}</small>
                    {diagnosis.analysis.coverage.failed_ranges.map((f, i) => (
                      <small className="warning-text" key={i}>
                        {f.reason}
                      </small>
                    ))}
                  </div>
                </div>
              )}
              <div className="diagnosis-bottom">
                <button
                  className="primary full-width"
                  disabled={
                    busy || diagnosis.analysis.stale || !necessary.length
                  }
                  onClick={onPlan}
                >
                  制定补全与修改计划 <Icon name="arrow" />
                </button>
                <small>未确认的问题，会保留为待确认任务。</small>
              </div>
            </>
          )}
        </aside>
      </div>
    </>
  );
}

function RequirementCard({
  requirement: r,
  disabled,
  save,
}: {
  requirement: Requirement;
  disabled: boolean;
  save: (data: Record<string, unknown>) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(r.description);
  return (
    <div className="requirement-card">
      <div>
        <span className="badge">
          {r.priority === "must"
            ? "必须表达"
            : r.priority === "should"
              ? "建议表达"
              : "可选丰富"}
        </span>
        <span className="dim">
          {r.origin === "user_explicit" ? "来自创作意图" : "模型建议"}
        </span>
      </div>
      {editing ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
        />
      ) : (
        <p>{r.description}</p>
      )}
      <small>
        可接受证据：
        {r.accepted_evidence_types
          .map((t) => ({ visual: "画面", audio: "对白", text: "文字" })[t] || t)
          .join(" / ")}
      </small>
      <div className="requirement-actions">
        {r.user_confirmed && (
          <span className="ready">
            <Icon name="check" size={12} /> 已确认
          </span>
        )}
        <button
          className="text-button"
          disabled={disabled}
          onClick={() =>
            editing
              ? (save({ description: text, user_confirmed: true }),
                setEditing(false))
              : setEditing(true)
          }
        >
          {editing ? "保存并重新诊断" : "修改"}
        </button>
        {!r.user_confirmed && !editing && (
          <button
            disabled={disabled}
            className="small-button"
            onClick={() => save({ user_confirmed: true })}
          >
            确认需求
          </button>
        )}
      </div>
    </div>
  );
}

function GapCard({
  gap: g,
  evidence,
  jump,
  onChange,
  disabled,
}: {
  gap: Gap;
  evidence: Evidence[];
  jump: (e: Evidence) => void;
  onChange: (id: string, status: string, reason: string) => void;
  disabled: boolean;
}) {
  const [reason, setReason] = useState("");
  return (
    <article
      className={
        "gap-card " +
        (g.status === "dismissed" || g.status === "resolved"
          ? "muted-card"
          : "")
      }
    >
      <div className="gap-top">
        <span className={"badge " + (g.uncertain ? "" : "amber")}>
          {g.status === "resolved"
            ? "已验证解决"
            : g.status === "dismissed"
              ? "已忽略"
              : g.status === "confirmed"
                ? "已确认"
                : g.uncertain
                  ? "需要复核"
                  : g.optional
                    ? "可选建议"
                    : "待确认"}
        </span>
        <span className="dim">
          {g.type === "missing_content"
            ? "内容缺失"
            : g.type === "transition_issue"
              ? "镜头衔接"
              : "表达不足"}
        </span>
      </div>
      <h4>{g.description}</h4>
      <p>{g.reason}</p>
      {g.evidence_ids
        .map((id) => evidence.find((e) => e.id === id))
        .filter((e): e is Evidence => !!e)
        .map((e) => (
          <button className="evidence-link" key={e.id} onClick={() => jump(e)}>
            <Icon name="play" size={11} />
            查看依据{" "}
            <span className="mono">
              {time(e.source_start_s)} — {time(e.source_end_s)}
            </span>
          </button>
        ))}
      {!g.evidence_ids.length && (
        <span className="searched-label">
          检索范围：{g.searched_ranges.length} 个素材，未获得直接支持证据
        </span>
      )}
      {g.alternative_edit.feasible && (
        <div className="reedit-hint">
          <Icon name="layers" size={14} />
          可优先重剪：{g.alternative_edit.reason}
        </div>
      )}
      {g.status === "needs_review" && (
        <div className="gap-actions">
          <input
            aria-label="人工核实说明"
            placeholder="补充你的核实意见（选填）"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div>
            <button
              disabled={disabled}
              className="small-button"
              onClick={() => onChange(g.id, "confirmed", reason)}
            >
              <Icon name="check" size={13} />
              确实需要修改
            </button>
            <button
              disabled={disabled}
              className="text-button"
              onClick={() => onChange(g.id, "dismissed", reason)}
            >
              忽略
            </button>
          </div>
        </div>
      )}
      {g.status === "dismissed" && (
        <button
          className="text-button"
          disabled={disabled}
          onClick={() => onChange(g.id, "needs_review", "重新复核")}
        >
          重新复核
        </button>
      )}
    </article>
  );
}
