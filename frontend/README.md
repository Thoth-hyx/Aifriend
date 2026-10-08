# AIFriends 前端

Vue 3 + Vite + Pinia，界面使用 Tailwind CSS 与 daisyUI。项目概览及后端配置见 [根目录 README](../README.md)。

## 开发与构建

在 `frontend/` 执行，需要 Node.js 20（≥20.19）或 ≥22.12：

```powershell
npm install
npm run dev
```

访问 <http://localhost:5173>；Vite 将 `/api`、`/media`、`/static` 代理到 <http://127.0.0.1:8000>。

```powershell
npm run build
```

构建输出到 `backend/static/frontend/`，之后可通过 Django 的 8000 端口访问。默认无需修改 API 地址；跨域部署时可用 `VITE_API_URL` 覆盖。

## 语音输入资源

首次安装后，在 `frontend/` 执行：

```powershell
New-Item -ItemType Directory -Force public/vad | Out-Null
Copy-Item node_modules/@ricky0123/vad-web/dist/vad.worklet.bundle.min.js public/vad/
Copy-Item node_modules/@ricky0123/vad-web/dist/*.onnx public/vad/
Copy-Item node_modules/onnxruntime-web/dist/ort-wasm*.mjs public/vad/
Copy-Item node_modules/onnxruntime-web/dist/ort-wasm*.wasm public/vad/
```

VAD 资源由 Vite 复制到构建产物，默认地址随开发/构建模式变化；`VITE_VAD_URL` 可选覆盖。浏览器需要麦克风权限，以及 localhost 或 HTTPS 环境。

## 前端回归检查

在项目根目录执行：

```powershell
node --test frontend/src/js/groupMessages.test.js frontend/src/stores/user.test.js test/test_reply_messages.mjs test/test_voice_upload.mjs
```
