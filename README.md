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
