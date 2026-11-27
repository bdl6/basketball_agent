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
  request_id?: string | null;
}
export interface Job {
  id: string;
  status:
    | "queued"
    | "preparing_roi"
    | "awaiting_roi"
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
  candidate_clips?: Record<string,{status:"ready"|"failed";url?:string;error?:string}>;
  roi?: RoiState | null;
}
export interface Rectangle { x1:number; y1:number; x2:number; y2:number }
export interface RoiState {
  width:number; height:number; duration_seconds:number;
  roi:Rectangle|null; net_roi:Rectangle|null; confirmed:boolean;
  preview_time_seconds?:number; warning?:string;
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
export interface ProgressSnapshot { job: Job; messages: Message[] }
async function watchProgress(session: Session, receive: (data: ProgressSnapshot) => void, signal: AbortSignal): Promise<void> {
  const response = await fetch(base(session) + "/events", {
    headers: { "X-Task-Token": session.token, Accept: "text/event-stream" },
    signal, referrerPolicy: "no-referrer", cache: "no-store",
  });
  if (!response.ok) throw new ApiError("进度连接失败", response.status);
  if (!response.body) throw new ApiError("浏览器不支持进度推送");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (!signal.aborted) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, {stream: true});
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (frame.startsWith(":")) continue;
        if (frame.includes("event: expired")) throw new ApiError("任务已过期", 404);
        const data = frame.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
        if (data && frame.includes("event: snapshot")) receive(JSON.parse(data) as ProgressSnapshot);
      }
    }
  } finally { reader.releaseLock(); }
  if (!signal.aborted) throw new ApiError("进度连接已断开");
}
export const api = {
  confirmRoi: (s:Session, body:{request_id:string;roi:Rectangle;net_roi:Rectangle}, signal?:AbortSignal) =>
    request<{status:string}>(base(s)+"/roi",s,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body),signal}),
  prepareCandidates: (s:Session,signal?:AbortSignal) => request<{status:string}>(base(s)+"/candidates",s,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({request_id:crypto.randomUUID()}),signal}),
  select: (s: Session, body: {request_id: string; event_ids: string[]}, signal?: AbortSignal) =>
    request<{status:string}>(base(s)+"/selection",s,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body),signal}),
  watch: watchProgress,
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
    !(["/result", "/source"].some(suffix => url.pathname === "/api/jobs/" + encodeURIComponent(session.id) + suffix)
      || (url.pathname.startsWith("/api/jobs/"+encodeURIComponent(session.id)+"/candidates/")
        && url.pathname.slice(("/api/jobs/"+encodeURIComponent(session.id)+"/candidates/").length).length>0
        && !url.pathname.slice(("/api/jobs/"+encodeURIComponent(session.id)+"/candidates/").length).includes("/")))
  )
    return "";
  url.searchParams.set("token", session.token);
  return url.pathname + url.search;
}
