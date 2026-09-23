import type { Job } from "../types";
import { createIdempotencyKey } from "./idempotency";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let sessionRevision = 0;
const pendingRequests = new Set<AbortController>();
const activeStreams = new Set<() => void>();

export function clearSessionRequests() {
  sessionRevision += 1;
  pendingRequests.forEach((controller) => controller.abort());
  pendingRequests.clear();
  activeStreams.forEach((stop) => stop());
  activeStreams.clear();
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("X-Requested-With", "XMLHttpRequest");
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const controller = new AbortController();
  const revision = sessionRevision;
  const abort = () => controller.abort();
  if (options.signal?.aborted) controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  pendingRequests.add(controller);
  try {
    const response = await fetch("/api/v1" + path, {
      ...options,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (revision !== sessionRevision || controller.signal.aborted)
      throw new DOMException("会话已切换", "AbortError");
    if (!response.ok) {
      if (response.status === 401 && !path.startsWith("/auth/"))
        window.dispatchEvent(new Event("xuguangji:unauthorized"));
      throw new ApiError(
        data.message || "请求失败，请稍后重试。",
        response.status,
      );
    }
    return data as T;
  } finally {
    pendingRequests.delete(controller);
    options.signal?.removeEventListener("abort", abort);
  }
}
export const post = <T>(path: string, body: unknown = {}, key?: string) =>
  api<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: key ? { "Idempotency-Key": key } : undefined,
  });
export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export async function upload(projectId: string, file: File, source: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("source_type", source);
  return api<{ asset_id: string; job_id: string }>(
    `/projects/${projectId}/assets`,
    {
      method: "POST",
      body: form,
      headers: { "Idempotency-Key": createIdempotencyKey() },
    },
  );
}

export function watchJob(id: string, onUpdate: (job: Job) => void) {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stream = new EventSource(`/api/v1/jobs/${id}/events`);
  const stop = () => {
    stopped = true;
    stream.close();
    if (timer) clearTimeout(timer);
    activeStreams.delete(stop);
  };
  activeStreams.add(stop);
  const deliver = (job: Job) => {
    if (stopped) return;
    onUpdate(job);
    if (["succeeded", "failed", "cancelled"].includes(job.status)) {
      stop();
    }
  };
  const poll = async () => {
    if (stopped) return;
    try {
      deliver(await api<Job>(`/jobs/${id}`));
    } catch {
      /* Retry transport failures without altering actual task state. */
    }
    if (!stopped) timer = setTimeout(poll, 2000);
  };
  stream.onmessage = (e) => deliver(JSON.parse(e.data));
  stream.onerror = () => {
    if (stopped) return;
    stream.close();
    void poll();
  };
  return stop;
}

export const time = (seconds: number) =>
  `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`;
