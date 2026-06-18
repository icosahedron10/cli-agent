# Security Review: cli-agent

## Scope
- Scan mode: repository-wide Codex Security scan.
- Repository root: `C:\Users\madse\Documents\cli-agent`.
- Commit: `e9a3e8b`.
- Scan id: `e9a3e8b_20260618T004757Z`.
- Threat model: generated during Phase 1 and copied to `C:\tmp\codex-security-scans\cli-agent\e9a3e8b_20260618T004757Z\artifacts\01_context\threat_model.md`.
- Worklist coverage: deterministic `rank_input.csv` produced 28 source/runtime rows; all 28 were copied into `deep_review_input.csv` and closed in `work_ledger.jsonl`.
- Validation status: focused tests passed with `18 passed`; validation used code trace, command-construction checks, existing tests, and a bounded symlink harness attempt.
- Main exclusions and limitations: no public deployment evidence was present; Docker daemon/Copilot runtime reproduction was not required; Windows symlink reproduction for finding 2 was blocked by local administrator privilege requirements; no malicious PDF was generated for finding 4.
- Final artifacts: markdown report at `C:\tmp\codex-security-scans\cli-agent\e9a3e8b_20260618T004757Z\report.md` and HTML report at `C:\tmp\codex-security-scans\cli-agent\e9a3e8b_20260618T004757Z\report.html`.

### Scan Summary
| Field | Value |
| --- | --- |
| Reportable findings | 4 |
| Severity mix | 3 medium, 1 low |
| Confidence mix | 2 high, 2 medium |
| Coverage | 28/28 deep-review rows closed; 13 repository coverage rows recorded |
| Validation mode | Static trace, focused tests, command-construction checks, bounded local reproduction attempt |
| Key phase artifacts | `C:\tmp\codex-security-scans\cli-agent\e9a3e8b_20260618T004757Z\artifacts\02_discovery\finding_discovery_report.md`, `C:\tmp\codex-security-scans\cli-agent\e9a3e8b_20260618T004757Z\artifacts\05_findings\validation_summary.md`, `C:\tmp\codex-security-scans\cli-agent\e9a3e8b_20260618T004757Z\artifacts\05_findings\attack_path_analysis_report.md` |

## Threat Model

# Threat Model: cli-agent

## Overview

`cli-agent` is a Python proof harness that exposes two model-callable tools, `source_search` and `auto_analysis`, through a Streamlit UI (`streamlit_app.py`) and an MCP stdio server (`cli_agent/mcp_server.py`). The tools let an OpenAI-compatible chat model request exact approved local source files, copy those files into an isolated run folder, optionally extract PDF text, and invoke a short-lived Docker worker running the GitHub Copilot CLI to produce an answer and optional artifacts. The reusable runtime is organized under `cli_agent/`; Streamlit is a temporary UI surface, and the MCP server exposes the same dispatch path.

The assets that matter most are local approved source files, the host filesystem under the repository root, generated run folders and artifacts, Docker host access, OpenAI-compatible chat provider credentials/endpoints, Copilot provider settings and API keys, and the integrity of tool outputs shown back to users or MCP clients. The main security objective is to let an untrusted or model-influenced request inspect only explicitly approved source files and write only bounded output artifacts, without turning tool execution into arbitrary host file access, command execution, network pivoting, or credential exposure.

## Threat Model, Trust Boundaries, and Assumptions

Primary runtime surfaces:

