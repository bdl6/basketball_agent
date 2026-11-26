# 篮球进球剪辑 Agent

React 聊天页 + FastAPI + SQLite 持久队列 + 单个串行 worker + LangGraph 的本地 MVP。上传视频后按可靠进球生成集锦，通过聊天修改进球前后时长、排除当前展示编号的某球，再播放或下载新版本。适用固定机位、单个清晰篮筐的短视频；不包含微信服务。

范围见 [任务计划 v0.4](docs/WeChat_Basketball_MVP_Task_Plan.md)，接口见 [API 与数据契约](docs/implementation/api-contract.md)，检测细节见 [检测使用说明](docs/implementation/detection-usage.md)。

## 安装

需要 Python >=3.10、Node.js >=20、FFmpeg/FFprobe（含 libx264）在 PATH。在仓库根目录的 PowerShell 中执行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[detection,dev]"
ffmpeg -version
ffprobe -version
Push-Location frontend
npm ci
Pop-Location
```

`detection` 包含 NumPy、OpenCV、Pillow、Ultralytics、dill 等；PyTorch 的 CPU/GPU 安装须与本机设备匹配。从源码根目录运行并保留 `vendor`：尚不保证独立 wheel 包含检测 vendor。外部权重须兼容 `ball` / `hoop` 类别，仓库不分发权重。

## 启动三个进程

`.env.example` 只是配置示例，程序**不会自动加载 .env**。以下环境变量需要在 API 和 worker 各自的 PowerShell 窗口、仓库根目录中都设置；两个进程的 `BASKETBALL_DATA_DIR` 必须一致。请把示例路径、模型名和密钥替换为实际值，密钥只放在服务端：

```powershell
$env:BASKETBALL_DATA_DIR = "E:/basketball-data"
$env:BASKETBALL_MODEL_PATH = "E:/basketball-highlight-editor/models/bball_model.pt"
$env:LLM_BASE_URL = "https://api.openai.com/v1"
$env:LLM_MODEL = "YOUR_MODEL_NAME"
$env:LLM_API_KEY = "YOUR_SERVER_SIDE_KEY"
Test-Path $env:BASKETBALL_MODEL_PATH
```

API 窗口执行：

```powershell
.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

worker 窗口执行（仅启动一个 worker）：

```powershell
.venv\Scripts\python.exe -m backend.worker
```

前端窗口在仓库根目录执行：

```powershell
Set-Location frontend
npm run dev
```

打开 Vite 输出的本机地址（通常为 `http://127.0.0.1:5173`）。开发代理把 `/api` 转发到 `127.0.0.1:8000`。前端不需要、也不应设置 LLM 密钥。只有 API 没有 worker 时，上传会一直排队；停止进程使用 Ctrl+C。

初次上传默认每个可靠进球前 5 秒、后 2 秒，不调用语言模型。后续文字要求调用支持 JSON 输出的 OpenAI-compatible Chat Completions 服务（地址尾部为 `/v1`，程序追加 `/chat/completions`）。可尝试“去掉第二球，每球前面多留三秒”；编号以当前成片展示顺序为准。渲染前会先显示已理解的时长及排除编号。修改复用已有分析，不重新识别。无可靠进球不会生成空成片，失败时保留上一份可用集锦。

默认每个视频最大 100 MiB、300 秒，任务保留 24 小时。数据库、原视频和成片写入数据目录。任务凭证用于 API、播放和下载鉴权，浏览器播放链接携带 query token：保持 `--no-access-log`，反向代理也应屏蔽 query；不要分享带凭证的链接。本地 MVP 未提供多用户账号、生产部署和多 worker 调度。

## 验证

在根目录运行 Python 测试；使用较短的临时路径，避免 Windows 工具的路径长度限制：

```powershell
New-Item -ItemType Directory -Force E:/vibe_code/runs | Out-Null
.venv\Scripts\python.exe -m pytest -q --basetemp=E:/vibe_code/runs/test-local
Push-Location frontend
npm test
npm run build
Pop-Location
```

只运行跨模块闭环验证：

```powershell
New-Item -ItemType Directory -Force E:/vibe_code/runs | Out-Null
.venv\Scripts\python.exe -m pytest -q tests/integration --basetemp=E:/vibe_code/runs/test-integration
```

集成测试使用 FFmpeg 生成带音频的合成视频，经真实上传探测、SQLite、worker、LangGraph、OpenAI-compatible 指令解析和 FFmpeg 导出，再验证状态、改版后的 MP4 时长、Range 下载及渲染失败保留旧成片。检测结果与 LLM HTTP 回复是模拟的，不证明真实篮球识别准确率或在线模型理解效果。另有独立 worker/runner 进程在缺失权重时报告失败的 smoke test。FFmpeg/FFprobe 不在 PATH 时，这组媒体集成测试会跳过；应确认输出没有意外 skipped。

既有完整标注视频命令仍可用，与聊天集锦是不同输出：

```powershell
.venv\Scripts\python.exe -m basketball_detect --config config.example.json --video "E:/videos/sample.mp4"
```

## 已知边界

没有真实授权验收视频，尚不能承诺准确率、召回率或实际速度；GPU 未验收。当前检测要求恒定帧率、无旋转元数据的视频，遇到 VFR/旋转应按检测说明先转为正向 CFR 副本。检测“无法确认”不会算作进球，空白视频/合成视频也不能替代真实视频验收。模型、LLM 服务、网络或 FFmpeg 配置失败会明确显示错误；没有配置在线模型时聊天修改不能完成。

算法上游与许可见 [vendor/UPSTREAM.md](vendor/UPSTREAM.md) 和 [vendor/LICENSE](vendor/LICENSE)。
