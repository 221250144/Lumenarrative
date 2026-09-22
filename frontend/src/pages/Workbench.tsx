import { useRef, useState, useEffect } from "react";
import type {
  Project,
  Asset,
  Diagnosis,
  Evidence,
  Requirement,
  Gap,
  Shot,
} from "../types";
import { Icon } from "../components/Icon";
import { VideoPlayer, type PlaybackRange } from "../components/VideoPlayer";
import { time } from "../api/client";
import { keyEvidence, preciseTime } from "../lib/evidence";

const PAGE_SIZE = 10;
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
  const [seek, setSeek] = useState<PlaybackRange>();
  const [tab, setTab] = useState("gaps");
  const [intent, setIntent] = useState(project.intent);
  const [dragging, setDragging] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [shotPage, setShotPage] = useState(0);
  const [findingPage, setFindingPage] = useState(0);
  const uploadRef = useRef<HTMLInputElement>(null);
  const playerRef = useRef<HTMLDivElement>(null);
  const primary = assets.find(
    (a) => a.id === project.constraints_json.primary_asset_id,
  );
  const active = assets.find((a) => a.id === selected) || primary;
  const legacy = !!diagnosis && !diagnosis.vlog;
  const diagnosisCurrent =
    !!diagnosis?.vlog &&
    !diagnosis.analysis.stale &&
    diagnosis.vlog.primary_asset_id === primary?.id;
  const shots = (
    diagnosisCurrent && diagnosis.shots?.length
      ? diagnosis.shots
      : primary?.shots || []
  )
    .filter((shot) => shot.asset_id === primary?.id)
    .slice()
    .sort((a, b) => a.start_s - b.start_s);
  useEffect(() => {
    setIntent(project.intent);
  }, [project.id, project.intent]);
  useEffect(() => {
    setSelected("");
    setSeek(undefined);
    setShotPage(0);
  }, [project.id, primary?.id]);
  useEffect(() => {
    setFindingPage(0);
  }, [diagnosis?.analysis.id]);
  useEffect(() => {
    setShotPage(0);
  }, [shots.length, diagnosis?.analysis.id]);
  const jumpTo = (
    assetId: string,
    start: number,
    end: number,
    label: string,
  ) => {
    setSelected(assetId);
    setSeek({ at: start, end, nonce: Date.now(), label });
    playerRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };
  const jump = (e: Evidence) =>
    jumpTo(e.asset_id, e.source_start_s, e.source_end_s, "关键证据回看");
  const jumpShot = (shot: Shot) =>
    jumpTo(
      shot.asset_id,
      shot.start_s,
      shot.end_s,
      `镜头 ${shots.findIndex((item) => item.id === shot.id) + 1}`,
    );
  const cannotConclude =
    !!diagnosis &&
    (diagnosis.analysis.provider === "mock" ||
      !diagnosis.analysis.coverage?.visual_complete ||
      diagnosis.analysis.status !== "succeeded");
  const gaps = diagnosis?.gaps || [];
  const actionable = gaps.filter(
    (g) => !["dismissed", "resolved"].includes(g.status),
  );
  const orderedGaps = [
    ...actionable,
    ...gaps.filter((g) => ["dismissed", "resolved"].includes(g.status)),
  ];
  const ready = project.input_mode === "vlog" && primary?.status === "ready";
  const processed = assets.filter((a) => a.status === "ready");
  const acceptUpload = (files: File[]) => {
    if (busy) return;
    if (files.length !== 1) {
      setUploadError(
        "请一次上传一条剪好的 Vlog。补拍片段请在“补拍与重剪”中添加。",
      );
      return;
    }
    setUploadError("");
    onUpload(files, "edited_video");
  };
  return (
    <>
      <div className="workspace-title">
        <div>
          <span className="eyebrow">VLOG REVIEW WORKSPACE</span>
          <h1>{project.title}</h1>
          <p>
            一条 Vlog，逐镜看清楚 <span>/</span> {project.style} <span>/</span>{" "}
            目标 {time(project.target_duration_s)}
          </p>
        </div>
        <button
          className="primary"
          disabled={busy || !ready}
          onClick={onAnalyze}
        >
          <Icon name="spark" />
          {diagnosis ? "重新按 Vlog 分析" : "分析这条 Vlog"}
        </button>
      </div>
      <div className="workflow-steps">
        {[
          ["01", "上传 Vlog", !!primary],
          ["02", "查看镜头切分", !!shots.length],
          ["03", "定位具体问题", diagnosisCurrent],
          ["04", "补拍或重剪", false],
        ].map(([n, label, done]) => (
          <div key={String(n)} className={done ? "step done" : "step"}>
            <span>{done ? <Icon name="check" size={13} /> : n}</span>
            {label}
          </div>
        ))}
        <small>每条建议只保留关键证据</small>
      </div>
      {project.input_mode !== "vlog" && (
        <div className="notice warning">
          <Icon name="film" />
          <span>
            这是旧版项目。请从已有视频中选一条剪好的 Vlog
            作为主片，再开始分析。历史数据会保留。
          </span>
        </div>
      )}
      {diagnosis && (legacy || diagnosis.analysis.stale) && (
        <div className="notice warning">
          <Icon name="alert" />
          <span>
            {legacy
              ? "旧版诊断：下方保留历史结果。选好主片后，重新按 Vlog 分析，获得逐镜定位的建议。"
              : "主片或审看重点已更新。下方为历史结果，请重新分析后再生成计划或导出。"}
          </span>
        </div>
      )}
      <div className="workbench-grid vlog-workbench">
        <aside className="asset-panel vlog-source-panel">
          <div className="panel-title">
            <h3>
              <Icon name="film" />主 Vlog
            </h3>
            <span>每次审看一条</span>
          </div>
          {primary && (
            <div className="primary-vlog">
              <button
                className="primary-preview"
                onClick={() => {
                  setSelected(primary.id);
                  setSeek(undefined);
                }}
              >
                {primary.thumbnail_url ? (
                  <img src={primary.thumbnail_url} alt="主 Vlog 封面" />
                ) : (
                  <Icon name="film" size={30} />
                )}
                <span className="mono">{time(primary.duration_s)}</span>
              </button>
              <strong title={primary.original_name}>
                {primary.original_name}
              </strong>
              <p>
                <span className={primary.status === "ready" ? "ready" : "dim"}>
                  {primary.status === "ready"
                    ? "已就绪"
                    : primary.status === "failed"
                      ? "处理失败"
                      : "正在检测镜头切点…"}
                </span>
                {primary.shot_count ? ` · ${primary.shot_count} 个镜头` : ""}
              </p>
              {primary.synthetic_media && <small>程序生成的演示视频</small>}
            </div>
          )}
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
              acceptUpload(Array.from(e.dataTransfer.files));
            }}
          >
            <button disabled={busy} onClick={() => uploadRef.current?.click()}>
              <Icon name="upload" size={23} />
              <strong>
                {primary ? "上传另一版 Vlog" : "上传一条剪好的 Vlog"}
              </strong>
              <span>
                {primary ? "上传后选择设为主片" : "拖放一个视频或点击上传"}
              </span>
              <small>MP4 / MOV / WebM / MKV / AVI</small>
            </button>
          </div>
          <input
            ref={uploadRef}
            type="file"
            hidden
            accept="video/*,.mkv,.avi"
            onChange={(e) => {
              if (e.target.files?.length)
                acceptUpload(Array.from(e.target.files));
              e.target.value = "";
            }}
          />
          {uploadError && (
            <p className="source-error" role="alert">
              {uploadError}
            </p>
          )}
          {(assets.length > 1 || !primary || project.input_mode !== "vlog") && (
            <div className="primary-picker">
              <label htmlFor="primary-vlog-select">
                {primary ? "更换要审看的主片" : "选择已有 Vlog"}
              </label>
              <select
                id="primary-vlog-select"
                disabled={busy || !processed.length}
                value={project.input_mode === "vlog" ? primary?.id || "" : ""}
                onChange={(e) => {
                  if (e.target.value) onPrimary(e.target.value);
                }}
              >
                <option value="">请选择一条剪好的 Vlog</option>
                {processed.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.original_name} · {time(a.duration_s)}
                  </option>
                ))}
              </select>
              <small>只分析所选主片。补充片段在修改任务中单独使用。</small>
            </div>
          )}
          {!!assets.filter((a) => a.id !== primary?.id && a.status !== "ready")
            .length && (
            <div className="source-processing">
              {assets
                .filter((a) => a.id !== primary?.id && a.status !== "ready")
                .map((a) => (
                  <p key={a.id}>
                    {a.original_name}
                    <span>
                      {a.status === "failed"
                        ? "处理失败，请查看任务提示"
                        : "视频处理中…"}
                    </span>
                  </p>
                ))}
            </div>
          )}
          <section className="intent-card vlog-intent">
            <div className="panel-title">
              <h3>
                <Icon name="sun" />
                审看重点
              </h3>
            </div>
            <textarea
              aria-label="审看重点"
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              rows={5}
            />
            <div className="intent-footer">
              <span>写下你担心的衔接或表达问题。</span>
              {intent !== project.intent && (
                <button
                  disabled={busy || !intent.trim()}
                  className="small-button"
                  onClick={() => onIntent(intent)}
                >
                  保存
                </button>
              )}
            </div>
          </section>
          <div className="library-footer">
            <Icon name="folder" size={14} />
            {Math.max(0, assets.length - (primary ? 1 : 0))} 条其他素材已保留
          </div>
        </aside>
        <div className="preview-column">
          <div ref={playerRef}>
            <VideoPlayer
              asset={active}
              seek={seek}
              onClearRange={() => setSeek(undefined)}
            />
          </div>
          <section className="shot-section">
            <div className="panel-title">
              <h3>
                <Icon name="layers" />
                镜头切分 <span>{shots.length}</span>
              </h3>
              <span>按原片顺序 · 点击回看</span>
            </div>
            {!!shots.length && (
              <p className="shot-explanation">
                按转场和画面变化自动检测切点，连续长镜头保留完整。切点供审看参考，原视频不会被改动。
              </p>
            )}
            {shots.length ? (
              <>
                {diagnosisCurrent && !!diagnosis.vlog?.chapters.length && (
                  <div className="vlog-chapters">
                    {diagnosis.vlog.chapters.map((chapter, i) => (
                      <button
                        className="chapter-chip"
                        key={`${chapter.title}-${i}`}
                        title={chapter.summary}
                        onClick={() => {
                          const index = shots.findIndex((shot) =>
                            chapter.shot_ids.includes(shot.id),
                          );
                          if (index >= 0) {
                            setShotPage(Math.floor(index / PAGE_SIZE));
                            jumpShot(shots[index]);
                          }
                        }}
                      >
                        {String(i + 1).padStart(2, "0")} {chapter.title}
                      </button>
                    ))}
                  </div>
                )}
                <div className="shot-list">
                  {shots
                    .slice(shotPage * PAGE_SIZE, (shotPage + 1) * PAGE_SIZE)
                    .map((shot, i) => (
                      <button
                        className={
                          "shot-row " +
                          (active?.id === shot.asset_id &&
                          seek?.at === shot.start_s &&
                          seek.end === shot.end_s
                            ? "selected"
                            : "")
                        }
                        key={shot.id}
                        onClick={() => jumpShot(shot)}
                      >
                        <div className="shot-thumbnail">
                          {shot.thumbnail_url ? (
                            <img
                              src={shot.thumbnail_url}
                              alt=""
                              loading="lazy"
                            />
                          ) : (
                            <Icon name="film" />
                          )}
                          <span>
                            {String(shotPage * PAGE_SIZE + i + 1).padStart(
                              2,
                              "0",
                            )}
                          </span>
                        </div>
                        <div className="shot-copy">
                          <strong>
                            {shot.summary ||
                              (shot.observed === false
                                ? "这个镜头尚未完成画面理解"
                                : `镜头 ${shotPage * PAGE_SIZE + i + 1}`)}
                          </strong>
                          <span className="mono">
                            {preciseTime(shot.start_s)} —{" "}
                            {preciseTime(shot.end_s)}{" "}
                            <small>
                              {(shot.end_s - shot.start_s).toFixed(1)} 秒
                            </small>
                          </span>
                          <small>
                            {shot.boundary_type === "start"
                              ? "原片开头"
                              : shot.boundary_type === "fade_candidate"
                                ? "渐变转场候选 · 请回看核实"
                                : "画面切换"}
                            {shot.observed === false ? " · 待核实" : ""}
                          </small>
                        </div>
                        <Icon name="play" size={15} />
                      </button>
                    ))}
                </div>
                {shots.length > PAGE_SIZE && (
                  <Pagination
                    page={shotPage}
                    total={shots.length}
                    size={PAGE_SIZE}
                    onPage={setShotPage}
                    noun="镜头"
                  />
                )}
              </>
            ) : (
              <div className="inline-empty">
                {!primary
                  ? "先上传或选择一条 Vlog，处理完成后会按原片顺序展示镜头。"
                  : primary.status !== "ready"
                    ? "正在读取视频并检测转场，处理完成后自动展示镜头。"
                    : "这条视频还没有新版切分结果。点击“分析这条 Vlog”，生成镜头切分与具体建议。"}
              </div>
            )}
          </section>
        </div>
        <aside className="diagnosis-panel vlog-diagnosis">
          <div className="panel-title">
            <h3>
              <Icon name="spark" />
              具体修改建议
            </h3>
            {diagnosis && (
              <span className="badge">
                {legacy
                  ? "历史结果"
                  : diagnosis.analysis.provider === "mock"
                    ? "演示数据"
                    : "Vlog 审看"}
              </span>
            )}
          </div>
          <div className="diagnosis-tabs">
            <button
              className={tab === "gaps" ? "active" : ""}
              onClick={() => setTab("gaps")}
            >
              补拍与重剪{" "}
              {actionable.length > 0 && <span>{actionable.length}</span>}
            </button>
            <button
              className={tab === "requirements" ? "active" : ""}
              onClick={() => setTab("requirements")}
            >
              审看依据
            </button>
          </div>
          {!diagnosis ? (
            <div className="diagnosis-empty">
              <div className="empty-spark">
                <Icon name="spark" size={32} />
              </div>
              <h3>具体到某一秒、某一镜。</h3>
              <p>
                先上传一条 Vlog，查看镜头切分，
                <br />
                再分析换地点、动作跳跃、
                <br />
                结果交代等具体问题。
              </p>
              <div className="principle">
                <Icon name="check" size={14} /> 每次最多 5 条优先建议
              </div>
              <div className="principle">
                <Icon name="check" size={14} /> 每条最多 2 段关键证据
              </div>
              <div className="principle">
                <Icon name="check" size={14} /> 说清补拍什么，插在哪里
              </div>
            </div>
          ) : tab === "requirements" ? (
            <div className="requirement-list">
              {diagnosis.requirements.map((r) => (
                <RequirementCard
                  key={r.id}
                  requirement={r}
                  disabled={busy || !diagnosisCurrent}
                  save={(data) => onRequirement(r.id, data)}
                />
              ))}
            </div>
          ) : (
            <>
              {diagnosis.vlog && (
                <div className="vlog-overview">
                  <span className="eyebrow">
                    {diagnosis.vlog.vlog_type || "VLOG"}
                  </span>
                  <p>{diagnosis.vlog.summary}</p>
                </div>
              )}
              <div className="diagnosis-summary">
                <div
                  className={
                    "summary-icon " +
                    (actionable.length || cannotConclude ? "" : "clear")
                  }
                >
                  <Icon
                    name={actionable.length || cannotConclude ? "eye" : "check"}
                    size={23}
                  />
                </div>
                <div>
                  <strong>
                    {actionable.length
                      ? `${actionable.length} 处值得修改或核实`
                      : cannotConclude
                        ? "当前信息还不足以下结论"
                        : "暂未发现需要补拍的问题"}
                  </strong>
                  <p>
                    {legacy
                      ? "旧版结果可回看，建议重新分析。"
                      : actionable.length
                        ? "先回看对应镜头，再决定是否采用。"
                        : cannotConclude
                          ? "演示结果或不完整的画面分析，不能确认这条 Vlog 是否还需补拍。"
                          : primary?.has_audio
                            ? "当前画面未发现必要缺口；可结合对白继续人工审看。"
                            : "当前画面未发现必要缺口；可继续回看切点和画面节奏。"}
                  </p>
                </div>
              </div>
              <div className="gap-list">
                {orderedGaps
                  .slice(findingPage * 5, (findingPage + 1) * 5)
                  .map((g) => (
                    <GapCard
                      key={g.id}
                      gap={g}
                      evidence={diagnosis.evidence}
                      shots={diagnosis.shots || []}
                      jump={jump}
                      jumpTo={jumpTo}
                      onChange={onGap}
                      disabled={busy || !diagnosisCurrent}
                    />
                  ))}
              </div>
              {orderedGaps.length > 5 && (
                <Pagination
                  page={findingPage}
                  total={orderedGaps.length}
                  size={5}
                  onPage={setFindingPage}
                  noun="历史建议"
                />
              )}
              {diagnosis.analysis.coverage && (
                <div className="coverage-note">
                  <Icon name="eye" size={14} />
                  <div>
                    {diagnosis.analysis.coverage.visual_complete
                      ? "画面分析已完成"
                      : "部分画面未完成分析，结论需要复核"}
                    {!diagnosis.analysis.coverage.audio_complete
                      ? " · 对白信息尚未完整核实"
                      : ""}
                    <details>
                      <summary>查看分析范围</summary>
                      <small>{diagnosis.analysis.coverage.sampling_note}</small>
                      {diagnosis.analysis.coverage.failed_ranges
                        .slice(0, 3)
                        .map((f, i) => (
                          <small className="warning-text" key={i}>
                            {f.reason}
                          </small>
                        ))}
                    </details>
                  </div>
                </div>
              )}
              <div className="diagnosis-bottom">
                <button
                  className="primary full-width"
                  disabled={busy || !diagnosisCurrent || !actionable.length}
                  onClick={onPlan}
                >
                  生成补拍与重剪清单 <Icon name="arrow" />
                </button>
                <small>未确认的意见会保留为待核实任务。</small>
              </div>
            </>
          )}
        </aside>
      </div>
    </>
  );
}

