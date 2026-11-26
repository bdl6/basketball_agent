# 篮球进球剪辑 Agent

React 聊天页 + FastAPI + 单个串行 worker + LangGraph 的本地最小闭环，固定机位、单个清晰篮筐短视频。当前提交是 P0 公共基线，Web/API/worker 尚待后续模块实现，不能宣称聊天应用已可运行。

有效范围见 [任务计划 v0.4](docs/WeChat_Basketball_MVP_Task_Plan.md)，模块对接见 [API 与数据契约](docs/implementation/api-contract.md)，验证与限制见 [开发进度](docs/implementation/development-progress.md)。旧 PRD 仅供历史参考。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[detection,dev]"
ffmpeg -version
ffprobe -version
```

Python >=3.10；FFmpeg/FFprobe 需在 PATH。安装/API 配置无需微信凭证。本仓库不包含微信服务。模型保持外部引用，不随项目分发。检测模块依赖源码中的 vendor，必须从仓库运行；不保证独立 wheel 包含 vendor。

当前可运行的是既有检测命令：
```powershell
.venv/Scripts/python.exe -m basketball_detect --config config.example.json --video "E:/videos/sample.mp4"
.venv/Scripts/python.exe -m pytest -q --basetemp=runs/test-local
```

[检测使用说明](docs/implementation/detection-usage.md) 保留完整参数与标注视频输出说明。既有标注视频不是聊天集锦功能。后续模块合并后约定 API 入口为 `python -m uvicorn backend.app:app --port 8000`，worker 为 `python -m backend.worker`，前端在 frontend 目录通过 Vite 启动；这些入口在 P0 尚未实现。

没有真实授权验收视频，不能承诺检测准确率、召回率或实际速度；旋转/VFR 素材、GPU 尚未验收。算法上游与许可见 [vendor/UPSTREAM.md](vendor/UPSTREAM.md) 和 [vendor/LICENSE](vendor/LICENSE)。
