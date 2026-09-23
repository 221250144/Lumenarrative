import { useState, useEffect, useCallback, useRef } from "react";
import {
  api,
  post,
  patch,
  upload,
  watchJob,
  ApiError,
  clearSessionRequests,
} from "../api/client";
import { createIdempotencyKey } from "../api/idempotency";
import type {
  Project,
  Asset,
  Analysis,
  Diagnosis,
  Plan,
  Job,
  Health,
} from "../types";
import { Icon } from "../components/Icon";
import { NotificationCenter } from "../components/NotificationCenter";
import { copyText } from "../lib/clipboard";
import { Projects } from "./Projects";
import { Workbench } from "./Workbench";
import { Tasks } from "./Tasks";
import { Auth } from "./Auth";
import { AccountMenu, type User } from "../components/AccountMenu";

type Page = "projects" | "workspace" | "tasks";
const SESSION_NOTICE = "xuguangji.session-change";
function announceSessionChange() {
  try {
    localStorage.setItem(SESSION_NOTICE, `${Date.now()}-${Math.random()}`);
  } catch {
    /* Storage is optional. */
  }
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [version, setVersion] = useState(0);
  const [authError, setAuthError] = useState("");
  const [unavailable, setUnavailable] = useState(false);
  const initialProject = useRef(
    new URLSearchParams(window.location.search).get("project") || "",
  );
  const discardProject = useCallback(() => {
    initialProject.current = "";
    window.history.replaceState({}, "", "/");
    try {
      Object.keys(sessionStorage)
        .filter((key) => key.startsWith("xuguangji.generation."))
        .forEach((key) => sessionStorage.removeItem(key));
    } catch {
      /* Storage may be disabled. */
    }
  }, []);
  const loadSession = useCallback(async () => {
    setChecking(true);
    setUnavailable(false);
    setAuthError("");
    try {
      setUser(await api<User>("/auth/me"));
      setVersion((current) => current + 1);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setUser(null);
      if (e instanceof ApiError && e.status === 401) discardProject();
      else {
        setUnavailable(true);
        setAuthError("暂时无法连接服务，请重试。");
      }
    }
    setChecking(false);
  }, [discardProject]);
  useEffect(() => {
    void loadSession();
    const unauthorized = () => {
      clearSessionRequests();
      discardProject();
      setUser(null);
      setChecking(false);
      setAuthError("登录已失效，请重新登录。");
    };
    const changed = (event: StorageEvent) => {
      if (event.key !== SESSION_NOTICE) return;
      clearSessionRequests();
      discardProject();
      setUser(null);
      void loadSession();
    };
    window.addEventListener("xuguangji:unauthorized", unauthorized);
    window.addEventListener("storage", changed);
    return () => {
      clearSessionRequests();
      window.removeEventListener("xuguangji:unauthorized", unauthorized);
      window.removeEventListener("storage", changed);
    };
  }, [discardProject, loadSession]);
  if (checking)
    return (
      <div className="auth-page">
        <div className="session-loading" role="status">
          <span className="spinner" />
          正在打开创作空间…
        </div>
      </div>
    );
  if (unavailable)
    return (
      <div className="auth-page">
        <div className="auth-card">
          <p className="form-error" role="alert">
            {authError}
          </p>
          <button
            className="primary full-width"
            onClick={() => void loadSession()}
          >
            重新连接
          </button>
        </div>
      </div>
    );
  if (!user)
    return (
      <Auth
        message={authError}
        onAuthenticated={(next) => {
          clearSessionRequests();
          discardProject();
          setAuthError("");
          setUser(next);
          setVersion((current) => current + 1);
          announceSessionChange();
        }}
      />
    );
  return (
    <Workspace
      key={`${user.id}:${version}`}
      user={user}
      initialProjectId={initialProject.current}
      accountError={authError}
      onLogout={async () => {
        setChecking(true);
        clearSessionRequests();
        discardProject();
        try {
          await post("/auth/logout");
          setUser(null);
          setAuthError("");
          announceSessionChange();
        } catch {
          setAuthError("退出登录失败，请点击右上角账号重试。");
          setVersion((current) => current + 1);
        } finally {
          setChecking(false);
        }
      }}
    />
  );
}

