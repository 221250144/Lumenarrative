import { useState, useEffect, useCallback, useRef } from "react";
import { api, post, patch, upload, watchJob } from "../api/client";
import { createIdempotencyKey } from "../api/idempotency";
import type {
  Project,
  Asset,
  Analysis,
  Diagnosis,
  Plan,
  Edit,
  Job,
  Health,
} from "../types";
import { Icon } from "../components/Icon";
import { Projects } from "./Projects";
import { Workbench } from "./Workbench";
import { Tasks } from "./Tasks";
import { Edits } from "./Edits";

type Page = "projects" | "workspace" | "tasks" | "edits";
export default function App() {
  const query = new URLSearchParams(window.location.search);
  const [projectId, setProjectId] = useState(query.get("project") || "");
  const [page, setPage] = useState<Page>(projectId ? "workspace" : "projects");
  const [health, setHealth] = useState<Health | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [edits, setEdits] = useState<Edit[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const activeProject = useRef(projectId);
  const refreshSequence = useRef(0);
  const refresh = useCallback(async () => {
    const sequence = ++refreshSequence.current;
    const all = await api<Project[]>("/projects");
    setProjects(all);
    if (!projectId) return;
    const [p, a, r, pl, e, j] = await Promise.all([
      api<Project>(`/projects/${projectId}`),
      api<Asset[]>(`/projects/${projectId}/assets`),
      api<Analysis[]>(`/projects/${projectId}/analyses`),
      api<Plan[]>(`/projects/${projectId}/completion-plans`),
      api<Edit[]>(`/projects/${projectId}/edits`),
      api<Job[]>(`/projects/${projectId}/jobs`),
    ]);
    if (
      activeProject.current !== projectId ||
      sequence !== refreshSequence.current
    )
      return;
    setProject(p);
    setAssets(a);
    setPlans(pl);
    setEdits(e);
    setJobs(j);
    const latest =
      p.latest_analysis_id || r.find((run) => run.status === "succeeded")?.id;
    const d = latest
      ? await api<Diagnosis>(`/analyses/${latest}/diagnosis`)
      : null;
    if (
      activeProject.current === projectId &&
      sequence === refreshSequence.current
    )
      setDiagnosis(d);
  }, [projectId]);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  useEffect(() => {
    api<Health>("/health")
      .then(setHealth)
      .catch(() => setError("暂时无法连接服务，请稍后刷新重试。"));
  }, []);
  useEffect(() => {
    activeProject.current = projectId;
    void refresh().catch((e) => setError(e.message));
  }, [refresh, projectId]);
  const runningIds = jobs
    .filter((j) => ["queued", "running"].includes(j.status))
    .map((j) => j.id)
    .join(",");
  useEffect(() => {
    if (!runningIds) return;
    const stops = runningIds.split(",").map((id) =>
      watchJob(id, (job) => {
        setJobs((prev) => prev.map((j) => (j.id === id ? job : j)));
        if (["succeeded", "failed", "cancelled"].includes(job.status))
          void refreshRef.current().catch((e) => setError(e.message));
      }),
    );
    return () => stops.forEach((stop) => stop());
  }, [runningIds]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);
  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setError("");
    try {
      await fn();
      await refreshRef.current();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy("");
    }
  }
  function open(id: string) {
    activeProject.current = id;
    setProjectId(id);
    setProject(null);
    setDiagnosis(null);
    setAssets([]);
    setPlans([]);
    setEdits([]);
    setJobs([]);
    setPage("workspace");
    window.history.replaceState({}, "", `?project=${encodeURIComponent(id)}`);
  }
  function navigate(next: Page) {
    setPage(next);
    if (next === "projects") {
      setProjectId("");
      activeProject.current = "";
      setProject(null);
      window.history.replaceState({}, "", "/");
    }
  }
  const analyze = () =>
    act("创建 Vlog 分析任务", async () => {
      if (
        project?.input_mode !== "vlog" ||
        !project.constraints_json.primary_asset_id
      )
        throw new Error("请先选择一条剪好的 Vlog 作为主片。");
      if (
        !assets.some(
          (a) =>
            a.id === project.constraints_json.primary_asset_id &&
            a.status === "ready",
        )
      )
        throw new Error("主 Vlog 仍在处理，请等待镜头切分完成。");
      await post(`/projects/${projectId}/analyses`, {}, createIdempotencyKey());
    });
  const makePlan = (budget: number | null = 30) =>
    act("生成修改计划", async () => {
      if (!diagnosis) return;
      await post(`/projects/${projectId}/completion-plans`, {
        analysis_id: diagnosis.analysis.id,
        budget_min: budget,
      });
      setPage("tasks");
    });
  const waitJob = (id: string) =>
    new Promise<void>((resolve, reject) => {
      watchJob(id, (job) => {
        if (job.status === "succeeded") resolve();
        if (job.status === "failed")
          reject(new Error(job.error_message || "处理失败"));
      });
    });
  async function submit(task: string, asset: string) {
    await post(
      `/completion-tasks/${task}/submissions`,
      { asset_id: asset },
      createIdempotencyKey(),
    );
  }
  const busyJob = jobs.find((j) => ["queued", "running"].includes(j.status));
  const failed = jobs.filter((j) => j.status === "failed");
  const canUse =
    !!diagnosis?.vlog &&
    project?.input_mode === "vlog" &&
    diagnosis.vlog.primary_asset_id ===
      project.constraints_json.primary_asset_id &&
    !diagnosis.analysis.stale &&
    diagnosis.analysis.status === "succeeded";
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => navigate("projects")}>
          <span className="brand-mark">
            <Icon name="sun" size={27} />
          </span>
          <span>
            叙光集<small>LUMENARRATIVE</small>
          </span>
        </button>
        <div className="space-label">
          <span className="space-avatar">叙</span>
          <div>
            我的创作空间<small>Vlog 工作区</small>
          </div>
          <span className="space-chevron">⌄</span>
        </div>
        <span className="nav-label">创作工具</span>
        <nav>
          {(
            [
              ["projects", "grid", "我的项目"],
              ["workspace", "spark", "Vlog 审看"],
              ["tasks", "layers", "补拍与重剪"],
              ["edits", "film", "版本与导出"],
            ] as const
          ).map(([key, icon, label]) => (
            <button
              key={key}
              className={page === key ? "active" : ""}
              disabled={key !== "projects" && !projectId}
              onClick={() => navigate(key)}
            >
              <Icon name={icon} />
              {label}
              {key === "projects" && <small>{projects.length}</small>}
            </button>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-note">
          <div className="note-sun">
            <Icon name="sun" size={22} />
          </div>
          <p>
            镜头有限，
            <br />
            故事的可能无限。
          </p>
          <span>以帧补光，以叙成章</span>
        </div>
        <button
          className="settings-button"
          onClick={() => setSettingsOpen(true)}
        >
          <Icon name="settings" />
          运行与接入状态
          <Icon name="arrow" size={14} />
        </button>
        <div className="sidebar-bottom">
          <span className="status-dot" /> Vlog 专用 · v0.2
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <Icon name="folder" size={16} />
            <button onClick={() => navigate("projects")}>创作空间</button>
            <span>/</span>
            <strong>
              {page === "projects" ? "我的项目" : project?.title || "载入中"}
            </strong>
          </div>
          <div className="topbar-right">
            <span
              className={
                "mode-badge " + (health?.provider === "mock" ? "demo" : "")
              }
            >
              <i />
              {health?.provider === "mock"
                ? "演示数据模式"
                : health
                  ? "真实模型模式"
                  : "连接中"}
            </span>
            <span className="user-avatar">创</span>
          </div>
        </header>
        {health?.provider === "mock" && (
          <div className="demo-banner">
            <Icon name="eye" size={14} />
            <span>
              当前为演示数据模式：视频处理与导出真实运行，叙事分析使用固定夹具。用户上传素材不会被假装成已理解。
            </span>
          </div>
        )}
        <main className="main-content">
          {error && (
            <div className="error-banner" role="alert">
              <Icon name="alert" />
              <span>{error}</span>
              <button
                className="icon-button"
                aria-label="关闭错误"
                onClick={() => setError("")}
              >
                <Icon name="close" size={15} />
              </button>
            </div>
          )}
          {busyJob && page !== "projects" && (
            <div className="progress-banner" aria-live="polite">
              <span className="spinner" />
              <strong>{busyJob.stage}</strong>
              {busyJob.total_units > 0 && (
                <span className="mono">
                  {busyJob.completed_units} / {busyJob.total_units}
                </span>
              )}
              <small>任务在后台处理，你可以继续查看素材。</small>
            </div>
          )}
          {failed.length > 0 && page !== "projects" && (
            <details className="failed-jobs">
              <summary>
                <Icon name="alert" size={14} />
                {failed.length} 个任务需要处理
              </summary>
              {failed.map((j) => (
                <div key={j.id}>
                  <span>{j.error_message}</span>
                  <button
                    className="small-button"
                    disabled={
                      !!busy ||
                      (j.type === "generation" &&
                        j.generation_retryable === false)
                    }
                    onClick={() =>
                      act("重试任务", async () => {
                        await post(`/jobs/${j.id}/retry`);
                      })
                    }
                  >
                    <Icon name="refresh" size={13} />
                    {j.type === "generation" && j.generation_retryable === false
                      ? "无法直接重试"
                      : "重试"}
                  </button>
                </div>
              ))}
            </details>
          )}
          {page === "projects" ? (
            <Projects
              projects={projects}
              onOpen={open}
              busy={!!busy}
              isDemo={health?.provider === "mock"}
              onCreate={(values) =>
                act("创建项目", async () => {
                  const p = await post<Project>("/projects", values);
                  open(p.id);
                })
              }
              onDemo={(scenario) =>
                act("准备演示素材", async () => {
                  const p = await post<Project>(`/demo?scenario=${scenario}`);
                  open(p.id);
                })
              }
            />
          ) : !project ? (
            <div className="loading-page">
              <span className="spinner" />
              正在打开创作空间…
            </div>
          ) : page === "workspace" ? (
            <Workbench
              project={project}
              assets={assets}
              diagnosis={diagnosis}
              busy={
                !!busy ||
                jobs.some(
                  (j) =>
                    j.type === "analysis" &&
                    ["queued", "running"].includes(j.status),
                )
              }
              onAnalyze={analyze}
              onUpload={(files, source) =>
                act("上传 Vlog 并检测镜头", async () => {
                  if (files.length !== 1)
                    throw new Error("请一次上传一条剪好的 Vlog。");
                  await upload(projectId, files[0], source);
                })
              }
              onIntent={(text) =>
                act("保存创作意图", async () => {
                  await patch(`/projects/${projectId}`, { intent: text });
                })
              }
              onRequirement={(id, data) =>
                act("更新创作需求", async () => {
                  await patch(`/requirements/${id}`, data);
                  await post(
                    `/projects/${projectId}/analyses`,
                    {},
                    createIdempotencyKey(),
                  );
                })
              }
              onGap={(id, status, reason) =>
                act("保存核实结果", async () => {
                  await patch(`/gaps/${id}`, { status, reason });
                })
              }
              onPlan={() => makePlan()}
              onPrimary={(id) =>
                act("设置主 Vlog", async () => {
                  await patch(`/projects/${projectId}`, {
                    input_mode: "vlog",
                    primary_asset_id: id,
                  });
                })
              }
            />
          ) : page === "tasks" ? (
            <Tasks
              project={project}
              assets={assets}
              jobs={jobs}
              plan={plans[0] || null}
              busy={!!busy}
              canPlan={canUse}
              onRefresh={refresh}
              onPlan={makePlan}
              onSubmit={(task, asset) =>
                act("验证补充素材", () => submit(task, asset))
              }
              onUpload={(task, file) =>
                act("处理补充素材", async () => {
                  const result = await upload(projectId, file, "unknown");
                  await refresh();
                  await waitJob(result.job_id);
                  await submit(task, result.asset_id);
                })
              }
              onDemo={(task, correct) =>
                act("准备演示补充镜头", async () => {
                  const result = await post<{
                    asset_id: string;
                    job_id: string;
                  }>(
                    `/projects/${projectId}/demo-asset?role=${correct ? "process" : "result"}`,
                  );
                  await refresh();
                  await waitJob(result.job_id);
                  await submit(task, result.asset_id);
                })
              }
              onEdit={() => setPage("edits")}
              onCopy={(text) =>
                act("复制提示词", async () => {
                  await navigator.clipboard.writeText(text);
                  setToast("提示词已复制");
                })
              }
            />
          ) : (
            <Edits
              project={project}
              assets={assets}
              edits={edits}
              busy={!!busy}
              canRender={canUse}
              onRender={(timeline, allow) =>
                act("创建粗剪任务", async () => {
                  await post(`/projects/${projectId}/edits`, {
                    analysis_id: diagnosis?.analysis.id,
                    timeline,
                    allow_reedit: allow,
                  });
                })
              }
            />
          )}
        </main>
      </div>
      {busy && (
        <div className="action-toast" role="status">
          <span className="spinner" />
          {busy}…
        </div>
      )}
      {toast && (
        <div className="action-toast">
          <Icon name="check" />
          {toast}
        </div>
      )}
      {settingsOpen && (
        <div className="modal-overlay" onClick={() => setSettingsOpen(false)}>
          <section
            className="modal settings-modal"
            role="dialog"
            aria-modal="true"
            aria-label="运行与接入状态"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="icon-button modal-close"
              aria-label="关闭"
              onClick={() => setSettingsOpen(false)}
            >
              <Icon name="close" />
            </button>
            <span className="eyebrow">WORKSPACE STATUS</span>
            <h2>运行与接入状态</h2>
            <dl>
              <dt>叙事分析</dt>
              <dd>
                {health?.provider === "mock"
                  ? "固定演示夹具"
                  : health?.model_configured
                    ? "已配置模型服务"
                    : "尚未配置模型凭据"}
              </dd>
              <dt>视频处理</dt>
              <dd>
                {health?.ffmpeg_available ? "FFmpeg 可用" : "FFmpeg 不可用"}
              </dd>
              <dt>音频转写</dt>
              <dd>
                {health?.asr_configured
                  ? "已配置，调用结果见素材状态"
                  : "尚未配置"}
              </dd>
              <dt>影石 SDK</dt>
              <dd>未接入 · 可上传影石导出视频</dd>
              <dt>文件限制</dt>
              <dd>
                {health?.limits.max_assets} 个 / {health?.limits.max_duration_s}{" "}
                秒 / 单个 {health?.limits.max_upload_mb} MB
              </dd>
              {health?.model_destination && (
                <>
                  <dt>媒体发送目的地</dt>
                  <dd>{health.model_destination}</dd>
                </>
              )}
            </dl>
            <p className="dim">
              模型与密钥通过本地 .env
              配置。真实模式失败会直接显示错误。影石设备接入不影响本地视频上传。
            </p>
            <a
              className="small-button"
              href="http://127.0.0.1:8000/docs"
              target="_blank"
              rel="noreferrer"
            >
              查看本地 API 文档 <Icon name="arrow" size={14} />
            </a>
          </section>
        </div>
      )}
    </div>
  );
}
