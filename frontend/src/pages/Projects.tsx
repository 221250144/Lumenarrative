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
      <div className="page-topline">
        <span className="eyebrow">YOUR STORY, IN A NEW LIGHT</span>
        <span className="dim">从一个想法，到一个完整的故事</span>
      </div>
      <section className="hero">
        <div className="hero-copy">
          <div className="tagline">
            <span className="tiny-sun">✳</span> AI 叙事诊断与镜头补全助手
          </div>
          <h1>
            好故事，
            <br />
            值得被<span>完整看见。</span>
          </h1>
          <p>
            把散落的镜头交给旭光集。找到表达的缺口，
            <br className="desktop-break" />
            用更少的修改，让你的创作意图抵达观众。
          </p>
          <div className="hero-actions">
            <button className="primary" onClick={() => setShowForm(true)}>
              <Icon name="plus" /> 开始新的创作
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
          <span className="art-caption">CONNECT THE MOMENTS.</span>
        </div>
      </section>
      <div className="section-heading">
        <div>
          <h2>
            我的创作 <span className="count">{projects.length}</span>
          </h2>
          <p>每一次修改，都让故事更靠近你想表达的样子。</p>
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
                <span className="cover-tag">
                  {p.demo_scenario
                    ? "演示项目"
                    : p.input_mode === "clips"
                      ? "素材创作"
                      : "初稿审看"}
                </span>
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
          <strong>下一个故事，从这里开始</strong>
          <span>上传素材，开启创作</span>
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
      <footer className="quiet-footer">
        <Icon name="sun" size={17} /> 以帧补光，以叙成章{" "}
        <span>旭光集 · 本地创作空间</span>
      </footer>
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
            <span className="eyebrow">A NEW BEGINNING</span>
            <h2 id="new-project-title">你想讲一个怎样的故事？</h2>
            <p className="dim">先告诉我们创作意图，镜头会围绕它展开。</p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const data = new FormData(e.currentTarget);
                onCreate({
                  title: data.get("title"),
                  intent: data.get("intent"),
                  input_mode: data.get("input_mode"),
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
                想让观众看见什么？
                <textarea
                  name="intent"
                  required
                  rows={4}
                  maxLength={5000}
                  placeholder="描述创作目标、必须表达的内容，或者你期待的情绪。氛围短片也可以没有完整故事。"
                />
              </label>
              <div className="form-row">
                <label>
                  输入内容
                  <select name="input_mode">
                    <option value="clips">独立素材</option>
                    <option value="rough_cut">剪辑初稿</option>
                    <option value="mixed">初稿 + 可选素材</option>
                  </select>
                </label>
                <label>
                  目标时长
                  <select name="duration">
                    <option value="30">30 秒</option>
                    <option value="60">60 秒</option>
                    <option value="90">90 秒</option>
                  </select>
                </label>
              </div>
              <label>
                风格
                <input name="style" defaultValue="自然叙事" />
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
