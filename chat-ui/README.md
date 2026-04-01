# Chat UI (demo shell)

Dark, Claude-inspired chat interface for the multi-tool agent project. This package is **UI only**: messages are answered with a local mock after a short delay. Hooking up `POST /task` on the FastAPI service is a separate integration step.

## Local development

```bash
cd chat-ui
npm install
npm run dev
```

Open the URL Vite prints (typically http://localhost:5173).

## Production build

```bash
npm run build
npm run preview
```

## Docker

Build and run on port **8080** (host) mapping to nginx **80** (container):

```bash
cd chat-ui
docker build -t tufin-chat-ui .
docker run --rm -p 8080:80 tufin-chat-ui
```

Then open http://localhost:8080.

## Stack

- Vite, React, TypeScript, Tailwind CSS v4
- `react-markdown` + `remark-gfm` for assistant replies