function Pagination({
  page,
  total,
  size,
  onPage,
  noun,
}: {
  page: number;
  total: number;
  size: number;
  onPage: (page: number) => void;
  noun: string;
}) {
  return (
    <div className="shot-pagination">
      <span>
        {page * size + 1}–{Math.min((page + 1) * size, total)} / {total} 个
        {noun}
      </span>
      <div>
        <button
          className="small-button"
          disabled={page === 0}
          onClick={() => onPage(page - 1)}
          aria-label={`上一页${noun}`}
        >
          <Icon name="back" size={13} />
          上一页
        </button>
        <button
          className="small-button"
          disabled={(page + 1) * size >= total}
          onClick={() => onPage(page + 1)}
          aria-label={`下一页${noun}`}
        >
          下一页
          <Icon name="arrow" size={13} />
        </button>
      </div>
    </div>
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
  shots,
  jump,
  jumpTo,
  onChange,
  disabled,
}: {
  gap: Gap;
  evidence: Evidence[];
  shots: Shot[];
  jump: (e: Evidence) => void;
  jumpTo: (asset: string, start: number, end: number, label: string) => void;
  onChange: (id: string, status: string, reason: string) => void;
  disabled: boolean;
}) {
  const [reason, setReason] = useState("");
  const selectedEvidence = keyEvidence(g.evidence_ids, evidence);
  const originalCount = new Set(
    g.evidence_ids.filter((id) => evidence.some((e) => e.id === id)),
  ).size;
  const shotIndex = shots.findIndex((shot) => shot.id === g.anchor?.shot_id);
  const recommendation = g.recommendation;
  return (
    <article
      className={
        "gap-card " +
        (["dismissed", "resolved"].includes(g.status) ? "muted-card" : "")
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
          {recommendation?.kind === "reedit"
            ? "重剪"
            : recommendation?.kind === "reshoot"
              ? "补拍"
              : g.type === "transition_issue"
                ? "镜头衔接"
                : "画面表达"}
        </span>
      </div>
      <h4>{g.description}</h4>
      {g.anchor && (
        <button
          className="finding-anchor"
          onClick={() =>
            jumpTo(
              g.anchor!.asset_id,
              g.anchor!.start_s,
              g.anchor!.end_s,
              "问题位置回看",
            )
          }
        >
          <Icon name="play" size={12} />
          <span>
            {shotIndex >= 0 ? `镜头 ${shotIndex + 1} · ` : "原片位置 · "}
            {preciseTime(g.anchor.start_s)}–{preciseTime(g.anchor.end_s)}
          </span>
        </button>
      )}
      <div className="finding-detail">
        <span>观察到什么</span>
        <p>{g.reason}</p>
      </div>
      {g.impact && (
        <div className="finding-detail">
          <span>哪里不清楚</span>
          <p>{g.impact}</p>
        </div>
      )}
      {recommendation && (
        <div className="recommendation-box">
          <strong>
            <Icon
              name={recommendation.kind === "reedit" ? "layers" : "film"}
              size={14}
            />
            {recommendation.kind === "reedit" ? "建议这样剪" : "建议补拍这一镜"}
          </strong>
          <p>{recommendation.instruction}</p>
          <div className="recommendation-meta">
            {recommendation.shot_scale && (
              <span>{recommendation.shot_scale}</span>
            )}
            {recommendation.duration_s > 0 && (
              <span>{recommendation.duration_s} 秒</span>
            )}
            {g.anchor && (
              <span>
                {recommendation.insert_position === "replace"
                  ? "替换"
                  : recommendation.insert_position === "before"
                    ? "插在之前"
                    : "插在之后"}{" "}
                · {preciseTime(g.anchor.insert_at_s)}
              </span>
            )}
          </div>
          {recommendation.subject_action && (
            <p className="subject-action">
              画面内容：{recommendation.subject_action}
            </p>
          )}
          {!!recommendation.acceptance_checks.length && (
            <details>
              <summary>拍到怎样算完成</summary>
              <ul>
                {recommendation.acceptance_checks
                  .slice(0, 4)
                  .map((check, i) => (
                    <li key={i}>{check}</li>
                  ))}
              </ul>
            </details>
          )}
        </div>
      )}
      {!!selectedEvidence.length && (
        <div className="key-evidence">
          <span>关键证据</span>
          {selectedEvidence.map((e, i) => (
            <button
              className="evidence-link"
              key={e.id}
              onClick={() => jump(e)}
              title={e.action}
            >
              <Icon name="play" size={11} />
              <span>
                {i + 1}. {e.action}
              </span>
              <small className="mono">
                {preciseTime(e.source_start_s)}–{preciseTime(e.source_end_s)}
              </small>
            </button>
          ))}
          {originalCount > selectedEvidence.length && (
            <small>
              已合并重复范围，仅显示 {selectedEvidence.length} 段关键证据（原有{" "}
              {originalCount} 条）。
            </small>
          )}
        </div>
      )}
      {!selectedEvidence.length && (
        <span className="searched-label">
          未取得可回看的直接证据，此意见需要人工核实。
        </span>
      )}
      {!recommendation && g.alternative_edit.feasible && (
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
              采用这条建议
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
