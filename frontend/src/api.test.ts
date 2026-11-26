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
