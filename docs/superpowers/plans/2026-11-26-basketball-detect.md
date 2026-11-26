# 篮球检测视频最小闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 用户自行配置视频后，一条命令返回带进球判定的完整 MP4。

**Architecture:** 提取上游最小检测依赖，独立命令行编排自动 ROI、粗扫、候选、精扫与穿筐复核，再将证据和判定叠加到原视频。视频路径默认留空，模型使用外部路径；不依赖上游 GUI 或项目数据库。

**Tech Stack:** Python、OpenCV、NumPy、Ultralytics/PyTorch、FFmpeg/FFprobe、pytest。

**Spec:** ../specs/2026-11-26-basketball-detect-design.md

## Global Constraints

- 固定机位、单个篮筐；模型文件不随源码分发。
- 配置示例 video 为空；CLI 覆盖配置；配置相对路径相对于配置文件。
- 输出完整视频和原音频；没有音轨的输入允许成功。
- 不把没有候选或未被排除的候选判为进球，不把 state=confirmed 当成进球。
- 所有事件时间及标注坐标对应原视频，不覆盖输入。
- 当前没有真实验收视频，模型效果验证保持待验收状态。

## Review Focus

- 无候选时仍导出完整视频，累计进球数为 0。
- 反证与正证冲突时保留无法确认，不计数。
- 无音轨、奇数尺寸和非整数帧率输入仍可生成有效 MP4。
- 输入与输出相同或旧输出已存在时不得损坏原片和历史结果。
- 抽帧后轨迹不得跨长间隔插值或将原图坐标当代理坐标使用。

### Task 1: 配置入口和最小上游依赖

**Files:** Create pyproject.toml, config.example.json, basketball_detect/__init__.py, basketball_detect/__main__.py, basketball_detect/config.py, vendor/UPSTREAM.md, vendor/LICENSE, vendor/basketball_highlight/, vendor/scripts/, tests/test_config.py。

**Interfaces:** load_config(config_path: Path | None, overrides: dict) -> DetectConfig；字段 video、model、output、device、roi、coarse_fps、refine_fps。

- [x] 写配置测试，断言 video 空时提示用户配置；CLI 覆盖 JSON；相对路径相对配置文件；非法 ROI 和非正帧率被拒绝。
- [x] 运行 python -m pytest tests/test_config.py -q，确认新增行为尚未实现。
- [x] 实现配置与 CLI，提取上游脚本及其递归导入依赖，记录源版本或文件哈希，保留许可。
- [x] 运行配置测试及 python -m basketball_detect --help，确认无需导入模型也能显示帮助。
- [x] 提交本任务文件。

### Task 2: 检测流水线和三类结果

**Files:** Create basketball_detect/pipeline.py, basketball_detect/events.py, tests/test_pipeline.py, tests/test_events.py。

**Interfaces:** analyze(config: DetectConfig, run_dir: Path) -> AnalysisResult；classify_events(matches: list[dict], rim_checks: list[dict]) -> list[dict]；结果含 time、label、reason、rim、trajectory、raw_evidence。

- [x] 写测试覆盖 verdict made + rim made 才计入进球；ambiguous/缺失/冲突为无法确认；明确反证为未进；空候选不启动无用复核；重复事件不重复计数。
- [x] 运行 python -m pytest tests/test_pipeline.py tests/test_events.py -q，确认失败原因对应待实现行为。
- [x] 用 sys.executable 和参数列表编排 detect_auto_roi、scan_video、generate_candidates、refine_dynamic_candidates、verify_rim_crossing。直接使用原视频，proxy-scale=1；参考上游 apply_rim_checks 重新计算复核并保留 keep_unless_seen 的缺失证据处理。
- [x] 检查每阶段返回码和 JSON 结构，写独立日志、阶段耗时、配置和模型指纹；明确无篮筐与空候选的差异。
- [x] 运行上述测试并提交。

### Task 3: 视频标注和导出

**Files:** Create basketball_detect/render.py, tests/test_render.py, tests/test_media_export.py。

**Interfaces:** render_video(video: Path, analysis: AnalysisResult, destination: Path) -> Path；事件附近显示三类中文标签；可用系统中文字体通过 Pillow 渲染并缓存，字体不可用时报明确说明。

- [x] 测试事件首尾边界、累计进球只增加一次、空候选状态、球轨迹缺失和长间隔；利用标注函数返回的绘制数据检查时间和坐标，不只检查文件存在。
- [x] 用合成短视频分别覆盖无音轨和含音轨输入，断言输出可解码、帧数/时长在合理编码误差内、音轨按输入保留、H.264 编码，以及奇数尺寸补齐兼容编码。
- [x] 运行测试确认尚未实现；实现逐帧叠加、短轨迹和状态栏，再由 FFmpeg 合成音频并编码，FFprobe 校验后原子发布。
- [x] 对重复输出、输入输出冲突和编码失败添加保护；中间文件放入运行目录。
- [x] 运行本任务测试并抽取代表帧进行视觉检查，提交。

### Task 4: 单命令闭环、说明和实际验证边界

**Files:** Modify basketball_detect/__main__.py；Create README.md, tests/test_cli.py；Update config.example.json。

**Interfaces:** python -m basketball_detect --config config.json [--video input.mp4] [--output runs/demo]；成功打印成品路径，失败非零退出码。

- [x] 写 CLI 集成测试，注入可控检测后执行完整渲染，验证事件 JSON 与视频判定一致；明确该测试不验证真实模型。
- [x] 接通配置、检测和导出；示例 video 留空、model 可配置为 E:/basketball-highlight-editor/models/bball_model.pt，禁止自动下载替代模型。
- [x] 检查本机运行时和权重能否加载，记录实际结果；缺依赖时只安装必要依赖，不把未运行当通过。
- [x] 编写 Windows 安装与运行命令、配置说明、输出位置、三类判定含义及限制。
- [x] 运行 python -m pytest -q 和 CLI 帮助/空配置检查；查看合成输出代表帧、检查音视频元数据。真实视频验收待用户配置，明确列出待测项。
- [x] 提交并报告已验证内容、成品使用方式和未验证的模型实际准确率。
