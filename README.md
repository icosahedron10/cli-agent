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

## Tests

```powershell
pytest
```

