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

Set `NEXT_PUBLIC_BACKEND_URL` in Vercel to the externally reachable Python API URL.
The Vercel deployment should use `frontend/` as the project root.
