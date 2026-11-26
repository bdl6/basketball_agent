# 好球聊天前端

React + TypeScript + Vite 单页。需先启动 8000 端口的后端 API。

```powershell
cd frontend
npm ci
npm run dev
```

开发入口 http://127.0.0.1:5173。Vite 将 /api 代理到 http://127.0.0.1:8000；部署时也需同源代理，避免把任务凭证发送到其他域名。

```powershell
npm test
npm run build
```

欢迎和操作说明本地渲染，无需模型。上传限制来自 GET /api/config；配置获取失败时显示错误并禁用上传，避免虚构限制。使用原生 XHR 读取实际上传字节进度；分析与剪辑阶段只展示服务端状态。

本浏览器 localStorage 保存当前视频的任务 ID、访问凭证与待重发的消息请求 ID。网络失败后原样重发会复用请求 ID；刷新恢复消息与结果。服务端仍负责凭证校验与幂等处理。播放器与下载仅使用同源受控结果 URL，并附加凭证；页面启用 no-referrer。应避免在共享浏览器中保留敏感视频会话。

设计依据与 tokens 见 DESIGN.md；API 依据仓库 docs/implementation/api-contract.md。无账号、审片、版本列表或额外页面。
