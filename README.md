# CLI Source and Auto Analysis Tool

Greenfield Streamlit and MCP proof harness for exposing two Chat Completions tools to a
Qwen model served by vLLM's OpenAI-compatible API:

- `source_search`, shown in the UI as `source-search`
- `auto_analysis`, shown in the UI as `auto-analysis`

The reusable implementation lives in plain Python modules under `cli_agent/`. Streamlit only
renders the temporary chat UI and artifacts.

The default local topology is:

- The controller calls vLLM on the host at `http://localhost:8000/v1`.
- The Dockerized Copilot CLI worker calls the same vLLM service from inside Docker at
  `http://host.docker.internal:8000/v1`.
- Both paths default to `Qwen3.6-27B`; override the model environment variables if your vLLM
  server uses a different served model name.

## Architecture

- `controllers`: chat-turn orchestration and one-tool-call-per-turn enforcement.
- `agents`: OpenAI-compatible Chat Completions client behavior for vLLM/Qwen or a compatible
  provider.
- `managers`: tool dispatch, argument validation, ambiguity guardrails, and worker run coordination.
- `services`: approved-source loading, run-folder setup, Docker command execution, prompt construction, and artifact collection.

## Local Setup

```powershell
poetry install
```

Start a vLLM OpenAI-compatible server with Qwen before launching the app. For example:

```powershell
vllm serve Qwen3.6-27B --host 0.0.0.0 --port 8000
```

Set the controller chat endpoint:

```powershell
$env:CLI_AGENT_CHAT_BASE_URL="http://localhost:8000/v1"
$env:CLI_AGENT_CHAT_MODEL="Qwen3.6-27B"
$env:CLI_AGENT_CHAT_API_KEY="not-needed"
```

Set the Copilot CLI worker provider. The worker runs inside Docker, so `host.docker.internal`
points back to the host vLLM process:

```powershell
$env:COPILOT_PROVIDER_BASE_URL="http://host.docker.internal:8000/v1"
$env:COPILOT_MODEL=$env:CLI_AGENT_CHAT_MODEL
$env:COPILOT_OFFLINE="true"
```

`COPILOT_OFFLINE=true` is the default and is intended to avoid GitHub auth/server contact. It is
not required for BYOK; override it only when your worker provider setup requires online Copilot
behavior. Set `COPILOT_PROVIDER_API_KEY` only if your vLLM server or replacement provider requires
one. `CLI_AGENT_DOCKER_NETWORK` is passed directly to Docker as `--network` when set. Use it with a
preconfigured Docker network or external policy when the worker needs constrained provider
reachability, and verify allowed and blocked egress outside this process before trusting that
profile.

Build the worker image once:

```powershell
docker build -t cli-agent-worker:local worker
```

Run the Streamlit proof harness:

```powershell
poetry run streamlit run streamlit_app.py
```

Run the MCP stdio server:

```powershell
poetry run cli-agent-mcp
```

The MCP server exposes the same `source_search` and `auto_analysis` tools as the Streamlit proof
harness. Tool schemas are generated from `settings/approved_sources.json`, so clients must pass
exact approved source path strings.

## Implementation Guide

This proof of concept assumes a stable environment where a general agent runs against a vLLM-hosted
Qwen model and receives `cli-agent` as an MCP stdio tool server. In that topology, the general
agent owns the conversation and tool selection. `cli-agent` owns approved-source validation,
isolated worker execution, and returning structured tool results.

Target runtime shape:

```text
general agent
  -> vLLM OpenAI-compatible API on host: http://localhost:8000/v1
  -> MCP stdio subprocess: poetry run cli-agent-mcp
       -> approved source validation
       -> Docker worker container
            -> Copilot CLI
            -> vLLM from Docker: http://host.docker.internal:8000/v1
```

### 1. Prepare the model server

Run vLLM with the same served model name that `cli-agent` and the general agent will send in chat
completion payloads:

```powershell
vllm serve Qwen3.6-27B --host 0.0.0.0 --port 8000
```

Confirm the model server is reachable from the host:

```powershell
Invoke-RestMethod http://localhost:8000/v1/models
```

Confirm Docker containers can reach the same server:

```powershell
docker run --rm curlimages/curl:latest http://host.docker.internal:8000/v1/models
```