- `streamlit_app.py` accepts user chat input, displays approved source labels/paths, renders markdown answers, and exposes CSV/PNG artifacts for download or display.
- `cli_agent/mcp_server.py` exposes `source_search` and `auto_analysis` as MCP tools over stdio and dispatches requests through the same `Subagent`/`ToolManager` path.
- `cli_agent/controllers/chat_controller.py` sends conversation history to the chat agent, permits at most one tool call per turn, executes that tool call, and then asks the model for a final answer.
- `cli_agent/managers/tool_manager.py` parses model tool calls, validates argument keys, validates required strings, handles clarification logic, creates run folders, builds worker prompts, runs Docker, and collects artifacts.
- `cli_agent/services/approved_sources.py` loads `settings/approved_sources.json`, requires repo-relative source paths, rejects path traversal outside the repository root, rejects unapproved model-requested paths, deduplicates requested sources, and enforces source count and byte limits.
- `cli_agent/services/run_folder_service.py` creates UUID-based run folders under `python-agent-runs/`, copies approved files into `input/`, and extracts PDF text via `pypdf` before worker execution.
- `cli_agent/services/docker_runner.py` builds the Docker command, passes selected environment variables, mounts the run folder at `/workspace`, applies read-only rootfs/capability/PID/tmpfs restrictions, and runs the Copilot CLI.
- `cli_agent/services/artifact_service.py` reads worker outputs from `output/`, collects CSV and PNG artifacts, records a manifest, and returns a JSON envelope to the chat or MCP caller.
- `cli_agent/services/openai_chat_client.py` sends chat completion requests to the configured OpenAI-compatible base URL using the configured API key.

Trust boundaries:

- User and MCP client input crosses into the app as chat text or tool arguments. The app assumes these callers may be untrusted unless the deployment wraps it with authentication and authorization.
- The chat model is not trusted to choose safe tool arguments. Tool schema enums are a hint, but `ToolManager` and `ApprovedSourceService` are the authoritative enforcement points.
- `settings/approved_sources.json` and environment variables are operator/developer-controlled configuration. A malicious or careless operator can deliberately approve sensitive files, point endpoints at hostile services, weaken limits, or choose a permissive Docker network.
- Approved source file contents are attacker-controlled when the corpus comes from users or third parties. They can contain prompt injection, malformed PDFs, large files within configured limits, or content intended to influence the worker/model.
- The Docker worker is model-controlled execution over copied inputs. It must be treated as less trusted than the host app; its outputs are data, not executable instructions.
- The Docker daemon and host filesystem are privileged infrastructure. The app assumes Docker itself enforces the container boundary and that the worker image is built from trusted inputs.
- The OpenAI-compatible chat endpoint and Copilot provider endpoint are network trust boundaries. Requests may carry user prompts, source path names, tool outputs, and potentially excerpts of approved source data.

Attacker-controlled inputs include Streamlit chat prompts, MCP tool arguments, model-generated tool call JSON, contents and filenames of operator-approved source files, worker-generated `answer.md`, `needs_clarification.json`, CSVs, PNGs, and provider responses. Operator-controlled inputs include environment variables, approved source JSON, Docker image name, Docker network name, source-size limits, concurrency/timeouts, and provider credentials. Developer-controlled inputs include application code, tests, scripts, and the worker Dockerfile.

Key assumptions:

- This proof harness is intended for trusted local or internal use unless external authn/authz, quotas, retention, and observability are added.
- Approved source configuration is curated by a trusted operator and should not include secrets or broad repository paths.
- The worker image and installed Copilot CLI are trusted supply-chain artifacts at build time.
- Docker runs with normal container isolation, and operators do not grant host-equivalent privileges or unconstrained network reachability through `CLI_AGENT_DOCKER_NETWORK`.
- Run folders are intentionally retained for manual inspection; retention and access control are deployment responsibilities.

## Attack Surface, Mitigations, and Attacker Stories

Important mitigations already present:

- Model-requested source paths must exactly match approved strings loaded by `ApprovedSourceService.validate_requested_paths`; absolute paths and paths escaping `repo_root` are rejected while loading approved sources.
- Source-count, single-source-size, and total-source-size limits reduce denial-of-service and accidental disclosure blast radius.
- Tool dispatch rejects unknown tools, malformed JSON, missing arguments, unknown argument keys, non-string questions, and oversized/control-character `analysis_goal` values.
- `ChatController` rejects multiple tool calls in a single model turn.
- Run folder names include timestamps and UUID fragments, and directories are created with `exist_ok=False`.
- PDF text extraction happens before worker execution, and image-only/unextractable PDFs fail clearly instead of producing guessed answers.
- Worker containers run with `--read-only`, `--cap-drop=ALL`, `no-new-privileges`, a bounded `/tmp`, a PID limit, an init process, no remote/built-in MCPs, a restricted working directory, and only the run folder mounted.
- The README explicitly calls out that network restriction is external and warns not to grant firewall or network-admin privileges to the model-controlled container.
- Runner timeouts, queue timeouts, and a process-local semaphore bound worker execution.

