# DCI Search and Auto Analysis Tool POC

Greenfield Streamlit proof harness for exposing two Chat Completions tools to an OpenAI-compatible chat model:

- `dci_search`, shown in the UI as `dci-search`
- `auto_analysis`, shown in the UI as `auto-analysis`

The reusable implementation lives in plain Python modules under `dci_poc/`. Streamlit only renders the temporary chat UI and artifacts.

## Architecture

- `controllers`: chat-turn orchestration and one-tool-call-per-turn enforcement.
- `agents`: OpenAI-compatible Chat Completions client behavior.
- `managers`: tool dispatch, argument validation, ambiguity guardrails, and worker run coordination.
- `services`: approved-source loading, run-folder setup, Docker command execution, prompt construction, and artifact collection.

## Local Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Configure an OpenAI-compatible chat endpoint:

```powershell
$env:DCI_CHAT_BASE_URL="http://localhost:11434/v1"
$env:DCI_CHAT_MODEL="llama3.2"
$env:DCI_CHAT_API_KEY="not-needed"
```

Configure the Copilot CLI worker provider:

```powershell
$env:COPILOT_PROVIDER_BASE_URL="http://host.docker.internal:11434"
$env:COPILOT_MODEL="llama3.2"
$env:COPILOT_OFFLINE="true"
```

Build the worker image once:

```powershell
docker build -t dci-copilot-worker:local worker
```

Run the Streamlit proof harness:

```powershell
streamlit run streamlit_app.py
```

## Approved Sources

The model can only request exact strings from `config/approved_sources.json`. The dispatcher rejects any path not on that shortlist before Docker starts.

For the local 5e PHB test corpus, use chapter PDFs instead of the full book PDF. The full
`5e PHB/Player's Handbook.pdf` file is about 96 MiB and is intentionally above the default
single-source limit. A committed example config is available at:

```text
config/approved_sources.5e_phb.example.json
```

To regenerate a local config from the chapter PDFs:

```powershell
python scripts\build_approved_sources.py --corpus "5e PHB\chapters" --output config\approved_sources.5e_phb.local.json
$env:DCI_APPROVED_SOURCES_PATH="config\approved_sources.5e_phb.local.json"
```

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

Default limits:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `DCI_MAX_CONCURRENT_WORKER_RUNS` | `2` | Maximum concurrent Docker worker runs per app process. |
| `DCI_WORKER_QUEUE_TIMEOUT_SECONDS` | `30` | How long a request waits for a worker slot before returning `capacity_exceeded`. |
| `DCI_WORKER_TIMEOUT_SECONDS` | `180` | Maximum runtime for a single worker container. |
| `DCI_CHAT_TIMEOUT_SECONDS` | `120` | Maximum wait for each OpenAI-compatible chat completion call. |
| `DCI_MAX_SOURCES_PER_RUN` | `4` | Maximum approved source files copied into one run. |
| `DCI_MAX_SOURCE_BYTES` | `33554432` | Maximum bytes for one requested source, 32 MiB by default. |
| `DCI_MAX_TOTAL_SOURCE_BYTES_PER_RUN` | `67108864` | Maximum total requested source bytes, 64 MiB by default. |

Each manifest records selected source byte sizes and whether the worker timed out or hit capacity.

## Production Limitations

- Concurrency limiting is per Python process. Multiple Streamlit replicas need an external queue,
  shared job runner, or deployment-level capacity policy to enforce a global limit.
- There is no retrieval index or PDF text cache. Each accepted tool run copies the requested files
  into an isolated run folder and asks the worker to inspect them, so large PDFs cost disk, time,
  and model context on every run.
- The app has no authentication, authorization, quota tracking, billing controls, or automated run
  folder retention. Add those before exposing it beyond a trusted internal group.
- Worker results remain model-dependent. The tool enforces source selection, output contracts,
  timeouts, and artifact collection, but it does not prove that every cited answer is complete or
  semantically correct.
- Streamlit is still a proof harness. For heavy production traffic, keep these modules and move the
  request/worker orchestration behind a service with durable jobs and observability.

## Tests

```powershell
pytest
```
