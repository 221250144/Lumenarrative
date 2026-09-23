import { useEffect, useState } from "react";
import type { Project, Asset, Edit, Clip } from "../types";
import { Icon } from "../components/Icon";
import { time } from "../api/client";

export function Edits({
  project,
  assets,
  edits,
  onRender,
  busy,
  canRender,
}: {
  project: Project;
  assets: Asset[];
  edits: Edit[];
  onRender: (timeline: Clip[] | null, allow: boolean) => void;
  busy: boolean;
  canRender: boolean;
}) {
  const [before, setBefore] = useState("original");
  const [after, setAfter] = useState("latest");
  const [custom, setCustom] = useState(false);
  const [allow, setAllow] = useState(false);
  const [timeline, setTimeline] = useState<Clip[]>([]);
  const primary =
    assets.find((a) => a.id === project.constraints_json.primary_asset_id) ||
    (project.input_mode === "vlog" ? undefined : assets[0]);
  const assetKey =
    project.input_mode === "vlog"
      ? `${primary?.id}:${primary?.status}:${primary?.segmentation_version}:${primary?.shots?.length}`
      : assets
          .filter((a) => a.status === "ready")
          .map((a) => a.id)
          .join(",");
  useEffect(() => {
    if (project.input_mode === "vlog") {
      setTimeline(
        !primary || primary.status !== "ready"
          ? []
          : primary.shots?.length
            ? primary.shots
                .slice()
                .sort((a, b) => a.start_s - b.start_s)
                .map((shot) => ({
                  asset_id: primary.id,
                  source_in_s: shot.start_s,
                  source_out_s: shot.end_s,
                }))
            : [
                {
                  asset_id: primary.id,
                  source_in_s: 0,
                  source_out_s: primary.duration_s,
                },
              ],
      );
    } else {
      setTimeline(
        assets
          .filter((a) => a.status === "ready")
          .map((a) => ({
            asset_id: a.id,
            source_in_s: 0,
            source_out_s: a.duration_s,
          })),
      );
    }
  }, [assetKey, project.input_mode]); // eslint-disable-line react-hooks/exhaustive-deps
  const done = edits.filter((e) => e.output_url);
  const left =
    before === "original"
      ? primary?.preview_url
      : done.find((e) => e.id === before)?.output_url;
  const right =
    after === "latest"
      ? done[0]?.output_url
      : done.find((e) => e.id === after)?.output_url;
  const move = (i: number, offset: number) => {
    setTimeline((prev) => {
      const next = [...prev];
      [next[i], next[i + offset]] = [next[i + offset], next[i]];
      return next;
    });
  };
  const change = (
    index: number,
    key: "source_in_s" | "source_out_s",
    value: number,
  ) =>
    setTimeline((prev) =>
      prev.map((c, i) => (i === index ? { ...c, [key]: value } : c)),
    );
  const canEdit = project.input_mode === "clips" || allow;
  return (
    <div className="edits-page">
      <div className="workspace-title">
        <div>
          <span className="eyebrow">SEE THE STORY COME TOGETHER</span>
          <h1>看见每一次改变</h1>
          <p>保留主 Vlog 的镜头顺序，对比补拍与重剪前后的效果。</p>
        </div>
        <button
          className="primary"
          disabled={busy || !canRender}
          onClick={() => onRender(custom && canEdit ? timeline : null, allow)}
        >
          <Icon name="film" />
          导出 Vlog 审看版
        </button>
      </div>
      <div className="comparison-grid">
        <section className="comparison-panel">
          <div className="panel-title">
            <h3>
              <span className="compare-dot before" />
              修改前
            </h3>
            <select
              aria-label="修改前版本"
              value={before}
              onChange={(e) => setBefore(e.target.value)}
            >
              <option value="original">
                {project.input_mode === "clips"
                  ? "首条原始素材"
                  : "主 Vlog 原片"}
              </option>
              {done.map((e, i) => (
                <option key={e.id} value={e.id}>
                  版本 {done.length - i} · {time(e.duration_s)}
                </option>
              ))}
            </select>
          </div>
          {left ? (
            <video src={left} controls playsInline preload="metadata" />
          ) : (
            <div className="compare-empty">
              <Icon name="film" size={34} />
              <p>选择主 Vlog 后可预览</p>
            </div>
          )}
          <p>原片保留，可以随时回来对照。</p>
        </section>
        <section className="comparison-panel">
          <div className="panel-title">
            <h3>
              <span className="compare-dot after" />
              修改后
            </h3>
            <select
              aria-label="修改后版本"
              value={after}
              onChange={(e) => setAfter(e.target.value)}
            >
              <option value="latest">最新 Vlog 版本</option>
              {done.map((e, i) => (
                <option key={e.id} value={e.id}>
                  版本 {done.length - i} · {time(e.duration_s)}
                </option>
              ))}
            </select>
          </div>
          {right ? (
            <video src={right} controls playsInline preload="metadata" />
          ) : (
            <div className="compare-empty">
              <Icon name="spark" size={34} />
              <p>下一版故事，正在等待发生</p>
              <span>完成 Vlog 分析后导出可播放的 MP4</span>
            </div>
          )}
          <p>直切与基础编排，保留素材中的真实声音。</p>
        </section>
      </div>
      <section className="timeline-panel">
        <div className="panel-title">
          <div>
            <h3>
              <Icon name="layers" /> Vlog 镜头时间线
            </h3>
            <p>默认保留主片顺序；手动重剪从检测出的镜头开始。</p>
          </div>
          <label className="toggle-label">
            <input
              type="checkbox"
              checked={custom}
              disabled={!canEdit}
              onChange={(e) => setCustom(e.target.checked)}
            />
            手动调整顺序与入出点
          </label>
        </div>
        {project.input_mode !== "clips" && (
          <label className="reedit-consent">
            <input
              type="checkbox"
              checked={allow}
              onChange={(e) => setAllow(e.target.checked)}
            />
            允许重剪主
            Vlog。成片中的字幕和配乐已合在视频里，调整切点时请回听声音衔接。
          </label>
        )}
        {custom && canEdit ? (
          <div className="timeline-editor">
            {timeline.map((clip, i) => {
              const a = assets.find((a) => a.id === clip.asset_id);
              return (
                <div
                  className="timeline-edit-row"
                  key={`${clip.asset_id}-${i}`}
                >
                  <span className="mono dim">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span>{a?.original_name}</span>
                  <label>
                    入点
                    <input
                      aria-label={`片段${i + 1}入点`}
                      type="number"
                      step="0.1"
                      min="0"
                      value={clip.source_in_s}
                      onChange={(e) =>
                        change(i, "source_in_s", Number(e.target.value))
                      }
                    />
                  </label>
                  <label>
                    出点
                    <input
                      aria-label={`片段${i + 1}出点`}
                      type="number"
                      step="0.1"
                      min="0"
                      max={a?.duration_s}
                      value={clip.source_out_s}
                      onChange={(e) =>
                        change(i, "source_out_s", Number(e.target.value))
                      }
                    />
                  </label>
                  <button
                    className="icon-button"
                    aria-label="向前移动"
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                  >
                    <Icon name="back" size={14} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label="向后移动"
                    disabled={i === timeline.length - 1}
                    onClick={() => move(i, 1)}
                  >
                    <Icon name="arrow" size={14} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label="移出时间线"
                    onClick={() =>
                      setTimeline((prev) =>
                        prev.filter((_, index) => index !== i),
                      )
                    }
                  >
                    <Icon name="close" size={14} />
                  </button>
                </div>
              );
            })}
            <span className="dim">
              总时长{" "}
              {timeline
                .reduce((s, c) => s + c.source_out_s - c.source_in_s, 0)
                .toFixed(1)}{" "}
              秒 / 目标 {project.target_duration_s} 秒
            </span>
          </div>
        ) : (
          <div className="timeline-strip">
            {(done[0]?.timeline || timeline).map((clip, i) => {
              const a = assets.find((a) => a.id === clip.asset_id);
              return (
                <div
                  key={`${clip.asset_id}-${i}`}
                  className="timeline-block"
                  style={{
                    flex: Math.max(1, clip.source_out_s - clip.source_in_s),
                  }}
                >
                  {a?.thumbnail_url && <img alt="" src={a.thumbnail_url} />}
                  <span>{a?.original_name}</span>
                  <small className="mono">
                    {time(clip.source_in_s)} — {time(clip.source_out_s)}
                  </small>
                </div>
              );
            })}
          </div>
        )}
      </section>
      <div className="section-heading">
        <div>
          <h2>版本记录</h2>
          <p>每次导出独立保存，原始素材不会被覆盖。</p>
        </div>
      </div>
      <div className="version-list">
        {edits.length ? (
          edits.map((e, i) => (
            <div className="version-row" key={e.id}>
              <span className="version-icon">
                <Icon name="film" />
              </span>
              <div>
                <strong>Vlog 版本 {edits.length - i}</strong>
                <small>
                  {new Date(e.created_at).toLocaleString("zh-CN")} ·{" "}
                  {time(e.duration_s)} ·{" "}
                  {e.render_status === "succeeded"
                    ? "渲染完成"
                    : e.render_status === "failed"
                      ? "渲染失败"
                      : "渲染中"}
                </small>
              </div>
              <span className="version-note">{e.note}</span>
              <a className="small-button" href={e.edl_url} download>
                <Icon name="download" size={14} />
                EDL
              </a>
              {e.output_url && (
                <a
                  className="primary small"
                  href={e.output_url}
                  download="叙光集-Vlog.mp4"
                >
                  <Icon name="download" size={14} />
                  MP4
                </a>
              )}
            </div>
          ))
        ) : (
          <div className="inline-empty">
            还没有导出版本。完成 Vlog 分析后，可以导出第一版审看视频。
          </div>
        )}
      </div>
    </div>
  );
}
