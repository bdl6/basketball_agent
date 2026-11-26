# 篮球进球检测：标注视频最小闭环

输入一段本地视频，自动检测篮筐和篮球、复核候选进球，输出完整时长的中文标注 MP4。固定机位、单个篮筐清晰可见；支持 CPU，自动选择可用推理设备。

## 本机直接运行

在本项目目录中执行 PowerShell：

```powershell
.venv\Scripts\python.exe -m basketball_detect --config config.example.json --video "E:\videos\你的篮球视频.mp4"
```

示例配置中的 `video` 故意留空，模型默认引用你提供项目的 `E:/basketball-highlight-editor/models/bball_model.pt`。视频和模型不会复制到仓库。

也可以复制配置后自行填写，后续直接运行：

```powershell
Copy-Item config.example.json config.local.json
# 编辑 config.local.json，填写 video；JSON 路径请使用 / 或双反斜杠。
.venv\Scripts\python.exe -m basketball_detect --config config.local.json
```

命令行参数优先于配置文件；配置文件中的相对路径相对于配置文件目录，命令行相对路径相对于当前目录。

## 环境准备

本工作树已建立 `.venv` 并复用本机已有 PyTorch/OpenCV 等包，额外补齐 dill。换机器时从干净环境安装：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
```

FFmpeg/FFprobe 需自行安装并加入 PATH。请从此源码目录运行命令，保留 `vendor` 目录；首版未提供独立安装包。GPU 需要与设备匹配的 PyTorch。本机已验证 CPU 加载现有权重并完成空白帧推理；未验证 GPU。权重需要兼容 `ball` 和 `hoop` 类别。

## 输出

每次运行创建独立目录，成功后终端最后一行是成品绝对路径：

```text
runs/<时间-随机编号>/
  annotated.mp4            # 完整标注视频，H.264，保留第一条原音轨（转 AAC）
  events.json              # 三类事件、原视频时间、证据、模型指纹、耗时
  run.json                 # 阶段/成功或失败信息
  *.json / *.log           # 各检测阶段的结果及日志
```

标注包含篮筐框、抽帧检测到的篮球框、候选附近的短轨迹、中文判定、事件编号/时间和累计确认进球数。轨迹只显示实际检测点之间的短距离时间连接；检测缺失时不会虚构框。

- **进球**：精扫判定与原帧穿筐复核一致，通过自动确认。
- **未进**：逐帧复核观察到明确反弹、侧向离开等反证，且没有精扫进球正证与之冲突。精扫无法判断时，可靠的复核反证仍可判未进。
- **无法确认**：遮挡、缺少后续检测、复核不足或阶段证据冲突，不计数。
- **无当前候选**：当前时间没有候选事件，不代表本次投篮未进。

这是一轮离线分析，判定会在事件前 0.25 秒到后 1.8 秒显示，累计数在事件时刻更新。篮球框只显示在被实际采样的源帧上，其他帧可能没有框；短轨迹用于展示候选附近的运动。上游只提出篮筐附近的候选，并非所有投篮尝试都一定被识别；视频没有候选仍输出完整视频及 0 个确认进球。

## 可配置参数

| 配置 | 用途 |
|---|---|
| `video` / `--video` | 输入路径，必须填写 |
| `model` / `--model` | 本地权重路径 |
| `output` / `--output` | 输出根目录，默认 runs，每次新建子目录 |
| `roi` / `--roi X1 Y1 X2 Y2` | 可选原视频像素分析区域；默认自动寻找篮筐 |
| `coarse_fps` / `--coarse-fps` | 粗扫采样帧率，默认 10，不超过输入帧率 |
| `refine_fps` / `--refine-fps` | 候选窗口精扫帧率，默认 30，不超过输入帧率 |
| `device` / `--device` | auto、cpu、cuda、mps、dml、coreml；可选后端可能回落 CPU |
| `font` / `--font` | 可选中文 TTF/TTC 字体；Windows 默认微软雅黑/黑体 |

`output` 请填写有效目录，保留示例中的 `runs` 即可，不支持空字符串或 null。手动 ROI 是分析裁剪区域，仍要求模型能识别该区域中的篮筐，不是手动指定篮圈几何。无稳定篮筐、损坏视频、模型失败会明确报错，日志保留。默认不会覆盖原片或既有成品。

首版要求恒定帧率、无旋转元数据的视频。检测算法依赖源帧编号；发现明显可变帧率或旋转元数据时会拒绝，避免静默标错时间和位置。手机素材遇到此提示可先转成正向恒定帧率副本，再输入副本：

```powershell
ffmpeg -i "原片.mp4" -vf "fps=30" -c:v libx264 -crf 18 -c:a aac -metadata:s:v:0 rotate=0 "正向30fps副本.mp4"
```

## 验证与当前边界

```powershell
.venv\Scripts\python.exe -m pip install pytest
.venv\Scripts\python.exe -m pytest -q --basetemp=runs/test-local
```

测试覆盖配置、三类结果、证据冲突、候选合并、无候选、原图坐标、标注时间、长轨迹间隔、音轨、奇数尺寸、29.97fps、输出保护及完整应用导出。集成测试注入可控检测结果并真实执行 FFmpeg，不代表真实篮球视频的识别准确率。

**目前没有真实验收视频，精确率、召回率和实际处理速度待你配置视频后评估。** 不对双篮筐、移动镜头、严重遮挡、远处极小篮球保证效果；无法确认事件需要查看视频与证据。

算法来源及逐文件指纹见 [vendor/UPSTREAM.md](vendor/UPSTREAM.md)，上游 MIT 许可保留在 [vendor/LICENSE](vendor/LICENSE)。模型保持外部引用，不随本项目分发。