If the Docker check fails, fix host firewall, Docker Desktop networking, or the vLLM bind address
before testing `cli-agent`. The worker cannot complete tool runs unless this path works.

### 2. Install the app and build the worker

Install Python dependencies and build the local worker image:

```powershell
poetry install
docker build -t cli-agent-worker:local worker
```

The worker image contains the Copilot CLI and runs with the containment settings described below.
Rebuild it after changing `worker/Dockerfile` or when refreshing the Copilot CLI version.

### 3. Configure the environment

Set these variables in the same process environment that will launch `cli-agent-mcp`:

```powershell
$env:CLI_AGENT_CHAT_BASE_URL="http://localhost:8000/v1"
$env:CLI_AGENT_CHAT_MODEL="Qwen3.6-27B"
$env:CLI_AGENT_CHAT_API_KEY="not-needed"
$env:COPILOT_PROVIDER_BASE_URL="http://host.docker.internal:8000/v1"
$env:COPILOT_MODEL="Qwen3.6-27B"
$env:COPILOT_OFFLINE="true"
```

The MCP path does not normally use `CLI_AGENT_CHAT_BASE_URL` directly, because the general agent
owns the outer chat loop. Keeping the controller and worker variables aligned still matters for
Streamlit smoke tests and for any code path that uses the bundled chat controller.

Use these optional variables when the environment requires them:

- `CLI_AGENT_APPROVED_SOURCES_PATH`: point at a non-default approved-source manifest.
- `CLI_AGENT_DOCKER_NETWORK`: attach workers to a preconfigured Docker network.
- `COPILOT_PROVIDER_API_KEY`: pass a provider token to the worker only when required.
- `CLI_AGENT_RUNS_ROOT`: move run folders outside `python-agent-runs/`.

### 4. Define approved sources

`cli-agent` never lets the model pass arbitrary file paths. Every source path must be listed in the
approved-source manifest and must be repo-relative:

```json
{
  "sources": [
    {
      "path": "sample_sources/dnd5e_hp_reference.md",
      "label": "D&D 5e HP quick reference",
      "description": "Small demo source for hit point calculations and ambiguity checks."
    }
  ]
}
```

For a PDF corpus, prefer chapter-level files. Large monolithic PDFs are slower, harder to inspect,
and may exceed default source-size limits. Generate a local manifest from PDFs with:

```powershell
poetry run python scripts\build_approved_sources.py --corpus "5e PHB\chapters" --output settings\approved_sources.5e_phb.local.json
$env:CLI_AGENT_APPROVED_SOURCES_PATH="settings\approved_sources.5e_phb.local.json"
```

### 5. Register the MCP server with the agent

Configure the general agent to launch `cli-agent` as a stdio MCP server from the repository root.
Exact configuration syntax depends on the host agent, but the required shape is:

```json
{
  "mcpServers": {
    "cli-agent": {
      "command": "poetry",
      "args": ["run", "cli-agent-mcp"],
      "cwd": "C:\\Users\\madse\\Documents\\cli-agent",
      "env": {
        "CLI_AGENT_APPROVED_SOURCES_PATH": "settings\\approved_sources.json",
        "COPILOT_PROVIDER_BASE_URL": "http://host.docker.internal:8000/v1",
        "COPILOT_MODEL": "Qwen3.6-27B",
        "COPILOT_OFFLINE": "true"
      }
    }
  }
}
```

After registration, the agent should see two tools:

- `source_search`: source-backed lookup only, with citations from approved files.
- `auto_analysis`: source-backed analysis or calculation, with an optional markdown report and
  artifacts.

Both tools require `question` and `source_paths`. `source_paths` must contain exact strings from
the manifest. `auto_analysis` may also receive `analysis_goal` for a concise statement of the
expected output.

Example `source_search` arguments:

```json
{
  "question": "What hit point rule applies after level 1?",
  "source_paths": ["sample_sources/dnd5e_hp_reference.md"]
}
```

Example `auto_analysis` arguments:

```json
{
  "question": "Calculate expected level 5 paladin hit points with a Constitution modifier of +2 using fixed increases.",
  "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
  "analysis_goal": "Return the calculated hit point total and cite the rule used."
}
```

### 6. Smoke test the proof of concept

