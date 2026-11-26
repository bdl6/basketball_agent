import { useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  mediaUrl,
  type Config,
  type Job,
  type Message,
  type Session,
} from "./api";
const KEY = "basketball-session";
function restore(): Session | null {
  try {
    const s = JSON.parse(localStorage.getItem(KEY) || "null");
    return typeof s?.id === "string" && typeof s?.token === "string" ? s : null;
  } catch {
    return null;
  }
}
function save(s: Session) {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* Current tab remains usable when storage is unavailable. */
  }
}
const stages: Record<Job["status"], string> = {
  queued: "等待处理",
  analyzing: "正在分析进球",
  rendering: "正在生成集锦",
  completed: "集锦已就绪",
  failed: "处理失败",
  interrupted: "处理已中断",
};
const active = (j: Job | null) =>
  !!j && ["queued", "analyzing", "rendering"].includes(j.status);
const examples = [
  "每球前面改成 8 秒",
  "每球后面多留 1 秒",
  "去掉第二球",
  "查看进度",
];
function time(seconds: number) {
  return (
    String(Math.floor(seconds / 60)).padStart(2, "0") +
    ":" +
    (seconds % 60).toFixed(1).padStart(4, "0")
  );
}
function reason(e: unknown) {
  return e instanceof Error ? e.message : "请求失败，请重试。";
}
export default function App() {
  const [session, setSession] = useState<Session | null>(restore);
  const [config, setConfig] = useState<Config | null>(null),
    [configError, setConfigError] = useState(false);
  const [job, setJob] = useState<Job | null>(null),
    [messages, setMessages] = useState<Message[]>([]),
    [local, setLocal] = useState<Message[]>([]);
  const [text, setText] = useState(session?.pending?.text || ""),
    [error, setError] = useState(""),
    [offline, setOffline] = useState(false),
    [unavailable, setUnavailable] = useState(false);
  const [uploading, setUploading] = useState(false),
    [progress, setProgress] = useState(0),
    [sending, setSending] = useState(false),
    [replacement, setReplacement] = useState<File | null>(null),
    [refresh, setRefresh] = useState(0);
  const input = useRef<HTMLInputElement>(null),
    field = useRef<HTMLTextAreaElement>(null),
    action = useRef<AbortController | null>(null),
    generation = useRef(0),
    end = useRef<HTMLDivElement>(null);
  const busy =
    uploading || sending || active(job) || (!!session && !job && !unavailable);
  useEffect(() => {
    const c = new AbortController();
    api
      .config(c.signal)
      .then(setConfig)
      .catch(() => {
        if (!c.signal.aborted) setConfigError(true);
      });
    return () => c.abort();
  }, []);
  useEffect(
    () => () => {
      generation.current++;
      action.current?.abort();
    },
    [],
  );
  useEffect(() => {
    if (!session || uploading) return;
    const c = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [j, m] = await Promise.all([
          api.job(session!, c.signal),
          api.messages(session!, c.signal),
        ]);
        if (c.signal.aborted) return;
        setJob(j);
        setMessages(m.messages);
        setOffline(false);
        setUnavailable(false);
      } catch (e) {
        if (c.signal.aborted) return;
        setOffline(true);
        if (e instanceof ApiError && e.status === 404) {
          setUnavailable(true);
          setOffline(false);
          setJob(null);
          setError("此视频已到期或访问凭证无效，请重新上传视频。");
          return;
        }
      }
      if (!c.signal.aborted) timer = setTimeout(poll, 2500);
    }
    void poll();
    return () => {
      c.abort();
      clearTimeout(timer);
    };
  }, [session?.id, session?.token, uploading, refresh]);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest", behavior: "auto" });
  }, [messages.length, local.length, job?.status]);
  function note(message: string) {
    setLocal((v) => [
      ...v,
      { id: crypto.randomUUID(), role: "assistant", text: message },
    ]);
  }
  async function upload(file: File) {
    if (!config) {
      note("无法读取上传限制，请确认服务可用后刷新页面。");
      return;
    }
    if (
      !config.allowed_extensions.some((ext) =>
        file.name.toLowerCase().endsWith(ext.toLowerCase()),
      )
    ) {
      note(
        "不支持此格式，请选择 " +
          config.allowed_extensions.join("、") +
          " 视频。",
      );
      return;
    }
    if (file.size > config.max_upload_bytes) {
      note(
        "视频超过 " +
          (config.max_upload_bytes / 1048576).toFixed(1) +
          " MB 限制，请缩短后上传。",
      );
      return;
    }
    if (session && !replacement) {
      setReplacement(file);
      return;
    }
    setReplacement(null);
    const version = ++generation.current;
    action.current?.abort();
    const c = new AbortController();
    action.current = c;
    setUploading(true);
    setProgress(0);
    setError("");
    try {
      const s = await api.upload(
        file,
        (p) => {
          if (version === generation.current) setProgress(p);
        },
        c.signal,
      );
      if (version !== generation.current) return;
      save(s);
      setSession(s);
      setJob(null);
      setMessages([]);
      setLocal([
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: "已收到，正在检查视频",
        },
      ]);
      setUnavailable(false);
      setText("");
    } catch (e) {
      if (!c.signal.aborted && version === generation.current)
        setError(reason(e));
    } finally {
      if (version === generation.current) setUploading(false);
    }
  }
  async function send() {
    const value = text.trim();
    if (!value || sending) return;
    if (!session) {
      note("请先上传一段视频，再告诉我怎样剪辑。");
      setText("");
      return;
    }
    if (unavailable) return;
    if (busy && value !== "查看进度") {
      note("正在处理视频，完成后再修改。你可以输入“查看进度”。");
      return;
    }
    const body =
      session.pending?.text === value
        ? session.pending
        : { request_id: crypto.randomUUID(), text: value };
    const next = { ...session, pending: body };
    save(next);
    setSession(next);
    const version = generation.current,
      c = new AbortController();
    action.current = c;
    setSending(true);
    setError("");
    try {
      const result = await api.send(next, body, c.signal);
      if (version !== generation.current) return;
      const clean = { id: next.id, token: next.token };
      save(clean);
      setSession(clean);
      setText("");
      if (result.status === "queued")
        setJob((j) => (j ? { ...j, status: "queued" } : j));
      setRefresh((v) => v + 1);
    } catch (e) {
      if (!c.signal.aborted && version === generation.current)
        setError(reason(e) + " 再次发送会复用本次请求，不重复调整时长。");
    } finally {
      if (version === generation.current) setSending(false);
    }
  }
  const visible =
    job?.displayed_event_ids
      .map((id) => job.events.find((e) => e.id === id))
      .filter((e): e is NonNullable<typeof e> => !!e) || [];
  return (
    <div className="app">
      <header className="masthead">
        <a className="brand" href="#chat" aria-label="好球，前往聊天">
          <svg viewBox="0 0 60 60" aria-hidden="true">
            <circle cx="30" cy="30" r="27" />
            <path d="M3 30h54M30 3v54M11 11c26 6 26 32 38 38M49 11C23 17 23 43 11 49" />
          </svg>
          <span>
            好球<span className="brand-sub">篮球进球剪辑助手</span>
          </span>
        </a>
        <span className={"stage " + (busy ? "working" : "")}>
          {uploading ? "正在上传" : job ? stages[job.status] : "准备好你的好球"}
        </span>
      </header>
      <main className="layout">
        <aside className="guide">
          <h1>
            留下进球，
            <br />
            把精彩连起来。
          </h1>
          <p className="welcome">
            你好，我是篮球进球剪辑助手。我可以从固定机位、篮筐清晰的篮球视频中寻找可靠进球，生成可播放、下载的集锦。请先点击下方按钮上传一段短视频。
          </p>
          <p>默认每球保留前 5 秒、后 2 秒。识别不清楚的球不会自动加入集锦。</p>
          <div className="upload-box">
            <label
              className={"upload-button " + (busy || !config ? "disabled" : "")}
              htmlFor="video-upload"
            >
              {session ? "上传新视频" : "上传篮球视频"}
              <span aria-hidden="true">＋</span>
            </label>
            <input
              ref={input}
              id="video-upload"
              aria-label="选择篮球视频"
              className="file-input"
              type="file"
              accept={config?.allowed_extensions.join(",") || "video/*"}
              disabled={busy || !config}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) void upload(f);
              }}
            />
            {config ? (
              <p className="limits">
                {config.allowed_extensions.join(" / ")}
                <br />
                最大 {(config.max_upload_bytes / 1048576).toFixed(
                  1,
                )} MB，最长 {config.max_duration_seconds} 秒<br />
                视频保留 {config.retention_hours} 小时
              </p>
            ) : (
              <p className="limits">
                {configError
                  ? "无法读取上传限制，请检查服务后刷新页面。"
                  : "正在读取上传限制…"}
              </p>
            )}
          </div>
          <p className="guide-foot">
            生成后，直接说出你的剪辑要求。
            <br />
            例如：“去掉第二球，每球前面多留三秒”。
          </p>
        </aside>
        <section id="chat" className="chat" aria-label="篮球剪辑聊天">
          <div className="chat-heading">
            <h2>剪辑对话</h2>
            <span>一个视频，一次好球集锦</span>
          </div>
          <div
            className="conversation"
            role="log"
            aria-label="聊天消息"
            aria-live="polite"
          >
            {!session && !local.length && (
              <div className="empty">
                <span className="court-mark" aria-hidden="true">
                  ⌒
                </span>
                <h3>从一段球场视频开始</h3>
                <p>
                  上传后，我会分析进球并自动生成集锦。
                  <br />
                  剪辑完成后，还可以在这里调整。
                </p>
              </div>
            )}
            {[...messages, ...local].map((m) => (
              <article key={m.id} className={"message " + m.role}>
                <span className="speaker">
                  {m.role === "user" ? "你" : "好球助手"}
                </span>
                <p>{m.text}</p>
              </article>
            ))}
            {uploading && (
              <div className="notice" role="status">
                <strong>
                  {progress === 100
                    ? "上传完成，正在检查视频"
                    : "正在上传视频 " + progress + "%"}
                </strong>
                <progress max="100" value={progress} aria-label="上传进度" />
              </div>
            )}
            {job && (
              <div className={"notice " + job.status} role="status">
                <strong>{stages[job.status]}</strong>
                {active(job) && <p>完成后会自动更新。处理期间可以查看进度。</p>}
                {job.error && <p>{job.error}</p>}
                {job.status === "interrupted" && (
                  <p>服务曾中断，请重新上传视频。</p>
                )}
              </div>
            )}
            {offline && (
              <div className="error" role="alert">
                暂时无法更新进度，正在尝试重新连接。
                <button onClick={() => setRefresh((v) => v + 1)}>
                  立即重试
                </button>
              </div>
            )}
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            {job?.result && session && (
              <article className="result">
                <div className="result-heading">
                  <div>
                    <h3>你的进球集锦</h3>
                    <p>
                      {visible.length} 个进球
                      {active(job) || job.status === "failed"
                        ? " · 上一份可用集锦"
                        : ""}
                    </p>
                  </div>
                  <a
                    className="download"
                    href={mediaUrl(job.result.download_url, session)}
                    download
                    referrerPolicy="no-referrer"
                  >
                    下载集锦
                  </a>
                </div>
                <video
                  key={job.result.revision}
                  aria-label="进球集锦播放器"
                  controls
                  preload="metadata"
                  src={mediaUrl(job.result.url, session)}
                  onError={() =>
                    setError(
                      "视频暂时无法播放，请尝试下载，或重新连接服务后刷新。",
                    )
                  }
                />
                <ol className="events" aria-label="当前集锦进球">
                  {visible.map((e, i) => (
                    <li key={e.id}>
                      <span>第 {i + 1} 球</span>
                      <time>{time(e.time)}</time>
                    </li>
                  ))}
                </ol>
                <p className="result-hint">
                  时间点对应原视频。用“第几球”告诉我需要去掉哪一球。
                </p>
              </article>
            )}
            <div ref={end} />
          </div>
          <div className="composer">
            <div className="shortcuts" aria-label="快捷指令">
              {examples.map((e) => (
                <button
                  key={e}
                  disabled={
                    (e === "去掉第二球" && !job?.result) ||
                    (busy && e !== "查看进度")
                  }
                  onClick={() => {
                    setText(e);
                    field.current?.focus();
                  }}
                >
                  {e}
                </button>
              ))}
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void send();
              }}
            >
              <label className="sr-only" htmlFor="instruction">
                剪辑要求
              </label>
              <textarea
                ref={field}
                id="instruction"
                value={text}
                maxLength={2000}
                rows={2}
                placeholder={
                  busy
                    ? "正在处理，可输入“查看进度”"
                    : "告诉我怎样剪辑，例如：每球前面改成 8 秒"
                }
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (
                    e.key === "Enter" &&
                    !e.shiftKey &&
                    !e.nativeEvent.isComposing
                  ) {
                    e.preventDefault();
                    void send();
                  }
                }}
              />
              <button
                className="send"
                type="submit"
                disabled={
                  !text.trim() ||
                  sending ||
                  unavailable ||
                  (busy && text.trim() !== "查看进度")
                }
              >
                {sending ? "发送中" : "发送"}
              </button>
            </form>
            <p className="composer-hint">
              {busy
                ? "处理期间仅支持“查看进度”。"
                : "Enter 发送，Shift + Enter 换行。仅支持时长调整、去掉进球与查看进度。"}
            </p>
          </div>
        </section>
      </main>
      {replacement && (
        <div className="modal-backdrop">
          <section
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setReplacement(null);
                input.current?.focus();
              }
              if (e.key === "Tab") {
                const buttons = e.currentTarget.querySelectorAll("button");
                const first = buttons[0],
                  last = buttons[buttons.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                  e.preventDefault();
                  last.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first.focus();
                }
              }
            }}
            role="dialog"
            aria-modal="true"
            aria-labelledby="reset-title"
            className="reset-dialog"
          >
            <h2 id="reset-title">开始新视频？</h2>
            <p>
              上传“{replacement.name}
              ”后将重置当前聊天上下文。当前视频不会与新视频混合剪辑。
            </p>
            <div>
              <button autoFocus onClick={() => setReplacement(null)}>
                保留当前视频
              </button>
              <button className="send" onClick={() => void upload(replacement)}>
                上传并开始新视频
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
