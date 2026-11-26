export interface Session {
  id: string;
  token: string;
  pending?: { request_id: string; text: string };
}
export interface Config {
  allowed_extensions: string[];
  max_upload_bytes: number;
  max_duration_seconds: number;
  retention_hours: number;
}
export interface Message {
  id: string;
  role: "user" | "assistant" | "status";
  text: string;
  created_at?: string;
}
export interface Job {
  id: string;
  status:
    | "queued"
    | "analyzing"
    | "rendering"
    | "completed"
    | "failed"
    | "interrupted";
  events: { id: string; time: number; label: string }[];
  displayed_event_ids: string[];
  plan: { before_seconds: number; after_seconds: number };
  result: { url: string; download_url: string; revision: string } | null;
  error: string | null;
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
  ) {
    super(message);
  }
}
async function request<T>(
  path: string,
  session?: Session,
  init: RequestInit = {},
): Promise<T> {
  try {
    const response = await fetch(path, {
      ...init,
      headers: {
        ...(session ? { "X-Task-Token": session.token } : {}),
        ...init.headers,
      },
      referrerPolicy: "no-referrer",
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new ApiError(
        typeof body?.detail === "string"
          ? body.detail
          : "请求失败，请稍后重试。",
        response.status,
      );
    }
    return (await response.json()) as T;
  } catch (error) {
    if (
      error instanceof ApiError ||
      (error instanceof DOMException && error.name === "AbortError")
    )
      throw error;
    throw new ApiError("连接失败，请检查服务后重试。");
  }
}
const base = (s: Session) => "/api/jobs/" + encodeURIComponent(s.id);
export const api = {
  config: (signal?: AbortSignal) =>
    request<Config>("/api/config", undefined, { signal }),
  job: (s: Session, signal?: AbortSignal) =>
    request<Job>(base(s), s, { signal }),
  messages: (s: Session, signal?: AbortSignal) =>
    request<{ messages: Message[] }>(base(s) + "/messages", s, { signal }),
  send: (
    s: Session,
    body: { request_id: string; text: string },
    signal?: AbortSignal,
  ) =>
    request<{ status: string }>(base(s) + "/messages", s, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    }),
  upload: (
    file: File,
    onProgress: (value: number) => void,
    signal: AbortSignal,
  ) =>
    new Promise<Session>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const abort = () => xhr.abort();
      signal.addEventListener("abort", abort, { once: true });
      const cleanup = () => signal.removeEventListener("abort", abort);
      xhr.open("POST", "/api/jobs");
      xhr.responseType = "json";
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable)
          onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        cleanup();
        if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response);
        else
          reject(
            new ApiError(
              typeof xhr.response?.detail === "string"
                ? xhr.response.detail
                : "上传失败，请检查视频后重试。",
              xhr.status,
            ),
          );
      };
      xhr.onerror = () => {
        cleanup();
        reject(new ApiError("上传连接失败，请检查服务后重试。"));
      };
      xhr.onabort = () => {
        cleanup();
        reject(new DOMException("Aborted", "AbortError"));
      };
      const form = new FormData();
      form.append("file", file);
      if (signal.aborted) {
        cleanup();
        reject(new DOMException("Aborted", "AbortError"));
        return;
      }
      xhr.send(form);
    }),
};
export function mediaUrl(path: string, session: Session) {
  const url = new URL(path, window.location.origin);
  if (
    url.origin !== window.location.origin ||
    url.pathname !== "/api/jobs/" + encodeURIComponent(session.id) + "/result"
  )
    return "";
  url.searchParams.set("token", session.token);
  return url.pathname + url.search;
}
