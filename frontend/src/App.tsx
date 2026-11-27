import { useEffect, useRef, useState } from "react";
import { RoiEditor } from './RoiEditor';
import {
  api,
  ApiError,
  mediaUrl,
  type Config,
  type Job,
  type Message,
  type Session,
  type Rectangle,
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
  preparing_roi: "正在准备区域建议",
  awaiting_roi: "请确认识别区域",
  analyzing: "正在分析进球",
  rendering: "正在生成集锦",
  completed: "集锦已就绪",
  failed: "处理失败",
  interrupted: "处理已中断",
};
const jobLabel = (j: Job) => j.status === "completed" && !j.result
  ? "分析已完成，未生成集锦" : stages[j.status];
const active = (j: Job | null) =>
  !!j && ["queued", "preparing_roi", "analyzing", "rendering"].includes(j.status);
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
  const [picks, setPicks] = useState<string[]>([]);
  const requestedPreviews = useRef(new Set<string>());
  const selectionRequest = useRef<{key:string; id:string} | null>(null);
  const roiRequest = useRef<{key:string; id:string} | null>(null);
  const pickKey = JSON.stringify([session?.id,job?.events,job?.displayed_event_ids]);
  useEffect(() => {
    setPicks(job?.displayed_event_ids.length ? job.displayed_event_ids : (job?.events || []).filter(e => ["made","probable"].includes(e.label)).map(e => e.id));

  },[pickKey]);
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
    let reconnect: ReturnType<typeof setTimeout>;
    let streaming = false;
    async function watch() {
      try {
        await api.watch(session!, (snapshot) => {
          if (c.signal.aborted) return;
          streaming = true;
          setJob(snapshot.job);
          setMessages(snapshot.messages);
          setOffline(false);
          setUnavailable(false);
        }, c.signal);
      } catch (e) {
        if (c.signal.aborted) return;
        streaming = false;
        if (e instanceof ApiError && e.status === 404) {
          setUnavailable(true);
          setJob(null);
          setError("此视频已到期或访问凭证无效，请重新上传视频。");
          return;
        }
      }
      if (!c.signal.aborted) reconnect = setTimeout(() => void watch(), 2500);
    }
    async function poll() {
      if (streaming) {
        timer = setTimeout(poll, 2500);
        return;
      }
      try {
        const [j, m] = await Promise.all([
          api.job(session!, c.signal),
          api.messages(session!, c.signal),
        ]);
        if (c.signal.aborted) return;
        if (streaming) { timer = setTimeout(poll, 2500); return; }
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
    void watch();
    return () => {
      c.abort();
      clearTimeout(timer);
      clearTimeout(reconnect);
    };
  }, [session?.id, session?.token, uploading, refresh]);
  useEffect(() => {
    const pending = session?.pending;
    if (
      !pending ||
      !messages.some(
        (m) => m.role === "user" && m.request_id === pending.request_id,
      )
    )
      return;
    // A persisted user message proves the server durably accepted this request.
    const clean = { id: session.id, token: session.token };
    save(clean);
    setSession(clean);
    setText((value) => (value.trim() === pending.text ? "" : value));
  }, [messages, session]);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest", behavior: "auto" });
  }, [messages.length, local.length, job?.status]);
  function note(message: string) {
    setLocal((v) => [
      ...v,
      { id: crypto.randomUUID(), role: "assistant", text: message },
    ]);
  }
  useEffect(() => {
    if (!session || !job || active(job) || !job.events.some(e=>e.label!=="missed")) return;
    const candidates=job.events.filter(e=>e.label!=="missed");
    if (candidates.every(e=>job.candidate_clips?.[e.id]) || requestedPreviews.current.has(session.id)) return;
    requestedPreviews.current.add(session.id);
    const c=new AbortController();
    void api.prepareCandidates(session,c.signal).catch(e=>{if (!c.signal.aborted) setError(reason(e));});
    return ()=>c.abort();
  },[session?.id,job?.status,job?.events.length]);
  async function submitSelection() {
    if (!session || busy || !picks.length) return;
    const c = new AbortController();
    action.current?.abort(); action.current = c;
    const version = generation.current;
    const key = JSON.stringify(picks.slice().sort());
    if (selectionRequest.current?.key !== key) selectionRequest.current = {key,id:crypto.randomUUID()};
    setSending(true); setError("");
    try {
      await api.select(session,{request_id:selectionRequest.current.id,event_ids:picks},c.signal);
      if (c.signal.aborted || version !== generation.current) return;
      selectionRequest.current = null;
      setJob(j => j ? {...j,status:"queued"} : j);
      setRefresh(v => v+1);
    } catch(e) { if (!c.signal.aborted && version===generation.current) setError(reason(e)); }
    finally { if (version===generation.current) setSending(false); }
  }
  async function confirmRoi(roi:Rectangle,net_roi:Rectangle) {
    if(!session || busy) return;
    const c=new AbortController(); action.current?.abort(); action.current=c;
    const version=generation.current;
    const key=JSON.stringify([session.id,roi,net_roi]);
    if(roiRequest.current?.key!==key) roiRequest.current={key,id:crypto.randomUUID()};
    setSending(true);setError('');
    try {
      await api.confirmRoi(session,{request_id:roiRequest.current.id,roi,net_roi},c.signal);
      if(c.signal.aborted || version!==generation.current) return;
      roiRequest.current=null;
      requestedPreviews.current.delete(session.id);
      setJob(j=>j?{...j,status:'queued',events:[],displayed_event_ids:[],candidate_clips:{},result:null,roi:{...j.roi!,roi,net_roi,confirmed:true}}:j);
      setRefresh(v=>v+1);
    } catch(e) {if(!c.signal.aborted && version===generation.current) setError(reason(e));}
    finally {if(version===generation.current)setSending(false);}
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
    const isProgress = value === "查看进度";
    if (job?.roi && !job.roi.confirmed && !isProgress) {
      note('请先确认画面中的投篮分析区和篮网区域，然后我会开始识别。');
      return;
    }
    const isRetry = session.pending?.text === value;
    if (session.pending && !isProgress && !isRetry) {
      note("上一条剪辑指令尚未确认。请重发原指令，或查看进度后等待消息恢复。");
      return;
    }
    if (busy && !isProgress && !isRetry) {
      note("正在处理视频，完成后再修改。你可以输入“查看进度”。");
      return;
    }
    const body =
      session.pending?.text === value
        ? session.pending
        : { request_id: crypto.randomUUID(), text: value };
    const next = isProgress ? session : { ...session, pending: body };
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
      // Progress never replaces or clears an unresolved mutation.
      setSession((current) => {
        if (!current || current.id !== next.id) return current;
        const clean =
          !isProgress && current.pending?.request_id === body.request_id
            ? { id: current.id, token: current.token }
            : current;
        save(clean);
        return clean;
      });
      setText("");
      if (result.status === "queued")
        setJob((j) => (j ? { ...j, status: "queued" } : j));
      setRefresh((v) => v + 1);
    } catch (e) {
      if (!c.signal.aborted && version === generation.current)
        setError(
          reason(e) +
            (isProgress
              ? " 请重试查看进度。"
              : " 再次发送会复用本次请求，不重复调整时长。"),
        );
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
          {uploading ? "正在上传" : job ? jobLabel(job) : "准备好你的好球"}
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
          <p>上传后，请先确认投篮分析区和篮网区域。我会使用原项目的识别流程寻找候选。默认每球保留前 5 秒、后 2 秒，疑似进球可以逐条预览核对。</p>
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
                  上传后，先确认画面上的两个识别区域，再开始分析进球并生成集锦。
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
                <strong>{["analyzing", "rendering"].includes(job.status)
                  ? [...messages].reverse().find(m => m.role === "status")?.text || jobLabel(job)
                  : jobLabel(job)}</strong>
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
            {session && job?.roi && job.roi.width>0 && <RoiEditor
              key={session.id+JSON.stringify(job.roi)} value={job.roi}
              src={mediaUrl(`/api/jobs/${session.id}/source`,session)} disabled={busy}
              onConfirm={(roi,net)=>void confirmRoi(roi,net)}/>}
            {session?.pending && (
              <div className="notice" role="status">
                上一条剪辑指令尚未确认，可重发原指令或查看进度。确认前暂不接受其他修改。
                <button
                  onClick={() => {
                    setText(session.pending!.text);
                    field.current?.focus();
                  }}
                >
                  重发原指令
                </button>
              </div>
            )}
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            {job && session && job.events.some(e => e.label !== "missed") && (
              <article className="result">
                <h3>选择要保留的进球</h3>
                <p>确认进球是模型的高置信判断；疑似及不确定事件需要你核对。勾选只影响剪辑，不改变识别结论。</p>
                {job.events.some(e=>e.label!=="missed" && !job.candidate_clips?.[e.id]) && <p role="status">正在逐条生成独立候选视频，生成后会自动出现在这里。</p>}
                {job.events.filter(e => e.label !== "missed" && job.candidate_clips?.[e.id]).sort((a,b)=>a.time-b.time).map((e,i) => {
                  const clip=job.candidate_clips?.[e.id];
                  return <article className="candidate-message" key={e.id} aria-label={`候选消息 ${i+1}`}>
                    <p>好球助手 · 候选 {i+1} · 原片 {time(e.time)} · {e.label==="made"?"模型确认":e.label==="probable"?"疑似进球":"不确定"}</p>
                    {clip?.status==="ready" && clip.url ? <video aria-label={`候选 ${i+1} 独立视频`} controls preload="none"
                      src={mediaUrl(clip.url,session)} onError={()=>setError(`候选 ${i+1} 视频播放失败，请刷新重试。`)} />
                      : <p role="status">{clip?.error || "正在准备这条候选的独立短视频…"}</p>}
                    <label><input type="checkbox" aria-label={`候选 ${i+1} ${time(e.time)}`} checked={picks.includes(e.id)} disabled={busy}
                      onChange={v=>setPicks(old=>v.target.checked?[...old,e.id]:old.filter(id=>id!==e.id))}/>保留这条候选</label>
                  </article>;
                })}
                <button type="button" disabled={busy} onClick={()=>void api.prepareCandidates(session).catch(e=>setError(reason(e)))}>重新准备候选短视频</button>
                <button type="button" className="send" disabled={busy || !picks.length} onClick={() => void submitSelection()}>
                  按选择生成集锦（{picks.length}）</button>
              </article>
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
                      <span>{e.label === "probable" ? "疑似进球" : e.label === "made" ? "确认进球" : "用户选入·不确定"}</span>
                      <time>{time(e.time)}</time>
                    </li>
                  ))}
                </ol>
                <p className="result-hint">
                  时间点对应原视频。疑似进球尚未确认命中，可说“去掉第几球”排除。
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
                    ((busy || !!session?.pending) && e !== "查看进度")
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
                  ((busy || !!session?.pending) &&
                    text.trim() !== "查看进度" &&
                    text.trim() !== session?.pending?.text)
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