Realistic attacker stories:

- A user or compromised chat model tries to request an unapproved file, a path traversal, or an absolute host path. The expected control is exact allowlist enforcement in `approved_sources.py` before Docker starts.
- A malicious approved PDF attempts parser abuse, decompression/resource exhaustion, or prompt injection. Relevant controls are byte limits, pre-worker `pypdf` extraction failures, worker timeout, and the fact that source content is still allowed to influence model output but should not expand file access.
- A model-generated tool call tries to smuggle unsupported arguments, multiple tools, or command-like content in `analysis_goal`. The expected controls are argument-key validation, one-tool-per-turn enforcement, and control-character/length checks.
- A malicious worker output tries to abuse Streamlit rendering or artifact download/display. `answer.md` is rendered as markdown, CSV files are served through download buttons, PNGs are displayed, and arbitrary other artifact paths are shown as text. Markdown/script handling depends on Streamlit defaults and should be reviewed before external exposure.
- A worker tries to access the host filesystem, write outside `/workspace`, fork excessively, or contact external services. The expected controls are Docker mount scope, read-only rootfs, PID limits, no added capabilities, and operator-provided network policy.
- A remote OpenAI-compatible provider receives sensitive prompts, approved source excerpts, or output artifacts. This is in scope for privacy/egress review; the app relies on operator selection of trusted providers and API keys.
- A local user abuses retained run folders to read prior users' copied sources, outputs, logs, or manifests. The current app intentionally leaves run folders for inspection and does not implement retention or access control.

Out-of-scope or lower-probability stories in the current repository context:

- Cross-tenant authorization and billing abuse are not first-order issues for the proof harness because the repository does not implement multi-tenant accounts, sessions, payments, or external user identity.
- CSRF/session fixation is less relevant until the Streamlit surface is deployed behind authenticated web access.
- SQL injection and traditional database authorization failures are not central because the repository does not use a database.
- SSRF through app-side HTTP requests is limited to configured chat completion endpoint calls; worker-side network risk depends primarily on Docker network policy and provider configuration.

## Severity Calibration (Critical, High, Medium, Low)

Critical findings in this repository would usually require escaping the intended source/worker boundary into host compromise or broad secret disclosure. Examples include a path validation flaw that lets model-chosen tool arguments copy arbitrary host files into the worker and provider prompt, Docker command or mount construction that lets attacker input mount host-sensitive paths or run arbitrary host commands, or worker containment weaknesses that make the Docker daemon/host filesystem reachable from model-controlled execution.

High findings would allow unauthorized access to sensitive approved or adjacent data, meaningful remote code execution within a privileged deployment boundary, or reliable bypass of core isolation controls without full host compromise. Examples include accepting unapproved source paths due to normalization mismatch, unsafe rendering of worker-controlled markdown/artifacts into executable browser content when exposed to users, or a configurable Docker network/default that unintentionally grants model-controlled containers access to internal services and credentials.

Medium findings would weaken integrity, confidentiality, or availability within expected local/internal use but have bounded blast radius. Examples include prompt-injection paths that cause uncited or misleading answers while still respecting the source allowlist, malformed PDF handling that crashes a request or consumes excessive CPU within configured limits, retained run folders leaking data to other local users on a shared host, or process-local concurrency allowing overload when deployed with multiple replicas.

