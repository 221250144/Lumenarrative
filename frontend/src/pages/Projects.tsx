import { useState } from "react";
import type { Project } from "../types";
import { Icon } from "../components/Icon";
import { time } from "../api/client";

export function Projects({
  projects,
  onOpen,
  onCreate,
  onDemo,
  busy,
  isDemo,
}: {
  projects: Project[];
  onOpen: (id: string) => void;
  onCreate: (values: Record<string, unknown>) => void;
  onDemo: (scenario: string) => void;
  busy: boolean;
  isDemo: boolean;
}) {
  const [showForm, setShowForm] = useState(false);
  const [search, setSearch] = useState("");
  return (
    <div className="projects-page">
      <section className="hero">
        <div className="hero-copy">
          <div className="tagline">
            <span className="tiny-sun">✳</span> Vlog 镜头诊断与补拍助手
          </div>
          <h1>
            好故事，
            <br />
            值得被<span>完整看见。</span>
          </h1>
          <p>
            上传一条已经剪好的 Vlog。先拆出每个镜头，
            <br className="desktop-break" />
            找到具体的衔接问题，知道该补拍哪一镜。
          </p>
          <div className="hero-actions">
            <button className="primary" onClick={() => setShowForm(true)}>
              <Icon name="plus" /> 新建 Vlog 项目
            </button>
            {isDemo && (
              <button
                className="text-button"
                disabled={busy}
                onClick={() => onDemo("missing")}
              >
                体验演示项目 <Icon name="arrow" />
              </button>
            )}
          </div>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="orbit orbit-three" />
          <div className="sun-disc" />
          <div className="art-horizon" />
          <div className="floating-frame frame-one">
            <div className="frame-scene scene-one">
              <div className="scene-window" />
              <div className="scene-cup" />
            </div>
            <span>
              <i />
              01 / 场景
            </span>
          </div>
          <div className="floating-frame frame-two">
            <div className="frame-scene scene-two">
              <Icon name="spark" size={30} />
            </div>
            <span>
              02 / 缺失的一镜 <b>?</b>
            </span>
          </div>
          <div className="floating-frame frame-three">
            <div className="frame-scene scene-three">
              <div className="scene-cup" />
            </div>
            <span>
              <i />
              03 / 结果
            </span>
          </div>
        </div>
      </section>
      <div className="section-heading">
        <div>
          <h2>
            我的创作 <span className="count">{projects.length}</span>
          </h2>
        </div>
        <input
          className="search"
          aria-label="搜索项目"
          placeholder="搜索项目…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="project-grid">
        {projects
          .filter((p) => p.title.includes(search))
          .map((p) => (
            <button
              className="project-card"
              key={p.id}
              onClick={() => onOpen(p.id)}
            >
              <div className="project-cover">
                {p.cover_url ? (
                  <img src={p.cover_url} alt="" />
                ) : (
                  <div className="cover-placeholder">
                    <Icon name="film" size={44} />
                  </div>
                )}
                {(p.demo_scenario || p.input_mode !== "vlog") && (
                  <span className="cover-tag">
                    {p.demo_scenario ? "演示项目" : "旧版项目"}
                  </span>
                )}
                <span className="cover-time mono">
                  {time(p.duration_s || 0)}
                </span>
                <span className="open-project">
                  <Icon name="arrow" />
                </span>
              </div>
              <div className="project-meta">
                <h3>{p.title}</h3>
                <p>{p.intent}</p>
                <div>
                  <span>
                    {p.asset_count || 0} 个素材 ·{" "}
                    {p.latest_analysis_id ? "已有诊断" : "等待探索"}
                  </span>
                  <span>
                    {new Date(p.created_at).toLocaleDateString("zh-CN", {
                      month: "2-digit",
                      day: "2-digit",
                    })}
                  </span>
                </div>
              </div>
            </button>
          ))}
        <button className="new-project-card" onClick={() => setShowForm(true)}>
          <span className="new-circle">
            <Icon name="plus" size={24} />
          </span>
          <strong>新建 Vlog 项目</strong>
        </button>
      </div>
      {isDemo && (
        <div className="demo-gallery">
          <span>探索不同叙事场景</span>
          {[
            ["complete", "完整故事"],
            ["unordered", "素材乱序"],
            ["montage", "氛围混剪"],
            ["obscured", "动作遮挡"],
            ["dialogue", "对白交代"],
            ["conflict", "属性冲突"],
            ["partial", "部分失败"],
          ].map(([key, label]) => (
            <button key={key} disabled={busy} onClick={() => onDemo(key)}>
              {label}
              <Icon name="arrow" size={13} />
            </button>
          ))}
        </div>
      )}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-project-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              aria-label="关闭"
              className="icon-button modal-close"
              onClick={() => setShowForm(false)}
            >
              <Icon name="close" />
            </button>
            <h2 id="new-project-title">新建 Vlog 项目</h2>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const data = new FormData(e.currentTarget);
                onCreate({
                  title: data.get("title"),
                  intent:
                    String(data.get("intent") || "").trim() ||
                    "审看这条 Vlog，依据实际画面检查人物、地点、动作和转场是否交代清楚，只提出具体且必要的补拍或重剪建议。",
                  input_mode: "vlog",
                  style: data.get("style"),
                  target_duration_s: Number(data.get("duration")),
                });
                setShowForm(false);
              }}
            >
              <label>
                项目名称
                <input
                  name="title"
                  required
                  maxLength={200}
                  placeholder="例如：一杯咖啡的午后"
                  autoFocus
                />
              </label>
              <label>
                想重点检查什么？（选填）
                <textarea
                  name="intent"
                  rows={3}
                  maxLength={5000}
                  placeholder="例如：周末南京探店 Vlog，重点看换地点时是否突兀、食物制作过程是否清楚。留空则按实际画面审看。"
                />
              </label>
              <div className="form-row">
                <label>
                  期望时长（供建议参考）
                  <select name="duration" defaultValue="60">
                    <option value="30">30 秒</option>
                    <option value="60">60 秒</option>
                    <option value="90">90 秒</option>
                    <option value="120">2 分钟</option>
                    <option value="180">3 分钟</option>
                    <option value="300">5 分钟</option>
                    <option value="600">10 分钟</option>
                  </select>
                </label>
              </div>
              <label>
                风格
                <input name="style" defaultValue="自然生活记录" />
              </label>
              <button
                className="primary full-width"
                disabled={busy}
                type="submit"
              >
                创建项目 <Icon name="arrow" />
              </button>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
