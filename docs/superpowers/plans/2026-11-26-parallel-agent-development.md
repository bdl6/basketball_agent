# 聊天式最小闭环：多 Agent 分支与目录计划

> **For agentic workers:** 实施采用 superpowers:subagent-driven-development；隔离工作区采用 superpowers:using-git-worktrees。各模块按明确行为测试、小步实现和验证推进。

**Goal:** 多 Agent 并行实现聊天介绍、上传、自动集锦、自然语言修改和结果播放下载。

**Architecture:** 一个仓库，Web + API + 单个串行 worker；LangGraph 和识别作为 worker 内模块。每个分支是完整 worktree，只修改负责的模块。

**Tech Stack:** React/TypeScript/Vite、FastAPI、SQLite、LangGraph、LLM、现有识别引擎和 FFmpeg。

**Spec:** [最小闭环任务计划 v0.4](../../WeChat_Basketball_MVP_Task_Plan.md)。本文件取代此前包含候选审核、复杂检查点与完整版本管理的分工计划。

## 1. 分支与独立工作文件夹

```text
C:/Users/lenovo/.codex/worktrees/
├── integration/vibe_code/     # codex/integration，主 Agent
├── frontend/vibe_code/        # codex/frontend，聊天前端
├── backend/vibe_code/         # codex/backend，最小 API 与 worker
├── video-engine/vibe_code/    # codex/video-engine，识别与集锦
└── agent/vibe_code/           # codex/agent，LangGraph 与指令处理
```

上述工作树已由原生工具创建并注册。原始 main 工作区为 `E:/vibe_code`，其未提交文档保持不变。用户已明确授权多 Agent 并行 worktree，优先于技能的默认串行执行建议。每个文件夹是完整仓库副本，frontend 工作树中也会有 frontend 源码目录。最终 main 只有一份模块目录，不包含这些工作树副本。

实施期间遵守最多主 Agent + 三个开发 Agent 并行的限制；frontend、backend、video-engine 与后续 agent 模块均已在独立分支完成初步集成。当前最终修复和验收仍在 integration 推进，不合并 main、不 push。

## 2. 仓库建议结构

```text
basketball_agent/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx                  # 单页聊天入口
│       ├── components/
│       │   ├── ChatMessages.tsx     # 用户/助手/状态消息
│       │   ├── WelcomeMessage.tsx   # 固定介绍、上传引导、指令示例
│       │   ├── ChatComposer.tsx     # 输入、上传与快捷指令
│       │   └── VideoResult.tsx      # 播放、下载、进球列表
│       ├── api.ts                  # 上传、消息、状态请求
│       └── styles.css
├── backend/
│   ├── __init__.py
│   ├── app.py                      # FastAPI 入口和少量路由
│   ├── config.py                   # 限制、目录与模型配置
│   ├── store.py                    # SQLite 任务/消息/事件/当前方案
│   ├── access.py                   # 任务凭证校验
│   ├── worker.py                   # 串行领取与执行，中断标记
│   └── cleanup.py                  # 简单过期清理函数/脚本
├── agent/
│   ├── __init__.py
│   ├── graph.py                    # 理解→分析或更新方案→渲染
│   ├── state.py                    # 消息、事件/文件引用、当前参数
│   ├── interpret.py                # LLM 结构化指令与澄清
│   ├── tools.py                    # 受约束工具适配，不执行任意命令
│   └── prompts.py                  # 能力边界与指令解释
├── basketball_detect/              # 既有识别代码，保留包名
├── video_engine/
│   ├── __init__.py
│   ├── analyzer.py                 # 复用识别，输出统一事件
│   └── highlights.py               # 裁剪、合并、编码和成片验证
├── contracts/
│   ├── __init__.py
│   ├── models.py                   # Job/Message/Event/EditPlan/Operation
│   └── fixtures/                   # 前端 mock 与公共样例
├── tests/
│   ├── backend/
│   ├── agent/
│   ├── video_engine/
│   └── integration/
├── vendor/                         # 原算法和许可
├── docs/
├── pyproject.toml
└── .env.example
```

仅在单文件职责变复杂时再拆目录。无需提前创建 security、queue、persistence、checkpoints 等多层目录。既有识别测试整合保留，不为目录美观重构算法。不保留 wechat_service：实施时删除微信专属代码、测试、依赖、环境变量和部署入口；共享配置只移除微信部分，保留网页与识别所需内容。不把容器化改造作为首版阻塞项。

## 3. 主要运行服务

| 服务 | 入口/建议端口 | 职责 |
|---|---|---|
| Web | Vite，5173 | 单页聊天、欢迎引导、上传、指令、视频结果 |
| API | backend.app，8000 | 接收上传/消息、查询任务与消息、校验凭证、播放下载 |
| Worker | backend.worker，无端口 | 串行执行 LangGraph、识别与剪辑 |

只使用本地文件和 SQLite；不加 Redis、Celery、账号服务或独立模型网关。集成环境 API 和 worker 共享数据；不同 worktree 使用不同环境、端口和数据目录，模型权重可只读引用。

## 4. 模块所有权与最小接口

| 分支 | 可修改范围 | 首版交付 |
|---|---|---|
| integration | contracts、公共依赖、集成测试、文档 | 公共接口、引擎整合、最终验收 |
| frontend | frontend | 固定欢迎、聊天消息、上传、状态、结果卡片 |
| backend | backend、tests/backend | 最小任务与消息 API、凭证、串行 worker |
| video-engine | basketball_detect、video_engine、相关测试和必要 vendor 修复 | 可靠事件输出、原片集锦导出 |
| agent | agent、tests/agent | 结构化指令、澄清、工具调用及结果复用 |

