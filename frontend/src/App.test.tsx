import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, test, expect, beforeEach } from "vitest";
import App from "./App";
import { api } from "./api";
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  api: {
    config: vi.fn(),
    upload: vi.fn(),
    job: vi.fn(),
    messages: vi.fn(),
    send: vi.fn(),
  },
}));
const mock = api as any;
const config = {
  allowed_extensions: [".mp4"],
  max_upload_bytes: 1024,
  max_duration_seconds: 30,
  retention_hours: 24,
};
const completed = {
  id: "one",
  status: "completed",
  events: [
    { id: "e2", time: 25, label: "made" },
    { id: "e1", time: 12.5, label: "made" },
  ],
  displayed_event_ids: ["e1", "e2"],
  plan: { before_seconds: 5, after_seconds: 2 },
  result: {
    url: "/api/jobs/one/result?revision=r1",
    download_url: "/api/jobs/one/result?revision=r1&download=1",
    revision: "r1",
  },
  error: null,
};
beforeEach(() => {
  vi.clearAllMocks();
  mock.config.mockResolvedValue(config);
  mock.job.mockResolvedValue(completed);
  mock.messages.mockResolvedValue({ messages: [] });
  mock.send.mockResolvedValue({ status: "queued" });
});
test("welcome and upload guidance render even when service is unavailable", async () => {
  mock.config.mockRejectedValue(new Error("离线"));
  render(<App />);
  expect(screen.getByText(/你好，我是篮球进球剪辑助手/)).toBeVisible();
  expect(screen.getByLabelText("选择篮球视频")).toBeInTheDocument();
  expect(await screen.findByText(/无法读取上传限制/)).toBeVisible();
});
test("instruction before upload explains next action without API submission", async () => {
  render(<App />);
  await userEvent.type(screen.getByRole("textbox"), "去掉第二球");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(
    await screen.findByText("请先上传一段视频，再告诉我怎样剪辑。"),
  ).toBeVisible();
  expect(mock.send).not.toHaveBeenCalled();
});
test("rejects oversized upload in chat", async () => {
  render(<App />);
  await screen.findByText(/30 秒/);
  fireEvent.change(screen.getByLabelText("选择篮球视频"), {
    target: {
      files: [
        new File([new Uint8Array(2048)], "game.mp4", { type: "video/mp4" }),
      ],
    },
  });
  expect(await screen.findByText(/视频超过/)).toBeVisible();
  expect(mock.upload).not.toHaveBeenCalled();
});
test("uploads, persists credentials, plays secure result and numbers displayed events", async () => {
  mock.upload.mockResolvedValue({
    id: "one",
    token: "secret /?",
    status: "queued",
  });
  render(<App />);
  await screen.findByText(/30 秒/);
  fireEvent.change(screen.getByLabelText("选择篮球视频"), {
    target: { files: [new File(["video"], "game.mp4", { type: "video/mp4" })] },
  });
  const download = await screen.findByRole("link", { name: "下载集锦" });
  expect(download.getAttribute("href")).toContain("token=secret+%2F%3F");
  expect(screen.getByLabelText("进球集锦播放器")).toHaveAttribute(
    "src",
    expect.stringContaining("revision=r1"),
  );
  expect(screen.getByText("第 1 球")).toBeVisible();
  expect(screen.getByText("00:12.5")).toBeVisible();
  expect(localStorage.getItem("basketball-session")).toContain("one");
});
test("restores messages and blocks editing while busy, allowing progress", async () => {
  localStorage.setItem(
    "basketball-session",
    JSON.stringify({ id: "one", token: "secret" }),
  );
  mock.job.mockResolvedValue({ ...completed, status: "rendering" });
  mock.messages.mockResolvedValue({
    messages: [{ id: "m1", role: "assistant", text: "正在调整前置时长" }],
  });
  render(<App />);
  expect(await screen.findByText("正在调整前置时长")).toBeVisible();
  await userEvent.type(screen.getByRole("textbox"), "去掉第二球");
  expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  await userEvent.clear(screen.getByRole("textbox"));
  await userEvent.type(screen.getByRole("textbox"), "查看进度");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() =>
    expect(mock.send).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        text: "查看进度",
        request_id: expect.any(String),
      }),
      expect.anything(),
    ),
  );
});
test("retains request id when retrying a failed relative edit", async () => {
  localStorage.setItem(
    "basketball-session",
    JSON.stringify({ id: "one", token: "secret" }),
  );
  mock.send
    .mockRejectedValueOnce(new Error("网络断开"))
    .mockResolvedValueOnce({ status: "queued" });
  render(<App />);
  await screen.findByRole("link", { name: "下载集锦" });
  await userEvent.type(screen.getByRole("textbox"), "每球前面多留三秒");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  await screen.findByText(/网络断开/);
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(mock.send).toHaveBeenCalledTimes(2));
  expect(mock.send.mock.calls[0][1].request_id).toBe(
    mock.send.mock.calls[1][1].request_id,
  );
});

test("failed rerender keeps the previous playable result and displayed ordinals", async () => {
  localStorage.setItem(
    "basketball-session",
    JSON.stringify({ id: "one", token: "secret" }),
  );
  mock.job.mockResolvedValue({
    ...completed,
    status: "failed",
    error: "模型暂不可用",
  });
  render(<App />);
  expect(await screen.findByRole("link", { name: "下载集锦" })).toBeVisible();
  expect(screen.getByText("模型暂不可用")).toBeVisible();
  expect(screen.getByText(/上一份可用集锦/)).toBeVisible();
});
test("new upload waits for explicit context reset and Escape cancels", async () => {
  localStorage.setItem(
    "basketball-session",
    JSON.stringify({ id: "one", token: "secret" }),
  );
  render(<App />);
  await screen.findByRole("link", { name: "下载集锦" });
  fireEvent.change(screen.getByLabelText("选择篮球视频"), {
    target: { files: [new File(["v"], "other.mp4", { type: "video/mp4" })] },
  });
  const dialog = await screen.findByRole("dialog");
  expect(mock.upload).not.toHaveBeenCalled();
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
test("unmount aborts status requests so an old session cannot update the UI", async () => {
  localStorage.setItem(
    "basketball-session",
    JSON.stringify({ id: "one", token: "secret" }),
  );
  const { unmount } = render(<App />);
  await screen.findByRole("link", { name: "下载集锦" });
  const signal = mock.job.mock.calls[0][1] as AbortSignal;
  unmount();
  expect(signal.aborted).toBe(true);
});

test("expired session explains recovery and allows selecting another video", async () => {
  localStorage.setItem(
    "basketball-session",
    JSON.stringify({ id: "one", token: "secret" }),
  );
  const { ApiError } = await import("./api");
  mock.job.mockRejectedValue(new ApiError("不存在", 404));
  render(<App />);
  expect(await screen.findByText(/此视频已到期/)).toBeVisible();
  expect(screen.getByLabelText("选择篮球视频")).not.toBeDisabled();
  expect(screen.queryByText(/正在尝试重新连接/)).not.toBeInTheDocument();
});
test("IME Enter does not submit an unfinished Chinese instruction", async () => {
  render(<App />);
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "去掉第二球" },
  });
  fireEvent.keyDown(screen.getByRole("textbox"), {
    key: "Enter",
    isComposing: true,
  });
  expect(
    screen.queryByText("请先上传一段视频，再告诉我怎样剪辑。"),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("textbox")).toHaveValue("去掉第二球");
});