function Workspace({
  user,
  initialProjectId,
  accountError,
  onLogout,
}: {
  user: User;
  initialProjectId: string;
  accountError: string;
  onLogout: () => void;
}) {
  const [projectId, setProjectId] = useState(initialProjectId);
  const [page, setPage] = useState<Page>(projectId ? "workspace" : "projects");
  const [health, setHealth] = useState<Health | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(accountError);
  const [toast, setToast] = useState("");
  const activeProject = useRef(projectId);
  const refreshSequence = useRef(0);
  const alive = useRef(true);
  const pendingWaits = useRef(new Set<() => void>());
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      refreshSequence.current += 1;
      pendingWaits.current.forEach((stop) => stop());
      pendingWaits.current.clear();
    };
  }, []);
  const refresh = useCallback(async () => {
    if (!alive.current) return;
    const sequence = ++refreshSequence.current;
    const all = await api<Project[]>("/projects");
    if (!alive.current || sequence !== refreshSequence.current) return;
    setProjects(all);
    if (!projectId) return;
    if (!all.some((item) => item.id === projectId)) {
      setProjectId("");
      activeProject.current = "";
      setProject(null);
      setAssets([]);
      setDiagnosis(null);
      setPlans([]);
      setJobs([]);
      setPage("projects");
      window.history.replaceState({}, "", "/");
      setError("该项目不存在，或不属于当前账号。");
      return;
    }
    const [p, a, r, pl, j] = await Promise.all([
      api<Project>(`/projects/${projectId}`),
      api<Asset[]>(`/projects/${projectId}/assets`),
      api<Analysis[]>(`/projects/${projectId}/analyses`),
      api<Plan[]>(`/projects/${projectId}/completion-plans`),
      api<Job[]>(`/projects/${projectId}/jobs`),
    ]);
    if (
      !alive.current ||
      activeProject.current !== projectId ||
      sequence !== refreshSequence.current
    )
      return;
    setProject(p);
    setAssets(a);
    setPlans(pl);
    setJobs(j.filter((job) => job.type !== "render"));
    const latest =
      p.latest_analysis_id || r.find((run) => run.status === "succeeded")?.id;
    const d = latest
      ? await api<Diagnosis>(`/analyses/${latest}/diagnosis`)
      : null;
    if (
      alive.current &&
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
      if (!alive.current) return;
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
    setJobs([]);
    setError("");
    setToast("");
    setPage("workspace");
    window.history.replaceState({}, "", `?project=${encodeURIComponent(id)}`);
  }
  function navigate(next: Page) {
    setPage(next);
    if (next === "projects") {
      setProjectId("");
      activeProject.current = "";
      setProject(null);
      setDiagnosis(null);
      setAssets([]);
      setPlans([]);
      setJobs([]);
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
      const cancel = () => {
        stop();
        reject(new DOMException("会话已关闭", "AbortError"));
      };
      const stop = watchJob(id, (job) => {
        if (["succeeded", "failed", "cancelled"].includes(job.status))
          pendingWaits.current.delete(cancel);
        if (job.status === "succeeded") resolve();
        if (["failed", "cancelled"].includes(job.status))
          reject(new Error(job.error_message || "处理未完成"));
      });
      pendingWaits.current.add(cancel);
    });
  async function submit(task: string, asset: string) {
    await post(
      `/completion-tasks/${task}/submissions`,
      { asset_id: asset },
      createIdempotencyKey(),
    );
  }
  const canUse =
    !!diagnosis?.vlog &&
    project?.input_mode === "vlog" &&
    diagnosis.vlog.primary_asset_id ===
      project.constraints_json.primary_asset_id &&
    !diagnosis.analysis.stale &&
    diagnosis.analysis.status === "succeeded";
  return (
    <div
      className={
        "app-shell" + (page === "workspace" && project ? " review-layout" : "")
      }
    >
      <aside className="sidebar">
        <button className="brand" onClick={() => navigate("projects")}>
          <span className="brand-mark">
            <Icon name="sun" size={27} />
          </span>
          <span>
            旭光集<small>LUMENARRATIVE</small>
          </span>
        </button>
        <div className="space-label">
          <span className="space-avatar">旭</span>
          <div>我的创作空间</div>
        </div>
        <nav>
          {(
            [
              ["projects", "grid", "我的项目"],
              ["workspace", "spark", "Vlog 审看"],
              ["tasks", "layers", "补拍与重剪"],
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
          <div className="topbar-actions">
            {health?.provider === "mock" && (
              <span className="mode-badge demo">
                <i />
                演示数据
              </span>
            )}
            <AccountMenu user={user} onLogout={onLogout} />
          </div>
        </header>
        <main
          className={
            "main-content" +
            (page === "workspace" && project ? " review-content" : "")
          }
        >
          {page === "projects" ? (
            <Projects
              projects={projects}
              onOpen={open}
              busy={!!busy}
              isDemo={health?.provider === "mock"}
              onRename={async (id, title) => {
                await patch(`/projects/${id}`, { title });
                await refreshRef.current();
                setToast("项目名称已更新");
              }}
              onDelete={async (id) => {
                await api(`/projects/${id}`, { method: "DELETE" });
                await refreshRef.current();
                setToast("项目已删除");
              }}
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
                  if (!alive.current) return;
                  await waitJob(result.job_id);
                  if (!alive.current) return;
                  await submit(task, result.asset_id);
                })
              }
              onCopy={(text) =>
                act("复制建议", async () => {
                  await copyText(text);
                  setToast("已复制，可粘贴到剪辑备忘或其他软件中");
                })
              }
            />
          ) : null}
        </main>
      </div>
      <NotificationCenter
        jobs={page === "projects" ? [] : jobs}
        busy={busy}
        error={error}
        toast={toast}
        isDemo={health?.provider === "mock"}
        onDismissError={() => setError("")}
        onRetry={(job) =>
          void act("重试任务", () => post(`/jobs/${job.id}/retry`))
        }
      />
    </div>
  );
}
