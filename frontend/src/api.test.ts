import { TextEncoder, TextDecoder } from "node:util";
import { beforeEach, expect, test, vi } from "vitest";
import { api, ApiError, mediaUrl } from "./api";
const session = { id: "one", token: "secret" };
beforeEach(() => vi.unstubAllGlobals());
test("protects JSON requests with a header and never adds credentials to their URL", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => ({ id: "one" }) });
  vi.stubGlobal("fetch", fetch);
  await api.job(session);
  expect(fetch).toHaveBeenCalledWith(
    "/api/jobs/one",
    expect.objectContaining({
      headers: { "X-Task-Token": "secret" },
      referrerPolicy: "no-referrer",
    }),
  );
});
test("preserves HTTP errors for expired-session recovery", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ detail: "找不到视频" }),
      }),
  );
  await expect(api.job(session)).rejects.toMatchObject({
    status: 404,
    message: "找不到视频",
  });
});
test("validates media origin before attaching a secret", () => {
  expect(mediaUrl("https://outside.example/api/jobs/one/result", session)).toBe(
    "",
  );
  expect(mediaUrl("/api/jobs/other/result", session)).toBe("");
  expect(mediaUrl("/api/jobs/one/result?revision=r1", session)).toBe(
    "/api/jobs/one/result?revision=r1&token=secret",
  );
});
test("network errors have actionable copy", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
  );
  await expect(api.config()).rejects.toBeInstanceOf(ApiError);
  await expect(api.config()).rejects.toThrow("连接失败");
});


test("progress stream decodes split frames and keeps token in header", async () => {
  vi.stubGlobal("TextDecoder", TextDecoder);
  const encoder = new TextEncoder();
  const frame = 'event: snapshot\ndata: {"job":{"status":"analyzing"},"messages":[{"text":"定位完成"}]}\n\n';
  const bytes = encoder.encode(frame);
  let n=0;
  const read = vi.fn(async () => ++n===1 ? {done:false,value:bytes.slice(0,28)} : n===2 ? {done:false,value:bytes.slice(28)} : {done:true});
  const fetch=vi.fn().mockResolvedValue({ok:true,body:{getReader:()=>({read,releaseLock:vi.fn()})}});
  vi.stubGlobal("fetch",fetch);
  const receive=vi.fn();
  await expect(api.watch(session,receive,new AbortController().signal)).rejects.toThrow();
  expect(receive).toHaveBeenCalledWith(expect.objectContaining({messages:[{text:"定位完成"}]}));
  expect(fetch).toHaveBeenCalledWith('/api/jobs/one/events',expect.objectContaining({headers:expect.objectContaining({'X-Task-Token':'secret'})}));
});