建议 API：POST /api/jobs（上传）、GET /api/jobs/{id}（状态和当前结果）、GET /api/jobs/{id}/messages（消息）、POST /api/jobs/{id}/messages（提交指令）、GET /api/jobs/{id}/result（播放/下载）。凭证校验适用于所有任务接口。返回结构与消息 ID 在并行开发前由主 Agent 定义，供 mock 和实际实现共用。

工具保留分析、列事件、更新当前方案、渲染和查询状态五类；工具调用只引用授权任务，不接受模型任意指定本地路径。欢迎与进度模板不用模型。worker 执行图时同步调用视频工具，不向自己再次入队同一渲染任务。

不建设候选确认接口、版本列表接口、用户接口或人工恢复接口。消息提交用请求 ID 去重，同任务仅一个活动执行；重复请求返回已有执行，新修改在忙碌时明确拒绝，避免设计并发编辑系统。

## 5. 执行步骤

### P0：共同基线

- [x] 主 Agent 在 integration 整合 baketball_detect，处理 README、pyproject、测试等公共冲突，保留许可。
- [x] 主 Agent 清理 wechat_service 及微信专属测试、配置和部署说明，更新 README 与 Python 包发现设置；搜索残余引用，确认网页和识别模块不依赖微信凭证即可启动。历史 Git 提交保留，无需在目标目录保留微信服务。
- [x] 重跑已有测试，记录权重与真实素材限制，不将合成验证当作识别准确率。
- [x] 定义最小数据与 API 契约、指令操作格式和 mock；确认后创建或同步各 worktree。

### P1：前端、后端、视频并行

- [x] frontend：设计参考 `frontend-design` skill，先定位并阅读 SKILL.md，再确定聊天页的排版、配色、间距和交互；覆盖欢迎、上传、处理中、结果与错误状态，检查手机/桌面布局、键盘操作和可读性。已读取公开来源 `https://raw.githubusercontent.com/anthropics/skills/main/skills/frontend-design/SKILL.md`，视觉 tokens 记录在 `frontend/DESIGN.md`，不表示全局安装；不以参考设计为由增加页面或后端功能。
- [x] frontend：新会话立即显示自我介绍、上传引导和四类指令示例，完成消息区、输入框、上传及结果卡片；验证模型不可用时欢迎仍显示。
- [x] backend：实现上传、SQLite 状态/消息/当前方案、任务凭证与单 worker；验证请求不阻塞、越权拒绝、重复请求去重、重启标记中断。
- [x] video-engine：封装现有识别与集锦导出；验证前五后两秒、重叠与边界、无进球、音轨和可播放性。
- [x] 各模块已实现、验证并提交关键行为；前端先用同一契约的 mock，随后切换真实 API。当前最终修复的回归仍待完成，见开发进度记录。
- [x] 主 Agent 集成自动集锦聊天流程，固定十秒或原样交付仅用于内部调试。

### P2：LangGraph 与聊天修改

- [x] 视频工具稳定后启动 agent 分支，前端/后端继续对接消息与指令状态。
- [x] 实现前后时长绝对/相对调整、排除事件及组合指令；歧义先澄清，不支持操作拒绝执行。
- [x] 图从已保存业务数据启动请求流程，不建设检查点和人工 interrupt；测试修改后分析调用计数不增加。
- [x] 实现同请求去重、参数校验和执行错误反馈，渲染成功后替换当前结果引用，失败保留旧成片。

### P3：最小闭环验收

- [ ] 真实浏览器完成介绍→上传→集锦→组合修改→新版播放下载。
- [ ] 验证未上传指令、无篮筐/无进球、模型超时、重复请求、刷新、重启中断、任务隔离与简单过期清理。
- [ ] 运行模块测试、前端构建及集成检查，记录真实样本和设备、识别误差、耗时和模型调用费用。
- [ ] 交付本地运行与使用说明；审查通过后按小步集成，不自行让各 Agent 合并 main。

## 6. 当前范围与后置项

候选人工审核、复杂图恢复、多会话管理、跨设备历史、版本浏览与回滚、并发编辑、自动重试平台、大文件续传、对象存储及生产运维扩展全部后置。只保留任务级保护，不建设账号系统。

重点审查：重复相对指令不累加、事件编号不等同合并片段、忙碌时修改不并发、失败不覆盖旧成片、重启不假报成功。分别由 agent/backend/video_engine 与集成测试覆盖。

上述工作树和 P0/P1/P2 模块已创建并初步集成（integration 13850c7）。修复前 Python 97 项、前端 18 项及构建通过；合成集成 2 项使用模拟识别/LLM、实际 FFmpeg/LangGraph 通过。真实 HTTP 无篮筐素材返回安全失败；浏览器只验证欢迎、配置与未上传提示，文件选择器超时，完整成功上传/修改/播放下载仍未验收。当前 worker 生命周期锁、渲染前说明、POSIX 子进程终止和 Windows 长路径发布修复及最终全量回归尚未确认通过。真实授权篮球样本与 live LLM key 未提供，真实识别效果和模型费用仍待记录。P3 复合验收项保持未勾选；详细证据见 [开发进度](../../implementation/development-progress.md)。首版交付依据仍为任务计划 v0.4 的 S4 最小闭环，不沿用旧 M4 扩展要求。
