# CLI Agent Frontend PoC

Barebones Next.js frontend for the existing Python `cli-agent` backend.

## Local run

Start the Python API from the repository root:

```bash
poetry run cli-agent-http
```

Then start the frontend:

```bash
cd frontend
npm install
npm run dev
```

For local proxy mode, create `frontend/.env.local` with:

```bash
CLI_AGENT_BACKEND_URL=http://127.0.0.1:8765
CLI_AGENT_BACKEND_BEARER_TOKEN=<same value as CLI_AGENT_HTTP_BEARER_TOKEN, if set>
```

For the Vercel demo, set `CLI_AGENT_BACKEND_URL` to the externally reachable Python API URL
such as an ngrok URL, and set `CLI_AGENT_BACKEND_BEARER_TOKEN` to the same value as
`CLI_AGENT_HTTP_BEARER_TOKEN`. Do not set `NEXT_PUBLIC_BACKEND_URL` unless you intentionally want
the browser to call the Python API directly.

The Vercel deployment should use `frontend/` as the project root.