Use this sequence to verify the integration end to end:

1. `Invoke-RestMethod http://localhost:8000/v1/models` returns the Qwen served model.
2. `docker run --rm curlimages/curl:latest http://host.docker.internal:8000/v1/models` works.
3. `poetry run pytest` passes.
4. `poetry run cli-agent-mcp` starts without an approved-source or environment error.
5. The host agent lists `source_search` and `auto_analysis`.
6. A `source_search` call returns a JSON tool result with `status: "success"`, a `run_id`, and
   cited markdown.
7. A failed request for an unapproved path returns an error before Docker starts.
8. A successful run creates `python-agent-runs/<run_id>/output/answer.md` and
   `python-agent-runs/<run_id>/output/manifest.json`.

### 7. Expected outputs and debugging

Each MCP tool result is returned as JSON text. The important fields are:

- `status`: `success`, `error`, `needs_clarification`, `timeout`, or `capacity_exceeded`.
- `run_id`: folder name under `python-agent-runs/` when a worker run was created.
- `report_markdown`: the worker's answer or report.
- `artifact_paths`: generated files such as CSVs or graphs.
- `citation_summary`: approved source paths cited by the result.
- `error`: failure text when the run did not succeed.

When a run fails, inspect:

- `python-agent-runs/<run_id>/output/manifest.json` for source sizes and run metadata.
- `python-agent-runs/<run_id>/output/logs/copilot.stderr.log` for worker startup or provider
  errors.
- `python-agent-runs/<run_id>/output/logs/copilot.stdout.log` for Copilot CLI output.

Common setup failures:

- The MCP server starts but tools are missing: the approved-source manifest is empty or invalid.
- Tool calls fail before Docker starts: `source_paths` do not exactly match manifest paths, or
  source-size limits are exceeded.
- Docker starts but the worker cannot answer: `host.docker.internal:8000` is unreachable from the
  container, `COPILOT_MODEL` does not match the served vLLM model, or provider auth is required.
- Runs return `capacity_exceeded`: increase `CLI_AGENT_MAX_CONCURRENT_WORKER_RUNS`, increase
  `CLI_AGENT_WORKER_QUEUE_TIMEOUT_SECONDS`, or reduce concurrent tool calls from the host agent.

## Approved Sources

The model can only request exact strings from `settings/approved_sources.json`. The dispatcher rejects any path not on that shortlist before Docker starts.

For the local 5e PHB test corpus, use chapter PDFs instead of the full book PDF. The full
`5e PHB/Player's Handbook.pdf` file is about 96 MiB and is intentionally above the default
single-source limit. A committed example settings file is available at:

```text
settings/approved_sources.5e_phb.example.json
```

To regenerate a local settings file from the chapter PDFs:

```powershell
poetry run python scripts\build_approved_sources.py --corpus "5e PHB\chapters" --output settings\approved_sources.5e_phb.local.json
$env:CLI_AGENT_APPROVED_SOURCES_PATH="settings\approved_sources.5e_phb.local.json"
```

PDF sources are copied into the run folder and converted to `.pdf.txt` files with page markers
before the Docker worker starts. The worker is pointed at the extracted text file, not the binary
PDF.

## Run Folders

Each accepted tool call creates one run folder:

```text
python-agent-runs/<run_id>/
  input/
  work/
  output/
    answer.md
    manifest.json
    optional results.csv
    optional graphs/*.png
    logs/
```

Run folders are gitignored and intentionally left for manual inspection and cleanup.

## Runtime Limits

The app is safe for concurrent Streamlit sessions in a single process because chat history is
kept in `st.session_state`, run folders use UUID-based names, and the cached controller does not
store per-user conversation state. Expensive worker execution is capped by a process-local
semaphore before Docker starts.

