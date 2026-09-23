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
  const shotScrollRef = useRef<HTMLDivElement>(null);
  const diagnosisScrollRef = useRef<HTMLDivElement>(null);
  const primary = assets.find(
    (a) => a.id === project.constraints_json.primary_asset_id,
  );
  const active = assets.find((a) => a.id === selected) || primary;
  const diagnosisCurrent =
    !!diagnosis?.vlog &&
    !diagnosis.analysis.stale &&
    diagnosis.vlog.primary_asset_id === primary?.id;
  const analyzedShots = diagnosis?.display_shots ?? diagnosis?.shots;
  const shots = (
    diagnosisCurrent && analyzedShots?.length
      ? analyzedShots
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
  useEffect(() => {
    shotScrollRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [shotPage, primary?.id, diagnosis?.analysis.id]);
  useEffect(() => {
    diagnosisScrollRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [tab, findingPage, diagnosis?.analysis.id]);
  const jumpTo = (
    assetId: string,
    start: number,
    end: number,
    label: string,
  ) => {
    setSelected(assetId);
    setSeek({ at: start, end, nonce: Date.now(), label });
    if (
      !window.matchMedia("(min-width: 1251px) and (min-height: 700px)").matches
    )
      playerRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
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
  const coverage = diagnosis?.analysis.coverage;
  const planDisabledReason = busy
    ? "正在处理，请稍后生成清单。"
    : !diagnosisCurrent
      ? "请先重新分析当前 Vlog，再生成建议清单。"
      : !actionable.length
        ? "当前没有需要加入清单的修改建议。"
        : "";
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
    <div className="vlog-workspace">
      <div className="workspace-title">
        <div>
          <h1>{project.title}</h1>
          <p>
            {project.style} <span>/</span> 目标{" "}
            {time(project.target_duration_s)}
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
      <div className="workbench-grid vlog-workbench">
        <aside className="asset-panel vlog-source-panel">
          <div className="panel-title">
            <h3>
              <Icon name="film" />主 Vlog
            </h3>
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
            {intent !== project.intent && (
              <div className="intent-footer">
                <button
                  disabled={busy || !intent.trim()}
                  className="small-button"
                  onClick={() => onIntent(intent)}
                >
                  保存
                </button>
              </div>
            )}
          </section>
          {assets.length > (primary ? 1 : 0) && (
            <div className="library-footer">
              <Icon name="folder" size={14} />
              {assets.length - (primary ? 1 : 0)} 条其他素材
            </div>
          )}
        </aside>
        <div className="preview-column">
          <div className="review-player" ref={playerRef}>
            <VideoPlayer
              asset={active}
              seek={seek}
              onClearRange={() => setSeek(undefined)}
            />
          </div>
          <section className="shot-section">
            <div className="panel-title">
              <h3 id="vlog-shots-title">
                <Icon name="layers" />
                镜头切分 <span>{shots.length}</span>
              </h3>
            </div>
            <div
              className="shot-scroll"
              ref={shotScrollRef}
              tabIndex={0}
              role="region"
              aria-labelledby="vlog-shots-title"
            >
              {shots.length ? (
                <>
                  {diagnosisCurrent && !!diagnosis.vlog?.chapters.length && (
                    <details className="chapter-picker">
                      <summary>
                        按章节定位{" "}
                        <span>{diagnosis.vlog.chapters.length} 个章节</span>
                      </summary>
                      <div className="vlog-chapters">
                        {diagnosis.vlog.chapters.map((chapter, i) => (
                          <button
                            className="chapter-chip"
                            key={`${chapter.title}-${i}`}
                            title={chapter.summary}
                            onClick={(event) => {
                              const index = shots.findIndex(
                                (shot) =>
                                  chapter.shot_ids.includes(shot.id) ||
                                  shot.source_shot_ids?.some((id) =>
                                    chapter.shot_ids.includes(id),
                                  ),
                              );
                              if (index >= 0) {
                                setShotPage(Math.floor(index / PAGE_SIZE));
                                jumpShot(shots[index]);
                                event.currentTarget
                                  .closest("details")
                                  ?.removeAttribute("open");
                              }
                            }}
                          >
                            {String(i + 1).padStart(2, "0")} {chapter.title}
                          </button>
                        ))}
                      </div>
                    </details>
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
                            {shot.boundary_type === "fade_candidate" && (
                              <small>渐变转场待核实</small>
                            )}
                            {shot.observed === false && shot.summary && (
                              <small>画面分析未完成</small>
                            )}
                          </div>
                          <Icon name="play" size={15} />
                        </button>
                      ))}
                  </div>
                </>
              ) : (
                <div className="inline-empty">
                  {!primary
                    ? "尚未选择 Vlog"
                    : primary.status === "failed"
                      ? "视频处理失败"
                      : primary.status !== "ready"
                        ? "正在检测镜头…"
                        : "尚无镜头分析结果"}
                </div>
              )}
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
          </section>
        </div>
        <aside className="diagnosis-panel vlog-diagnosis">
          <div className="panel-title">
            <h3 id="vlog-diagnosis-title">
              <Icon name="spark" />
              具体修改建议
            </h3>
            {diagnosis &&
              (!diagnosisCurrent || diagnosis.analysis.provider === "mock") && (
                <span className="badge">
                  {!diagnosisCurrent ? "旧结果" : "演示数据"}
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
          <div
            className="diagnosis-scroll"
            ref={diagnosisScrollRef}
            tabIndex={0}
            role="region"
            aria-labelledby="vlog-diagnosis-title"
          >
            {!diagnosis ? (
              <div className="diagnosis-empty">
                <div className="empty-spark">
                  <Icon name="spark" size={32} />
                </div>
                <h3>等待 Vlog 分析</h3>
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
                      name={
                        actionable.length || cannotConclude ? "eye" : "check"
                      }
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
                    {cannotConclude && <p>当前分析不足以确认是否还需补拍。</p>}
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
                        shots={diagnosis.display_shots ?? diagnosis.shots ?? []}
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
              </>
            )}
            {(primary || coverage) && (
              <div className="coverage-note">
                <Icon name="eye" size={14} />
                <div>
                  <details>
                    <summary>分析范围</summary>
                    {primary && (
                      <small>
                        {!primary.has_audio
                          ? "主片无音轨，只分析画面。"
                          : primary.audio_status === "analyzed"
                            ? "主片音频已转写。"
                            : primary.audio_status === "failed"
                              ? "主片音频分析失败，对白信息尚未核实。"
                              : "主片对白尚未分析。"}
                      </small>
                    )}
                    {coverage && (
                      <>
                        <small>
                          {coverage.visual_complete
                            ? "画面分析已完成。"
                            : "部分画面未完成分析，结论需要复核。"}
                        </small>
                        <small>
                          {coverage.audio_complete
                            ? "本次分析的对白信息已完整核实。"
                            : "本次分析的对白信息尚未完整核实。"}
                        </small>
                        <small>{coverage.sampling_note}</small>
                        {coverage.failed_ranges.slice(0, 3).map((f, i) => (
                          <small className="warning-text" key={i}>
                            {f.reason}
                          </small>
                        ))}
                      </>
                    )}
                  </details>
                </div>
              </div>
            )}
          </div>
          {diagnosis && tab === "gaps" && (
            <div className="diagnosis-bottom">
              <button
                className="primary full-width"
                disabled={!!planDisabledReason}
                aria-describedby={
                  planDisabledReason ? "workbench-plan-disabled" : undefined
                }
                onClick={onPlan}
              >
                生成补拍与重剪清单 <Icon name="arrow" />
              </button>
              {planDisabledReason && (
                <small className="action-hint" id="workbench-plan-disabled">
                  {planDisabledReason}
                </small>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
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
  const shotIndex = shots.findIndex(
    (shot) =>
      shot.id === g.anchor?.shot_id ||
      shot.source_shot_ids?.includes(g.anchor?.shot_id || ""),
  );
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
            ? "已补足"
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
              <summary>
                {recommendation.kind === "reedit"
                  ? "调整后如何检查"
                  : "拍到怎样算完成"}
              </summary>
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
