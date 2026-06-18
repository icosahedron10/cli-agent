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
`CLI_AGENT_HTTP_BEARER_TOKEN`. If the backend is behind ngrok, set
`CLI_AGENT_BACKEND_NGROK=true` so the proxy sends ngrok's browser-warning bypass header. Do not set
`NEXT_PUBLIC_BACKEND_URL` unless you intentionally want the browser to call the Python API directly.

The proxy does not authenticate Vercel visitors. `CLI_AGENT_BACKEND_BEARER_TOKEN` keeps the backend
URL and token server-side and blocks direct unauthenticated calls to the Python API, but any visitor
who can reach the Vercel deployment can still use the proxy to start chat jobs and read run results.

The Vercel deployment should use `frontend/` as the project root.
