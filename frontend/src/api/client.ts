import type { Job } from "../types";

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch("/api/v1" + path, { ...options, headers });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "请求失败");
  return data as T;
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
      headers: { "Idempotency-Key": crypto.randomUUID() },
    },
  );
}

export function watchJob(id: string, onUpdate: (job: Job) => void) {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stream = new EventSource(`/api/v1/jobs/${id}/events`);
  const deliver = (job: Job) => {
    if (stopped) return;
    onUpdate(job);
    if (["succeeded", "failed", "cancelled"].includes(job.status)) {
      stream.close();
      stopped = true;
    }
  };
  const poll = async () => {
    try {
      deliver(await api<Job>(`/jobs/${id}`));
    } catch {
      /* Retry transport failures without altering actual task state. */
    }
    if (!stopped) timer = setTimeout(poll, 2000);
  };
  stream.onmessage = (e) => deliver(JSON.parse(e.data));
  stream.onerror = () => {
    stream.close();
    void poll();
  };
  return () => {
    stopped = true;
    stream.close();
    if (timer) clearTimeout(timer);
  };
}

export const time = (seconds: number) =>
  `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`;