Important environment settings:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `CLI_AGENT_CHAT_BASE_URL` | `http://localhost:8000/v1` | OpenAI-compatible vLLM endpoint used by the controller chat model. |
| `CLI_AGENT_CHAT_MODEL` | `Qwen3.6-27B` | Qwen served model name sent to the controller chat endpoint. |
| `CLI_AGENT_CHAT_API_KEY` | `not-needed` | Bearer token sent to the chat endpoint. Use a real value if your provider requires one. |
| `CLI_AGENT_CHAT_TEMPERATURE` | `0.0` | Temperature for controller chat completions. |
| `CLI_AGENT_CHAT_TIMEOUT_SECONDS` | `120` | Maximum wait for each OpenAI-compatible chat completion call. |
| `COPILOT_PROVIDER_BASE_URL` | `http://host.docker.internal:8000/v1` | OpenAI-compatible worker provider base URL visible from Docker. |
| `COPILOT_MODEL` | `CLI_AGENT_CHAT_MODEL` | Model name passed to the Copilot CLI worker provider. |
| `COPILOT_PROVIDER_API_KEY` | unset | Optional bearer token for the worker provider. |
| `COPILOT_OFFLINE` | `true` | Whether Copilot CLI should avoid GitHub auth/server contact by default. |
| `CLI_AGENT_APPROVED_SOURCES_PATH` | `settings/approved_sources.json` | Approved-source settings file. |
| `CLI_AGENT_RUNS_ROOT` | `python-agent-runs/` | Root directory for per-tool run folders. |
| `CLI_AGENT_WORKER_IMAGE` | `cli-agent-worker:local` | Docker image used for worker runs. |
| `CLI_AGENT_MAX_CONCURRENT_WORKER_RUNS` | `2` | Maximum concurrent Docker worker runs per app process. |
| `CLI_AGENT_WORKER_QUEUE_TIMEOUT_SECONDS` | `30` | How long a request waits for a worker slot before returning `capacity_exceeded`. |
| `CLI_AGENT_WORKER_TIMEOUT_SECONDS` | `180` | Maximum runtime for a single worker container. |
| `CLI_AGENT_MAX_SOURCES_PER_RUN` | `4` | Maximum approved source files copied into one run. |
| `CLI_AGENT_MAX_SOURCE_BYTES` | `33554432` | Maximum bytes for one requested source, 32 MiB by default. |
| `CLI_AGENT_MAX_TOTAL_SOURCE_BYTES_PER_RUN` | `67108864` | Maximum total requested source bytes, 64 MiB by default. |
| `CLI_AGENT_DOCKER_NETWORK` | unset | Optional Docker `--network` value for externally constrained worker networking. |

Each manifest records selected source byte sizes and whether the worker timed out or hit capacity.

## Worker Containment

Worker containers run with a read-only root filesystem, no added Linux capabilities,
`no-new-privileges`, an init process, a small writable `/tmp`, and a PID limit. Runtime homes and
caches are redirected under `/workspace/work` so the worker can write only inside the run folder.
The Copilot CLI invocation keeps remote/built-in MCPs disabled, restricts added directories to
`/workspace`, and exposes only the explicit tool set required for local source inspection.

Network restriction is intentionally external to the worker container. Do not grant firewall or
network-admin privileges to this model-controlled container. For a constrained provider profile,
create and verify the Docker network or host policy separately, set `CLI_AGENT_DOCKER_NETWORK`, and
check both provider reachability and blocked disallowed egress before relying on that profile.

## Production Limitations

- Concurrency limiting is per Python process. Multiple Streamlit replicas need an external queue,
  shared job runner, or deployment-level capacity policy to enforce a global limit.
- There is no retrieval index or PDF text cache. Each accepted tool run copies the requested files
  into an isolated run folder and asks the worker to inspect them, so large PDFs cost disk, time,
  and model context on every run.
- vLLM is an external dependency. This app does not launch the model server, reserve GPU capacity,
  check model health, or verify that `CLI_AGENT_CHAT_MODEL` and `COPILOT_MODEL` match the served
  model names.
- PDF support depends on extractable embedded text through `pypdf`. Scanned/image-only PDFs fail
  before worker execution instead of producing guessed answers. Layout-heavy tables may still need
  manual validation.
- The app has no authentication, authorization, quota tracking, billing controls, or automated run
  folder retention. Add those before exposing it beyond a trusted internal group.
- Worker results remain model-dependent. The tool enforces source selection, output contracts,
  timeouts, and artifact collection, but it does not prove that every cited answer is complete or
  semantically correct.
- Streamlit is still a proof harness. For heavy production traffic, keep these modules and move the
  request/worker orchestration behind a service with durable jobs and observability.

## Tests

```powershell
poetry run pytest
```