Low findings would be hardening gaps, confusing failure modes, or developer-footguns that do not by themselves cross a major trust boundary. Examples include unclear configuration errors, incomplete manifest metadata, insufficient artifact type filtering that only exposes paths as text, missing cleanup tooling for local runs, or documentation gaps around safe provider/network setup.


## Findings

| # | Finding | Severity | Confidence | Category |
| --- | --- | --- | --- | --- |
| 1 | [Model-controlled worker can disclose COPILOT_PROVIDER_API_KEY through tool output and final chat context](#1-model-controlled-worker-can-disclose-copilotproviderapikey-through-tool-output-and-final-chat-context) | medium | high | Secret exposure / agent-tool boundary failure |
| 2 | [Worker-created symlinks in the writable bind mount can make the host read or overwrite files outside the run folder](#2-worker-created-symlinks-in-the-writable-bind-mount-can-make-the-host-read-or-overwrite-files-outside-the-run-folder) | medium | medium | Symlink confused deputy / path traversal across container boundary |
| 3 | [Model-controlled worker has unrestricted default Docker network egress despite network-boundary assumptions](#3-model-controlled-worker-has-unrestricted-default-docker-network-egress-despite-network-boundary-assumptions) | medium | high | Container egress control failure |
| 4 | [Approved PDFs are parsed and fully extracted on the host before Docker worker limits apply](#4-approved-pdfs-are-parsed-and-fully-extracted-on-the-host-before-docker-worker-limits-apply) | low | medium | Host-side parser resource exhaustion |

### Confidence Scale
| Label | Meaning |
| --- | --- |
| high | direct source, configuration, or runtime evidence supports the finding, with no material unresolved reachability or exploitability blocker. |
| medium | source evidence supports a plausible issue, but runtime behavior, deployment configuration, role reachability, type constraints, or exploit reliability still need proof. |
| low | weak or incomplete evidence; include only when the user explicitly wants follow-up candidates in the final report. |

### [1] Model-controlled worker can disclose COPILOT_PROVIDER_API_KEY through tool output and final chat context

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | high |
| Confidence rationale | Direct source and command-construction evidence shows the secret is injected into a shell-capable worker and returned output is not redacted; public deployment reachability is not established. |
| Category | Secret exposure / agent-tool boundary failure |
| CWE | CWE-200 Exposure of Sensitive Information; CWE-522 Insufficiently Protected Credentials; CWE-532 Insertion of Sensitive Information into Log File |
| Affected lines | `cli_agent/services/prompt_service.py:40-41`; `cli_agent/services/docker_runner.py:49-50`; `cli_agent/services/docker_runner.py:113`; `cli_agent/services/artifact_service.py:32-60`; `cli_agent/services/artifact_service.py:149-150`; `cli_agent/controllers/chat_controller.py:45-50`; `cli_agent/agents/chat_agent.py:24-34` |

#### Summary
The worker is explicitly described as model-controlled, but the host passes `COPILOT_PROVIDER_API_KEY` into that worker while also enabling `bash` and returning worker output to callers. Prompt text and Docker filesystem hardening do not stop a process from reading its own environment, and no redaction occurs before `answer.md`, stderr, or tool envelopes are displayed or forwarded.

#### Validation
Validation used static source-to-sink tracing, a bounded command-construction check, and focused tests. The command check showed `COPILOT_PROVIDER_API_KEY=CANARY_SECRET`, `--available-tools=view,create,edit,bash,grep,glob`, and `--allow-all-tools` in the Docker invocation. `python -m pytest tests\test_run_folders_artifacts_and_runner.py tests\test_schemas_and_sources.py -q` passed with 18 tests. No live Docker/Copilot run was needed to prove the source/control/sink tuple.

#### Dataflow
`Streamlit/MCP prompt or approved-source instruction` -> `WorkerPromptService.build_prompt` -> `DockerRunner.build_command` -> `COPILOT_PROVIDER_API_KEY` in container env with shell-capable tools -> worker writes secret to `answer.md` or stderr -> `ArtifactService.collect` returns it -> Streamlit/MCP caller sees it and Streamlit chat sends tool output into the final model call.

#### Reachability
A local/internal user of the proof harness or MCP client can trigger the tool path when the key is configured. The README states the app has no authentication and should not be exposed beyond trusted use without additional controls. That limits public likelihood, but the boundary crossing is real for the intended worker execution workflow.

#### Severity
Final severity is medium. The impact is high because provider credential disclosure is materially security-relevant, but likelihood is unknown from repository evidence because the app is documented as a local/internal proof harness rather than a public service. Evidence of broad deployment with untrusted users would raise severity; proof that only trusted operators can trigger worker runs would lower it.

#### Remediation
Do not pass provider API keys into the model-controlled worker unless the worker truly needs them. Prefer short-lived scoped tokens injected only into the Copilot process, not general shell environment. Remove `bash` unless required, redact known secret values from stdout/stderr/answer/manifest before returning them, and add tests with canary secrets to prove tool outputs and logs are scrubbed.

### [2] Worker-created symlinks in the writable bind mount can make the host read or overwrite files outside the run folder

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Source tracing shows host file operations follow worker-writable output paths without symlink checks; local Windows symlink reproduction was blocked by OS privilege, so platform behavior remains a deployment caveat. |
| Category | Symlink confused deputy / path traversal across container boundary |
| CWE | CWE-59 Improper Link Resolution Before File Access; CWE-22 Path Traversal; CWE-200 Exposure of Sensitive Information |
| Affected lines | `cli_agent/services/docker_runner.py:33-34`; `cli_agent/services/docker_runner.py:49-50`; `cli_agent/services/docker_runner.py:121-124`; `cli_agent/services/artifact_service.py:32`; `cli_agent/services/artifact_service.py:102-105`; `cli_agent/services/artifact_service.py:108-118`; `cli_agent/services/artifact_service.py:188-189`; `streamlit_app.py:21-31` |

#### Summary
The worker can write inside `/workspace/output`, which is the host run folder bind mount. After the worker exits, host code reads `answer.md`, reads optional artifacts, and writes logs and `manifest.json` under that worker-writable tree without rejecting symlinks or verifying resolved paths remain inside the run folder.

#### Validation
Validation used static trace, existing tests, and a bounded symlink harness attempt. The harness could not create a symlink on this Windows host because administrator privilege is required. That is a local OS constraint, not repository counterevidence. Focused artifact and source tests passed with 18 tests and showed the normal host read/write behavior is covered but symlink rejection is not tested.

#### Dataflow
`attacker-influenced worker` -> creates `output/answer.md`, `output/graphs/leak.png`, or `output/logs/copilot.stdout.log` as a symlink -> host `_write_runner_logs` or `ArtifactService.collect` reads/writes the path -> file contents are returned as tool output/artifact or a writable host target is overwritten.

#### Reachability
The path is reachable for any tool run where the worker follows attacker-controlled instructions strongly enough to create a symlink. Exploitability depends on symlink-preserving host/container filesystem behavior, which is realistic on Linux Docker. Repository evidence does not show public ingress, so likelihood is calibrated as unknown rather than high.

#### Severity
Final severity is medium. The impact is high because this breaks the intended worker-to-host filesystem boundary, but deployment reachability and local symlink behavior are not fully proven. A Linux bind-mount reproduction reading a sensitive host file would raise severity; a host configuration that rejects symlink creation/following would lower it.

#### Remediation
Treat worker output as hostile. Use no-follow file opens or reject symlinks with `lstat` before every host read/write under the output tree. After resolving paths, require containment under the intended run/output directory and require regular files. Write logs and manifests to host-created paths that the worker cannot replace, and add regression tests with symlinked `answer.md`, `logs`, CSV, and PNG paths.

### [3] Model-controlled worker has unrestricted default Docker network egress despite network-boundary assumptions

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | high |
| Confidence rationale | Direct command-construction and test evidence shows no default network restriction, while the worker has shell-capable and network-capable tools; reachable targets depend on deployment network topology. |
| Category | Container egress control failure |
| CWE | CWE-200 Exposure of Sensitive Information; CWE-922 Insecure Storage or Transmission of Sensitive Information |
| Affected lines | `cli_agent/services/docker_runner.py:27-29`; `cli_agent/services/docker_runner.py:49-50`; `cli_agent/services/docker_runner.py:97-113`; `cli_agent/settings.py:38`; `cli_agent/settings.py:59-61`; `worker/Dockerfile:1-5`; `cli_agent/services/prompt_service.py:21` |

#### Summary
When `CLI_AGENT_DOCKER_NETWORK` is unset, DockerRunner does not provide a deny-by-default network mode. The worker is model-controlled, has `bash`, Python, Node, git, and CA certificates, and may hold approved source copies and provider environment values. The only no-network statement is prompt text and README guidance that network restriction is external.

#### Validation
Validation used static trace, command-construction checks, tests, and documentation. The command check showed `--network` is absent by default while shell-capable tools are present. The focused tests passed and include an assertion that `--network` is absent by default and only added when configured.

#### Dataflow
`attacker-influenced worker` -> shell/Python/Node network client inside container -> Docker default bridge networking -> arbitrary external or host/internal destination -> exfiltration of copied approved sources, prompts, artifacts, or provider env values.

#### Reachability
A user who can trigger a worker run can influence execution through prompts or approved-source prompt injection. The precise network targets depend on Docker host policy, but the repository default leaves egress to Docker defaults. Operator-provided `CLI_AGENT_DOCKER_NETWORK` is a mitigation, not the default control.

#### Severity
Final severity is medium. The impact is high because uncontrolled egress from model-controlled execution can leak credentials and become an internal network pivot. Likelihood is unknown from repository deployment evidence, so the matrix lands at medium. Evidence of deployment with untrusted users and internal service reachability would raise severity; defaulting to `--network=none` would lower it.

#### Remediation
Default to `--network=none` for worker runs, then explicitly opt into a constrained provider-only network when needed. Enforce egress outside the prompt, document the secure default, and add tests that the default Docker command contains a deny-by-default network mode. Keep provider credentials out of general-purpose shell environments.

### [4] Approved PDFs are parsed and fully extracted on the host before Docker worker limits apply

| Field | Value |
| --- | --- |
| Severity | low |
| Confidence | medium |
| Confidence rationale | Static order-of-operations and tests prove host-side extraction occurs before worker limits; no malicious PDF PoC was generated and default active config uses a markdown sample. |
| Category | Host-side parser resource exhaustion |
| CWE | CWE-400 Uncontrolled Resource Consumption; CWE-770 Allocation of Resources Without Limits or Throttling |
| Affected lines | `cli_agent/managers/tool_manager.py:85-96`; `cli_agent/services/run_folder_service.py:36-43`; `cli_agent/services/run_folder_service.py:57-73`; `cli_agent/services/run_folder_service.py:80-84`; `cli_agent/services/approved_sources.py:99-118` |

#### Summary
PDF extraction runs in the host Python process before the Docker worker starts. Source byte limits bound the compressed PDF size but not parser CPU, page count, extracted text expansion, or output file size. A malicious approved PDF can therefore exhaust host resources outside the container limits intended for worker execution.

#### Validation
Validation used static order-of-operations tracing and existing tests. `ToolManager.run_tool` calls `RunFolderService.copy_sources` before `DockerRunner.run`; `_extract_pdf_text` constructs `PdfReader`, loops every page with `extract_text`, accumulates all text, and writes the full `.pdf.txt`. Existing tests confirm PDF text preparation happens before worker execution. No malicious PDF was created during the scan.

#### Dataflow
`approved third-party PDF` -> exact `source_paths` allowlist validation -> `copy_sources` -> `_extract_pdf_text` on host -> `PdfReader` and per-page `extract_text` -> unbounded `page_blocks` accumulation and `.pdf.txt` write -> host CPU, memory, or disk exhaustion before Docker timeout/resource limits.

#### Reachability
The default checked-in source config uses a small markdown file, but the repo includes PDF corpus tooling and an example PDF approved-source configuration. The issue matters when approved corpora include third-party or user-provided PDFs and a user/model can request them.

#### Severity
Final severity is low. Impact is medium availability loss to the app process, but the default active config is not a PDF and exploitability requires a malicious PDF to be approved. A reproduced small malicious PDF that reliably hangs or exhausts memory in a common configured corpus would raise severity; moving extraction into the constrained worker would lower it.

#### Remediation
Move PDF extraction into the same constrained worker environment or a separate subprocess with time, memory, output-size, and page-count limits. Add maximum extracted text bytes per source and fail closed when exceeded. Add tests for page-count and extracted-output caps, and keep compressed-byte limits as a separate prefilter rather than the only control.


# Reviewed Surfaces

| Surface | Risk Area | Outcome | Notes |
| --- | --- | --- | --- |
| Streamlit/MCP model tool boundary | Secret/data exposure | Reported | `CLIAGENT-001` covers provider key exposure through a shell-capable worker and returned tool output. |
| Docker worker bind mount to host post-processing | Path traversal / symlink confused deputy | Reported | `CLIAGENT-002` covers host reads/writes under worker-writable output paths without symlink or containment checks. |
| Docker worker network | SSRF / network egress / data exfiltration | Reported | `CLIAGENT-003` covers default Docker networking for model-controlled workers when `CLI_AGENT_DOCKER_NETWORK` is unset. |
| Approved source ingestion | Parser resource exhaustion | Reported | `CLIAGENT-004` covers host-side PDF parsing before Docker worker limits apply. |
| Approved source path selection | Path traversal / arbitrary file read | Rejected | Configured paths are resolved under `repo_root`; model requests must exactly match loaded approved strings before source copy. |
| Host Docker subprocess invocation | Host command injection / RCE | Rejected | Docker command is built as an argv list and run without a shell; prompt text is not interpolated into a host shell. |
| OpenAI-compatible chat provider client | SSRF via app-side HTTP client | Rejected | `chat_base_url` is operator configuration, not user/model-selected input. |
| Streamlit rendering | XSS / unsafe rendering | Rejected | No `unsafe_allow_html=True` was found; content-based secret and symlink risks are reported separately. |
| MCP server exposure | Missing auth / network listener | Rejected | The MCP server is stdio-based and delegates to `ToolManager` validation. |
| Dependency and worker image build inputs | Supply chain | Rejected | Floating image/package versions are hardening concerns, but no concrete compromised version or advisory path was validated. |
| Worker runtime availability controls | DoS | Rejected with exception | Worker semaphore, timeout, PID, tmpfs, and source byte controls exist; the host-side PDF extraction exception is reported as `CLIAGENT-004`. |
| Retained run artifacts | Sensitive data exposure | Rejected with exception | Existing retained manifest had no secrets; secret leakage into errors/manifests is covered by `CLIAGENT-001`. |
| Generated approved-source settings | Path/config safety | Rejected with exception | Generated paths are repo-relative and oversized PDFs are rejected; approved PDFs still trigger `CLIAGENT-004`. |


## Open Questions And Follow Up
- Run a targeted fix review for `cli_agent/services/docker_runner.py` and `cli_agent/services/artifact_service.py` after changing worker environment handling, default Docker networking, and symlink-safe artifact collection.
- Add a focused regression test that injects a canary `COPILOT_PROVIDER_API_KEY` and asserts no tool envelope, stderr, manifest, or final chat message contains the canary.
- On a Linux Docker host, reproduce the symlink artifact path with `output/answer.md`, `output/logs/copilot.stdout.log`, and `output/graphs/leak.png` to calibrate platform-specific exploitability.
- Add a bounded parser harness for `cli_agent/services/run_folder_service.py` that enforces page-count and extracted-byte limits for approved PDFs.
