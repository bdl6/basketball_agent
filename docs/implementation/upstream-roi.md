# 使用原项目识别与双 ROI 确认

本分支上传视频后，先调用原项目 `suggest_roi` 建议投篮分析区和篮网区域，等待用户确认，再启动原项目 `standard` 分析。自动定位失败时可手动框选。大框覆盖完整投篮轨迹和篮筐，小框贴合篮网，并位于大框内。支持切换时间、重新绘制与数值输入。

识别入口是 `video_engine/upstream.py`，通过原项目的 JSON-lines 协议调用 `create_project → link_video → save_roi → start_analysis → get_job → list_candidates`。代理视频、粗筛、精筛、重筛、候选去重由原项目执行；旧检测器、旧命令行入口和旧算法快照已删除，识别仅使用内置原项目引擎。剪辑所需的公共媒体工具迁至 `video_engine/media.py`。

候选保留原项目 ID、源视频时间、完整 evidence 和原始候选行。原项目 `excluded` 显示为未进，不参与剪辑；纳入的待审核候选显示疑似，默认纳入；只有原始 verdict 与 rim_check 都为 made 才显示模型确认。此处只做展示映射，不重新评估轨迹、调整阈值或再次去重。用户勾选不修改识别结论。

## 本地运行

先安装本仓库依赖与原项目 `requirements.txt`，准备 FFmpeg/FFprobe 和原项目权重。原项目源码应为包含 `engine/python`、`src`、`scripts` 的完整目录，当前验证版本 hello 返回 `python-v2.20-rim-crossing-event-dedupe`。部署时应固定该源码版本和权重版本。

API 和 worker 的两个终端都设置以下环境变量，`.env.example` 不会自动加载：

```powershell
# 默认使用仓库内 vendor/basketball-highlight-editor，无需设置 BASKETBALL_ENGINE_ROOT
$env:BASKETBALL_MODEL_PATH = 'E:/basketball-highlight-editor/models/bball_model.pt'
$env:BASKETBALL_DATA_DIR = "$PWD/data/upstream-roi"
# 可选：使用安装了原项目依赖的另一 Python
# $env:BASKETBALL_ENGINE_PYTHON = 'E:/python/python.exe'
```

API 终端：`python -m uvicorn backend.app:app --host 127.0.0.1 --port 8011 --no-access-log`

worker 终端：`python -m backend.worker`

前端终端进入 `frontend` 后运行：

```powershell
$env:BASKETBALL_API_TARGET = 'http://127.0.0.1:8011'
npm ci
npm run dev -- --port 5175 --strictPort
```

访问 `http://127.0.0.1:5175`。这里使用独立端口与工作树内的数据目录，避免和其他分支的服务共用状态。

## 状态和接口

- 上传返回 `preparing_roi`；worker 只准备视频信息和建议框，然后停在 `awaiting_roi`。
- `GET /api/jobs/{id}` 和 SSE 快照增加 `roi`，含 width/height、duration_seconds、两个框、confirmed、preview_time_seconds 与可选 warning。
- `POST /api/jobs/{id}/roi`：`{request_id, roi:{x1,y1,x2,y2}, net_roi:{x1,y1,x2,y2}}`；坐标均为显示方向下的源视频像素。需要原任务 token；校验有限值、边界、最小分析区与包含关系。
- 确认成功返回 202，幂等入队；进行中的新修改返回 409。未确认时聊天剪辑指令返回 409，进度查询仍可用。
- 原项目实际阶段与进度通过现有 SSE 发送。每次区域确认启动独立引擎项目，防止缓存候选跨区域复用。
- 重设区域立即清空旧事件、选择、预览引用和集锦；旧成片不会继续作为新分析结果展示。失败后可调整区域重试。
- 视频 `/source`、候选与成片均受任务凭证保护；浏览器媒体 URL 可带查询 token，关闭访问日志。

原项目识别源码已纳入 vendor/basketball-highlight-editor，保留 MIT 许可证及文件指纹；模型权重仍独立配置。真实识别效果取决于原模型、区域设置、视频质量及原项目算法。
