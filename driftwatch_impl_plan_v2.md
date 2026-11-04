# Driftwatch: Implementation Plan

Companion to `driftwatch_architecture.md`. This document says what to build, in what order, with which agents, in which folders, and how they talk to each other.

---

## 1. Tech choices

| Area | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Fast to build, `ast` for symbol extraction, pydantic for contracts |
| Contracts | pydantic v2 models | Validation on every hop, JSON-schema export for LLM output |
| CLI | `typer` | Small, good help text |
| Git access | `git` CLI via `subprocess` | No extra dependency; same results locally and in CI |
| LLM access | Pluggable provider layer. Default provider uses the `openai` Python library against any OpenAI-compatible endpoint (Baseten or Meta Model API) | Provider and model are config, not code. Hackathon profiles use Meta models (`meta-models/muse-spark-open-1026` on Baseten, Muse Spark on the Meta Model API) |
| Config | YAML file (`driftwatch.config.yaml`) loaded into pydantic models; secrets only from env vars | One validated place for provider, model, logging, budgets |
| Logging | stdlib `logging` with a readable console sink and a structured JSONL file sink | Step-by-step agent trace with key parameters, no extra dependency |
| Tests | `pytest` | Includes prompt-length and contract tests |
| CI | GitHub Actions | Public repo demo |

---

## 2. Agent catalogue

Every agent has one job, one input type, one output type.

### Non-LLM agents

| ID | Agent | Module | Input -> Output |
|---|---|---|---|
| N1 | ContextScanner | `agents/non_llm/context_scanner.py` | `ScanRequest` -> `ContextInventory` |
| N2 | ChangeDetector | `agents/non_llm/change_detector.py` | `ChangeRequest` -> `ChangeSet` |
| N3 | FolderDigester | `agents/non_llm/folder_digester.py` | `DigestRequest` -> `FolderDigest` |
| N4 | Router | `agents/non_llm/router.py` | `ChangeSet` + mapping -> `CheckPlan` |
| N5 | RuleClaimExtractor | `agents/non_llm/rule_claims.py` | `DocText` -> `ClaimSet` |
| N6 | CodeRetriever | `agents/non_llm/code_retriever.py` | `Claim` + folder -> `CodeContext` |
| N7 | RuleChecker | `agents/non_llm/rule_checker.py` | `Claim` -> `Verdict` or `NeedsJudge` |
| N8 | EvidenceValidator | `agents/non_llm/evidence_validator.py` | `Verdict` + `CodeContext` -> validated `Verdict` |
| N9 | MappingStore | `agents/non_llm/mapping_store.py` | `MappingOp` -> `.drift.json` |
| N10 | Reporter | `agents/non_llm/reporter.py` | `Verdict[]` -> `DriftReport` (+ MR comment, exit code) |
| N11 | UserPrompter | `agents/non_llm/user_prompter.py` | `Question` -> `Answer` |
| N12 | DiffApplier | `agents/non_llm/diff_applier.py` | `FixProposal` + `Answer` -> changed files |

### LLM agents

| ID | Agent | Module | Prompt file | Input -> Output |
|---|---|---|---|---|
| L1 | FeatureScout | `agents/llm/feature_scout.py` | `prompts/feature_scout.txt` | `FeatureScoutRequest` -> `FeatureProposal` |
| L2 | DocMapper | `agents/llm/doc_mapper.py` | `prompts/doc_mapper.txt` | `DocMapRequest` -> `DocMatch` |
| L3 | ClaimExtractor | `agents/llm/claim_extractor.py` | `prompts/claim_extractor.txt` | `ClaimExtractRequest` -> `ClaimSet` |
| L4 | Judge | `agents/llm/judge.py` | `prompts/judge.txt` | `JudgeRequest` -> `Verdict` |
| L5 | SkillAuthor (retired) | `agents/llm/skill_author.py` | `prompts/skill_author.txt` | `AuthorRequest` -> `DocDraft` |
| L6 | DocFixer | `agents/llm/doc_fixer.py` | `prompts/doc_fixer.txt` | `FixRequest` -> `FixProposal` |

The **Orchestrator** (`orchestrator/`) is not an agent. It is plain code that sequences agents and holds no model logic.

---

## 3. Folder structure

Two repositories are involved, and it matters which one a file belongs to:

- **Tool repo:** the Driftwatch source code (the tree below).
- **Target repo:** the repository Driftwatch is run on and evaluates. Driftwatch is run from inside it, and its root is found with `git rev-parse --show-toplevel`. Every path in a claim, mapping, or log is relative to this root.

Files Driftwatch creates or reads **in the target repo**:

| File or folder | Created by | Committed? |
|---|---|---|
| `.drift.json` (feature mapping) | `driftwatch map` | Yes |
| `driftwatch.config.yaml` (LLM profiles, logging, scan rules) | By hand or copied from the tool's template; defaults apply if absent | Yes |
| `.env` (API keys) | Developer; CI uses secrets instead | No |
| `.drift/` (`cache/`, `runs/`, `logs/`) | Every command | No; add it to the target repo's `.gitignore` |
| `.github/workflows/drift-check.yml` | Copied from the tool's `ci/` folder | Yes |
| New or edited `SKILL.md` and docs | `driftwatch map` and `fix`, after approval | Yes |

The tree below is the tool repo. Entries marked `[target repo]` are shown only to document their format; in real use they are created in the target repo. The tool repo keeps sample copies under `tests/fixtures/demo_repo/` for tests and the demo.

```
driftwatch/
├── pyproject.toml
├── Makefile                          # make drift | make eval | make test
├── README.md
├── .drift.json                       # [target repo] committed mapping (generated by `map`)
├── driftwatch.config.yaml            # [target repo] committed tool settings: LLM profiles, logging, scan rules (no secrets)
├── .env.example                      # [target repo] names of required env vars (BASETEN_API_KEY, MODEL_API_KEY, optional MODEL_API_BASE_URL)
├── .gitignore                        # includes .drift/
├── src/driftwatch/
│   ├── __init__.py
│   ├── cli/
│   │   ├── main.py                   # typer app: scan, map, check, fix
│   │   └── render.py                 # terminal output helpers
│   ├── contracts/                    # ALL shared message types live here
│   │   ├── envelope.py               # Envelope, AgentId, MessageType, ErrorInfo; every payload type has log_summary()
│   │   ├── context.py                # ContextInventory, ContextFile
│   │   ├── features.py               # FeatureProposal, DocMatch, FolderDigest
│   │   ├── changes.py                # ChangeSet, CheckPlan
│   │   ├── claims.py                 # Claim, ClaimSet, CodeContext
│   │   ├── verdicts.py               # Verdict, DriftReport
│   │   ├── fixes.py                  # FixRequest, FixProposal, DocDraft
│   │   └── mapping.py                # DriftFile (the .drift.json schema)
│   ├── agents/
│   │   ├── base.py                   # Agent protocol: handle(Envelope[In]) -> Envelope[Out]
│   │   ├── non_llm/
│   │   │   ├── context_scanner.py
│   │   │   ├── change_detector.py
│   │   │   ├── folder_digester.py
│   │   │   ├── router.py
│   │   │   ├── rule_claims.py
│   │   │   ├── code_retriever.py
│   │   │   ├── rule_checker.py
│   │   │   ├── evidence_validator.py
│   │   │   ├── mapping_store.py
│   │   │   ├── reporter.py
│   │   │   ├── user_prompter.py
│   │   │   └── diff_applier.py
│   │   └── llm/
│   │       ├── base_llm_agent.py     # loads prompt, builds request, validates reply
│   │       ├── feature_scout.py
│   │       ├── doc_mapper.py
│   │       ├── claim_extractor.py
│   │       ├── judge.py
│   │       ├── skill_author.py
│   │       └── doc_fixer.py
│   ├── llm/
│   │   ├── client.py                 # provider-agnostic client: profile lookup, validate, retry, log
│   │   ├── types.py                  # LLMRequest, LLMResponse, Usage, Capabilities
│   │   ├── registry.py               # @register_provider + dotted-path plug-in loading
│   │   ├── providers/
│   │   │   ├── base.py               # LLMProvider protocol
│   │   │   ├── openai_compatible.py  # openai library: Baseten, Meta Model API, GPT, Fireworks, Modal
│   │   │   ├── anthropic.py          # stub for a future Claude provider
│   │   │   └── mock.py               # canned replies for tests
│   │   ├── budget.py                 # per-run call/token budget
│   │   └── prompts/                  # one .txt per LLM agent, each <= 500 chars
│   │       ├── feature_scout.txt
│   │       ├── doc_mapper.txt
│   │       ├── claim_extractor.txt
│   │       ├── judge.txt
│   │       ├── skill_author.txt
│   │       ├── doc_fixer.txt
│   │       └── retry.txt
│   ├── orchestrator/
│   │   ├── bus.py                    # builds envelopes, validates, persists to .drift/runs/
│   │   ├── onboard.py                # scan -> map workflow
│   │   ├── check.py                  # MR/local check workflow
│   │   └── fix.py                    # fix workflow
│   ├── config/
│   │   ├── models.py                 # pydantic: DriftConfig, LLMConfig, ProfileConfig, LoggingConfig
│   │   └── loader.py                 # file + env + CLI merge; secret redaction for `config show`
│   ├── observability/
│   │   ├── logger.py                 # StepLogger and run context (run id, step n/N, feature)
│   │   ├── decorators.py             # @logged_step for agents
│   │   ├── summarize.py              # truncation rules and redact keys
│   │   ├── sinks.py                  # console (pretty/plain/json) and JSONL file
│   │   └── viewer.py                 # `driftwatch logs` filtering and pretty-print
│   ├── cache/
│   │   └── store.py                  # claim cache + verdict cache under .drift/cache/
│   └── gitutil.py                    # thin wrappers over git commands
├── ci/
│   └── drift-check.yml               # copied to .github/workflows/
├── eval/
│   ├── drifts.yaml                   # ~20 labeled injected drifts + negative cases
│   ├── inject.py                     # applies a drift to a scratch copy of a repo
│   └── run_eval.py                   # reports caught / missed / false alarms
├── tests/
│   ├── test_contracts.py
│   ├── test_prompts.py               # asserts every prompt <= 500 chars
│   ├── test_config.py                # precedence, secret redaction, lazy env-var check
│   ├── test_providers.py             # registry, plug-in loading, structured-output fallback
│   ├── test_logging.py               # redaction, truncation, step events, JSONL validity
│   ├── test_router_matrix.py
│   ├── test_rule_checker.py
│   ├── test_evidence_validator.py
│   └── fixtures/
│       └── demo_repo/                # small repo with auth/ and payments/
└── docs/
    ├── driftwatch_architecture.md
    └── driftwatch_implementation_plan.md
```

Runtime-only folder (gitignored): `.drift/` containing `cache/`, `runs/<correlation_id>/` (full envelopes), and `logs/` (run logs).

---

## 4. Agent-to-agent communication

### 4.1 Rules

1. Every hop is an **Envelope** with a typed payload. No plain-text hand-offs.
2. Payload types live only in `contracts/`. Agents import them and never define ad-hoc dicts.
3. The bus validates the payload on send and on receive. A validation failure becomes an `ErrorInfo` envelope, not an exception swallowed in the middle of a run.
4. Every envelope is persisted as JSON in `.drift/runs/<correlation_id>/NN_<type>.json`. This makes CI runs replayable and lets `fix` read a past run.
5. Evidence is always structured: `{"file": "services/auth/session.py", "line": 42}`, never a free string.
6. Every payload type implements `log_summary()`, which returns the few fields worth logging (see section 8). Agents never decide ad hoc what to log.

### 4.2 Envelope

```python
class Envelope(BaseModel, Generic[T]):
    schema_version: Literal["1"] = "1"
    msg_id: str                 # uuid
    correlation_id: str         # one per CLI run
    type: MessageType           # e.g. "ChangeSet", "JudgeRequest", "Verdict"
    sender: AgentId             # "N2.ChangeDetector"
    recipient: AgentId          # "N4.Router"
    created_at: datetime
    payload: T
    error: ErrorInfo | None = None
```

Example (ChangeDetector -> Router):

```json
{
  "schema_version": "1",
  "msg_id": "6f1c...",
  "correlation_id": "run-2026-11-01-0007",
  "type": "ChangeSet",
  "sender": "N2.ChangeDetector",
  "recipient": "N4.Router",
  "created_at": "2026-11-01T08:10:00Z",
  "payload": {
    "base": "origin/main",
    "head": "9d8e7f6",
    "files": [
      {"path": "services/auth/session.py", "status": "M", "hash": "c3a1..."},
      {"path": "services/auth/SKILL.md", "status": "M", "hash": "b71e..."}
    ]
  },
  "error": null
}
```

### 4.3 Message catalogue

| Type | From -> To | Key payload fields |
|---|---|---|
| `ScanRequest` | Orchestrator -> N1 | repo_root, deny_globs |
| `ContextInventory` | N1 -> Orchestrator | files[{path, hash, kind: known\|candidate}] |
| `FeatureScoutRequest` | Orchestrator -> L1 | tree (depth-limited), manifests, owners |
| `FeatureProposal` | L1 -> N11 | features[{name, folder, reason}] |
| `DigestRequest` / `FolderDigest` | Orchestrator -> N3 / N3 -> Orchestrator | folder; tree, symbols, commands, file_heads |
| `DocMapRequest` | Orchestrator -> L2 | feature{name, folder}, docs[{path, excerpt}] |
| `DocMatch` | L2 -> Orchestrator | feature, doc, match, quote, confidence |
| `AuthorRequest` / `DocDraft` | Orchestrator -> L5 / L5 -> N11 | digest; path, markdown |
| `MappingOp` | Orchestrator -> N9 | op (add_feature, set_docs, set_status, resolve_duplicate) |
| `ChangeRequest` / `ChangeSet` | Orchestrator -> N2 / N2 -> N4 | base, head; files[{path, status, hash}] |
| `CheckPlan` | N4 -> Orchestrator | features[{name, case, code_files, doc_files}], global_docs, unmapped_folders |
| `DocText` / `ClaimSet` | Orchestrator -> N5 or L3 / back | doc path, numbered lines; claims[Claim] |
| `CodeContext` | N6 -> Orchestrator | claim_id, snippets[{file, start, end, text}] |
| `JudgeRequest` | Orchestrator -> L4 | claim, snippets |
| `Verdict` | N7 or L4 -> N8 | claim_id, verdict, evidence[{file, line}], reason, needs_human, tier |
| `DriftReport` | N10 -> CLI / CI | counts, verdicts, per-feature status, mode |
| `FixRequest` | Orchestrator -> L6 | doc path, doc text, contradicted[{claim, evidence}] |
| `FixProposal` | L6 -> N11 | doc path, diff, skipped[claim ids] |
| `Question` / `Answer` | Orchestrator -> N11 / N11 -> Orchestrator | kind (confirm_features, pick_duplicate, approve_diff); options; choice |

### 4.4 Core payload sketches

```python
class Claim(BaseModel):
    id: str                    # hash(doc_path + line + text)
    doc_path: str
    line: int
    text: str
    kind: Literal["path", "symbol", "command", "behavior", "convention"]
    feature: str               # feature name or "global"
    refs: list[str] = []       # extracted paths/symbols, if any

class Evidence(BaseModel):
    file: str
    line: int

class Verdict(BaseModel):
    claim_id: str
    verdict: Literal["supported", "contradicted", "unverifiable"]
    evidence: list[Evidence]
    reason: str = ""
    needs_human: bool = False
    tier: Literal["deterministic", "behavioral", "judge"]
```

---

## 5. LLM agent rules

### 5.1 Prompt limit

- Every prompt text is **500 characters or fewer**. `tests/test_prompts.py` fails the build otherwise.
- Prompts contain only: role, input description, output description, and two or three hard rules. No examples, no data.

### 5.2 Structured request to the LLM

The model receives two things:

1. **System message:** the short prompt from `llm/prompts/<agent>.txt`.
2. **User message:** the request payload serialized as JSON (`model_dump_json()` of the request type).

The expected reply schema (exported from the output pydantic type) goes through the provider's structured-output mechanism and is never pasted into the prompt, so it does not count against the 500 characters. If a provider cannot do structured output, the schema is added to the request JSON as data, which is still not prompt text. The client then validates the reply against the pydantic type. On failure it retries once, sending `retry.txt` plus the validation errors as JSON. A second failure becomes an `ErrorInfo` envelope and the claim ends up `unverifiable`.

```python
# llm/client.py (shape)
def call(agent_id: str, prompt: str, request: BaseModel, out_type: type[T]) -> T:
    profile = config.resolve_profile(agent_id)      # flag > env > agents.<id> > default_profile
    provider = registry.get(profile)                 # cached per profile
    req = LLMRequest(system=prompt,
                     user_json=request.model_dump_json(),
                     response_schema=out_type.model_json_schema(),
                     mode=profile.structured_output,
                     temperature=config.llm.call.temperature,
                     meta=CallMeta(agent_id=agent_id))
    budget.check()                                   # raises BudgetExceeded
    resp = provider.complete(req)                    # logged: profile, model, tokens, latency
    return validate_or_retry(resp, out_type, req)
```

Provider, base URL, model, and key variable all come from the selected profile in `driftwatch.config.yaml` (sections 6 and 7). Keys live only in environment variables or a gitignored `.env`, never in the repo.

### 5.3 Prompts

Each block below is the entire file content for that agent. Verified at 500 characters or fewer.

**`feature_scout.txt` (L1)**

```prompt
You find product features in a repo. Input: JSON with folder tree, manifests, owners. Output: JSON features list with name, folder, reason. A feature is a top-level functional area (auth, gateway, licensing). Exclude tests, build, tooling, docs and nested helper folders. Prefer fewer, clearer features. Skip anything uncertain.
```

**`doc_mapper.txt` (L2)**

```prompt
Decide if a doc genuinely explains a feature. Input: JSON with feature name, folder, doc excerpts. Match only if the doc describes the feature's behavior, not merely names it. Output JSON: match (bool), quote (1-2 verbatim lines from the doc proving it), confidence (0-1). If you cannot quote proof, match must be false.
```

**`claim_extractor.txt` (L3)**

```prompt
Split a doc into atomic, checkable claims about code behavior or conventions. Input: JSON with numbered doc lines. Output JSON list: line, text, kind (behavior|convention). One fact per claim. Copy text verbatim. Skip opinions, advice, and claims about paths, commands or symbols (rules handle those).
```

**`judge.txt` (L4)**

```prompt
Judge one claim against code. Input: JSON with claim and code snippets labeled file:line. Output JSON: verdict (supported|contradicted|unverifiable), evidence (file:line list, only from the input), reason (max 20 words), needs_human (true if the code looks buggy rather than the doc stale). No evidence means unverifiable.
```

**`skill_author.txt` (L5)**

```prompt
Draft a SKILL.md for one feature. Input: JSON digest with folder tree, symbols, commands, file heads. Output JSON: markdown string with frontmatter (name, description) then sections Purpose, Key files, Commands, Conventions. State only facts visible in the input, one per line, naming the file. Do not guess.
```

**`doc_fixer.txt` (L6)**

```prompt
Fix a doc so it matches code. Input: JSON with the doc text and contradicted claims with evidence. Output JSON: diff (unified diff of the doc only), skipped (claim ids). Change only the lines of contradicted claims. Never edit code. Skip claims with needs_human true.
```

**`retry.txt`**

```prompt
Your last JSON failed validation. The errors are in the input. Reply with corrected JSON only, same schema.
```

### 5.4 Guardrails around LLM output

- **EvidenceValidator (N8)** rejects any verdict whose `file:line` was not in the snippets sent to the model.
- A `supported` or `contradicted` verdict with empty evidence is converted to `unverifiable`.
- DocMapper results with an empty `quote` are forced to `match=false`.
- Fixer output is applied only after user approval, and only to doc files.
- Request size is capped (about 6k tokens of snippets). CodeRetriever truncates, prioritizing files changed in the MR.

---

## 6. LLM provider layer

The LLM client knows no vendor. It talks to a **provider**, chosen by config. Switching between Baseten and the Meta Model API, changing the model name, or adding GPT or Claude later is a config change or one new file. No agent changes.

```
LLM agent --> LLM client --> LLMProvider (plug-in) --> vendor API
                  |                 ^
                  |                 +-- selected by a profile in driftwatch.config.yaml
                  +-- validates reply, retries, enforces budget, writes logs
```

### 6.1 Normalized types (`llm/types.py`)

Agents and the client only see these types, never a vendor response object.

```python
class CallMeta(BaseModel):          # for logging only, never sent to the model
    agent_id: str
    correlation_id: str | None = None
    claim_id: str | None = None
    feature: str | None = None

class LLMRequest(BaseModel):
    system: str                     # the short prompt (<= 500 chars)
    user_json: str                  # structured request payload as JSON text
    response_schema: dict | None    # JSON schema of the expected reply
    mode: Literal["json_schema", "json_object", "prompt_only"] = "json_schema"
    temperature: float = 0
    max_output_tokens: int | None = None
    meta: CallMeta

class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None

class LLMResponse(BaseModel):
    text: str                       # raw reply text (JSON)
    provider: str
    model: str
    usage: Usage
    latency_ms: int
    response_id: str | None = None

class Capabilities(BaseModel):
    json_schema: bool = False
    json_object: bool = False
    reasoning_effort: bool = False
```

### 6.2 Provider protocol and registry

```python
# llm/providers/base.py
class LLMProvider(Protocol):
    capabilities: Capabilities
    def __init__(self, profile: ProfileConfig) -> None: ...
    def complete(self, req: LLMRequest) -> LLMResponse: ...

# llm/registry.py
_PROVIDERS: dict[str, type[LLMProvider]] = {}

def register_provider(name: str):
    def deco(cls): _PROVIDERS[name] = cls; return cls
    return deco

def get(profile: ProfileConfig) -> LLMProvider:
    # profile.provider is either a registered name ("openai_compatible")
    # or a dotted path ("my_pkg.my_module:MyProvider") imported on demand.
    ...
```

### 6.3 Built-in providers

| Provider name | Library | Use for | Status |
|---|---|---|---|
| `openai_compatible` | `openai` | Baseten, Meta Model API, OpenAI GPT models, Fireworks, Modal endpoints, any OpenAI-compatible server | Build in Phase 0 |
| `mock` | none | Unit tests with canned replies | Build in Phase 0 |
| `anthropic` | `anthropic` | Claude models | Stub now, implement later |
| `"pkg.module:Class"` | any | Your own provider without touching core code | Supported by the registry |

The main provider, using the `openai` library:

```python
# llm/providers/openai_compatible.py
import os
from openai import OpenAI


class MissingKeyError(RuntimeError):
    pass

@register_provider("openai_compatible")
class OpenAICompatibleProvider:
    capabilities = Capabilities(json_schema=True, json_object=True, reasoning_effort=True)

    def __init__(self, profile: ProfileConfig):
        self.profile = profile
        key = os.environ.get(profile.api_key_env, "")
        if not key:
            raise MissingKeyError(f"{profile.api_key_env} is not set: add it to .env")
        base_url = (os.environ.get(profile.base_url_env or "") or profile.base_url)
        self.client = OpenAI(
            api_key=key,
            base_url=base_url,
            max_retries=profile.max_retries,   # SDK-level retries for timeouts, 429, 5xx
            timeout=profile.timeout_s,
        )

    def complete(self, req: LLMRequest) -> LLMResponse:
        kwargs = {}
        if req.mode == "json_schema":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "reply", "schema": req.response_schema, "strict": True},
            }
        elif req.mode == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        if self.profile.reasoning_effort:
            kwargs["reasoning_effort"] = self.profile.reasoning_effort
        if self.profile.extra_body:
            kwargs["extra_body"] = self.profile.extra_body   # vendor-specific parameters
        r = self.client.chat.completions.create(
            model=self.profile.model,
            temperature=req.temperature,
            messages=[{"role": "system", "content": req.system},
                      {"role": "user", "content": req.user_json}],
            **kwargs,
        )
        return to_llm_response(r, self.profile)   # fills usage, latency, model, response id
```

### 6.4 Structured-output ladder

Not every endpoint supports every response format. The profile sets the preferred mode, and the client falls back one step at a time if the endpoint rejects it.

| Mode | What is sent | Used when |
|---|---|---|
| `json_schema` | Reply schema via the provider's structured-output parameter | Preferred |
| `json_object` | JSON mode, schema included in the request JSON as `reply_schema` | Endpoint rejects schemas |
| `prompt_only` | No format parameter; schema included in the request JSON as `reply_schema` | Endpoint rejects both |

Rules:

- On a 400-type error about the response format, the client downgrades one step for the rest of the run and logs a WARNING (`structured output downgraded json_schema -> json_object`).
- The reply is always validated against the pydantic type, whichever mode was used.
- `reply_schema` is request data, so the 500-character prompt limit is unaffected.

### 6.5 Profiles used in this project

| Profile | Base URL | Key variable | Model | Notes |
|---|---|---|---|---|
| `baseten` | From the Baseten quickstart | `BASETEN_API_KEY` | `meta-models/muse-spark-open-1026` | Hackathon-specific model name; the public docs use a different one |
| `meta_api` | `https://api.meta.ai/v1` (override with `MODEL_API_BASE_URL`) | `MODEL_API_KEY` | `muse-spark-1.1` | Base URL, key variable, and the `openai` library call are confirmed working in your own client (4 SDK retries, 180 s timeout). The model name and the structured-output parameter come from LiteLLM's Meta provider page, so confirm them with `driftwatch llm ping` |

Hackathon rule: the project must use Meta models. Ship with the `baseten` and `meta_api` profiles active. GPT, Claude, and other profiles stay commented out as examples of extensibility.

### 6.6 Adding another model or library

1. **Same API shape (OpenAI-compatible):** add a profile in the config with `provider: openai_compatible`, a `base_url`, an `api_key_env`, and a `model`. No code.
2. **Different SDK:** add one file under `llm/providers/` implementing `LLMProvider` and decorate it with `@register_provider("name")`, then reference it from a profile. Or point `provider` at a dotted path in your own package.
3. **Per-agent models:** set `llm.agents.<agent_id>` to a profile name, for example a stronger model for the Judge.

### 6.7 Error handling

| Situation | Behavior |
|---|---|
| Timeout, 429, 5xx | The `openai` SDK retries up to the profile's `max_retries` (no second retry loop on top); then an `ErrorInfo` envelope and the claim becomes `unverifiable` |
| Response-format rejected | Downgrade the ladder once, log a WARNING |
| Reply fails schema validation | One retry using `retry.txt` plus the errors; then `ErrorInfo` |
| Missing API key | `MissingKeyError` naming the variable, raised when that profile is first used (not at startup, so unused profiles do not matter) |
| Budget exceeded | Remaining claims become `unverifiable`; logged once |

---

## 7. Configuration file

All tool settings live in one committed file, `driftwatch.config.yaml`, separate from `.drift.json`. The mapping file changes when features are onboarded; the config file changes when you change how the tool behaves.

### 7.1 Example

```yaml
version: 1

llm:
  default_profile: baseten
  profiles:
    baseten:
      provider: openai_compatible
      base_url: "https://inference.baseten.co/v1"   # confirm in the Baseten quickstart
      api_key_env: BASETEN_API_KEY
      model: meta-models/muse-spark-open-1026
      structured_output: json_schema                 # json_schema | json_object | prompt_only
      timeout_s: 60
    meta_api:
      provider: openai_compatible
      base_url: "https://api.meta.ai/v1"
      base_url_env: MODEL_API_BASE_URL               # optional override, read if set
      api_key_env: MODEL_API_KEY
      model: muse-spark-1.1                          # confirm exact name
      structured_output: json_schema
      reasoning_effort: medium                       # optional; sent only if set
      timeout_s: 180
      max_retries: 4                                 # SDK retries; default is 2 if omitted
    # openai:                                        # example of extensibility
    #   provider: openai_compatible
    #   base_url: "https://api.openai.com/v1"
    #   api_key_env: OPENAI_API_KEY
    #   model: <model name>
    # claude:
    #   provider: anthropic                          # needs the anthropic provider implemented
    #   api_key_env: ANTHROPIC_API_KEY
    #   model: <model name>
  agents:                                            # optional per-agent override of default_profile
    judge: meta_api
    doc_mapper: meta_api
  call:
    temperature: 0
    validation_retries: 1                        # re-ask after a schema failure; network retries are the SDK's
  budget:
    max_calls_per_run: 200
    max_input_tokens_per_call: 6000

logging:
  level: INFO                  # TRACE | DEBUG | INFO | WARNING | ERROR
  console:
    enabled: true
    format: pretty             # pretty | plain | json
  file:
    enabled: true
    dir: .drift/logs
    keep_last_runs: 20
  max_value_chars: 120         # longer strings are truncated in logs
  max_list_items: 3            # longer lists show count plus first items
  redact_keys: [api_key, authorization, token, secret, password]

scan:
  deny_globs: ["**/CHANGELOG.md", "**/LICENSE*.md", "**/node_modules/**", "**/vendor/**"]
  known_context_names: ["AGENTS.md", "SKILL.md", "CLAUDE.md", "GEMINI.md"]

check:
  default_mode: warn           # warn | enforce

cache:
  dir: .drift/cache
```

### 7.2 Rules

- **Precedence (highest wins):** CLI flags (`--profile`, `--model`, `-v`) > environment variables (`DRIFT_LLM_PROFILE`, `DRIFT_LOG_LEVEL`) > config file > built-in defaults.
- **No secrets in the file.** A profile names the environment variable (`api_key_env`). Keys come from the environment or a gitignored `.env`. `.env.example` lists the names.
- **Validated on load** by pydantic. Errors say exactly which key is wrong. A missing API key is only an error for a profile that is actually used.
- **Inspect it:** `driftwatch config show` prints the resolved config with secrets redacted and shows which source each value came from.
- **Test a profile:** `driftwatch llm ping --profile meta_api` makes one tiny structured call and prints provider, model, latency, and which structured-output mode worked.

---

## 8. Logging and observability

Goal: after any run you can answer "which step ran, with which parameters, what did it return, and why" without a debugger.

### 8.1 Sinks

| Sink | Content | Where |
|---|---|---|
| Console | Readable step lines at the configured level | Terminal or CI log |
| JSONL file | One JSON event per line, same events as the console plus TRACE detail | `.drift/logs/<run_id>.jsonl` |
| Envelopes | Full payloads of every message between agents | `.drift/runs/<run_id>/NN_<Type>.json` |

Every log line that involves a message includes the path of its envelope file, so you can jump from a summary to the full payload.

### 8.2 Levels

| Level | Shows |
|---|---|
| `INFO` (default) | One line per step start and end, with the important parameters and a result summary; LLM call summaries; the final run summary |
| `DEBUG` (`-v`) | Plus decisions and reasons: why the Router chose a case, why a claim went to the judge, cache hit or miss with key, provider fallbacks |
| `TRACE` (`-vv`) | Plus truncated request and reply excerpts for LLM calls (file sink only) |
| `WARNING` / `ERROR` | Always shown: rejected verdicts, downgraded structured output, retries, failures |

### 8.3 Event shape (JSONL)

```json
{"ts": "2026-11-01T10:15:32.412Z", "level": "INFO", "run": "run-0007",
 "step": "2/7", "agent": "N4.Router", "event": "step_end", "duration_ms": 12,
 "feature": null,
 "params": {"base": "origin/main", "changed_files": 14},
 "result": {"cases": {"auth": "both", "payments": "code_only"}, "unmapped_folders": []},
 "envelope": ".drift/runs/run-0007/02_CheckPlan.json"}
```

Event types: `run_start`, `step_start`, `step_end`, `step_skip` (with reason), `decision` (DEBUG), `llm_call`, `cache` (hit or miss), `warning`, `error`, `run_end`.

### 8.4 What each step logs at INFO

| Agent | Important parameters and results |
|---|---|
| N1 ContextScanner | md files found, kept, denied; known vs candidate counts |
| N2 ChangeDetector | base, head, changed file count by status, counts per folder |
| N3 FolderDigester | folder, files digested, symbol count, whether truncated |
| N4 Router | per feature: case, code and doc file counts; unmapped folders; skipped features |
| N5 RuleClaimExtractor | doc, claims found by kind |
| N6 CodeRetriever | claim id, snippet count, characters, files used |
| N7 RuleChecker | claim id, kind, verdict, tier; counts resolved vs sent to judge |
| N8 EvidenceValidator | accepted or rejected, and why (for example "cited line not in provided snippets") |
| N9 MappingStore | operation, feature, keys changed, file written |
| N10 Reporter | totals, mode, exit code, MR comment posted or not |
| N11 UserPrompter | question kind, options count, answer given |
| N12 DiffApplier | doc, hunks applied, re-check result |
| L1 to L6 | feature or doc, input size, result summary (match and confidence, verdict and evidence count, claims returned, diff line count) |
| LLM client | profile, provider, model, structured mode used, attempt number, input size in characters and estimated tokens, token usage, latency, validation result, cache hit or miss |

### 8.5 Summarizing and redaction

- Each payload type's `log_summary()` decides the important fields (section 4.1, rule 6). Logs show only those fields.
- Strings longer than `max_value_chars` are truncated with a length suffix. Lists show their count plus the first `max_list_items` items.
- Never logged: file contents beyond the truncation limit, API keys, auth headers, environment variable values. Keys matching `redact_keys` become `***`.
- Logging the name of the key variable and whether it is set is fine; the value never is.
- Full prompts are not logged; the log shows the prompt file name. Request and reply excerpts appear only at TRACE, truncated, in the JSONL file.

### 8.6 Example console output (`driftwatch check --base origin/main -v`)

```
10:15:30 INFO  run-0007 >> check base=origin/main mode=warn profile=baseten model=meta-models/muse-spark-open-1026
10:15:30 INFO  [1/7] N2.ChangeDetector  start base=origin/main head=9d8e7f6
10:15:30 INFO  [1/7] N2.ChangeDetector  ok 14 files (M=12 A=2) 38ms envelope=.drift/runs/run-0007/01_ChangeSet.json
10:15:30 INFO  [2/7] N4.Router  ok auth=both payments=code_only | unmapped=[] | skipped=gateway(no change) 12ms
10:15:30 DEBUG [2/7] N4.Router  auth: code_files=[services/auth/session.py, +1] doc_files=[services/auth/SKILL.md]
10:15:31 INFO  [3/7] N5.RuleClaimExtractor  feature=auth doc=services/auth/SKILL.md claims=9 (path=3 command=2 symbol=4)
10:15:31 INFO  [4/7] N7.RuleChecker  feature=auth resolved=8 needs_judge=1 contradicted=1
10:15:31 DEBUG [4/7] N7.RuleChecker  claim=a41c path services/auth/legacy.py not found -> contradicted
10:15:31 INFO  [5/7] L3.ClaimExtractor  feature=auth doc=services/auth/SKILL.md cache=miss
10:15:33 INFO  [5/7] LLM  profile=baseten model=meta-models/muse-spark-open-1026 mode=json_schema attempt=1 in=1.2k out=210 tokens 1.9s
10:15:33 INFO  [5/7] L3.ClaimExtractor  ok claims=4
10:15:33 INFO  [6/7] L4.Judge  feature=auth claim=c91f (services/auth/SKILL.md:14) cache=miss profile=meta_api
10:15:35 INFO  [6/7] LLM  profile=meta_api model=muse-spark-1.1 mode=json_schema attempt=1 in=1.8k out=96 tokens 1.9s
10:15:35 INFO  [6/7] L4.Judge  ok contradicted evidence=[services/auth/session.py:42] needs_human=false
10:15:35 WARN  [6/7] N8.EvidenceValidator  rejected claim=c3d2: cited services/auth/token.py:77 not in provided snippets -> unverifiable
10:15:35 INFO  [7/7] N10.Reporter  ok contradicted=2 unverifiable=1 mode=warn exit=0 comment=skipped(local)
10:15:35 INFO  run-0007 << done 5.1s | claims=23 (rules=17 judged=6 cache_hits=9) | llm_calls=2 tokens=3.3k | log=.drift/logs/run-0007.jsonl
```

The step counter (`[n/N]`) comes from the workflow definition in the Orchestrator. Per-feature loops stay within one step and add `feature=<name>` to each line.

### 8.7 Implementation

```python
# observability/decorators.py
def logged_step(agent_id: str):
    def deco(fn):
        def wrapper(env):
            log.step_start(agent_id, summarize(env.payload.log_summary()))
            t0 = perf_counter()
            try:
                out = fn(env)
            except Exception as e:
                log.step_error(agent_id, e, duration_ms(t0)); raise
            log.step_end(agent_id, summarize(out.payload.log_summary()),
                         duration_ms(t0), envelope=bus.last_path)
            return out
        return wrapper
    return deco
```

- Run context (run id, step number, feature) is carried in `contextvars`, so any agent or the LLM client can log without passing them around.
- The bus logs every envelope send and receive at DEBUG, with type, sender, recipient, and file path.
- The LLM client emits the `llm_call` event, so provider and model changes are visible in logs without agent code.
- `driftwatch logs [--run latest|ID] [--agent N7] [--feature auth] [--level DEBUG] [--follow]` filters the JSONL and prints it in the console format.
- In CI, use `--log-format plain` and upload `.drift/logs/` as an artifact on every run.
- Old logs: keep the last `keep_last_runs` run files, delete older ones at the start of a run.

### 8.8 Debugging recipe

1. Re-run with `-v` (or open `driftwatch logs --run latest --level DEBUG`).
2. Find the first WARN or ERROR line, then read the step above it to see its parameters.
3. Open the envelope path printed on that line to see the full input or output.
4. For model issues, re-run with `-vv` to see truncated request and reply excerpts, or run `driftwatch llm ping` to test the profile alone.

---

## 9. Step-by-step implementation

Timeline assumes the 10-day hackathon. Each phase lists what to build, which agents it covers, and how you know it is done.

### Phase 0: Skeleton, contracts, config, logging, providers (Day 1 to early Day 2)

1. Create the repo with the folder structure from section 3 (empty modules are fine).
2. Write `contracts/` types and `Envelope`; give every payload type a `log_summary()`.
3. Write `orchestrator/bus.py`: build, validate, persist, and log envelopes.
4. Write `config/` (models and loader with the precedence rules) and a default `driftwatch.config.yaml` with the `baseten` and `meta_api` profiles (section 7).
5. Write `observability/`: StepLogger, `@logged_step`, summarize and redact helpers, console and JSONL sinks. Wire it into the bus and Orchestrator so every step prints `[n/N] agent` lines (section 8).
6. Write the provider layer: `llm/types.py`, `registry.py`, `providers/openai_compatible.py` (openai library), `providers/mock.py`, an `anthropic.py` stub, and `llm/client.py` with profile resolution, the structured-output ladder, retry, and budget (section 6).
7. Add CLI globals (`--config`, `--profile`, `--model`, `-v`, `--log-format`) and the commands `config show`, `llm ping`, and `logs`.
8. Write tests: `test_prompts.py` (length check), `test_contracts.py`, `test_config.py`, `test_providers.py`, `test_logging.py`.

Done when: `make test` passes; `driftwatch llm ping --profile baseten` and `--profile meta_api` both return a validated object by changing only the profile; any command prints step lines and writes `.drift/logs/<run_id>.jsonl`.

### Phase 1: `scan` and deterministic checks (Days 2-3)

1. **N1 ContextScanner:** `git ls-files '*.md'`, apply deny globs, tag known names.
2. **N5 RuleClaimExtractor:** extract path, command (`make x`, `npm run x`), flag, and backticked symbol claims, with line numbers.
3. **N7 RuleChecker:** path exists, symbol exists (`ast` for Python, regex otherwise), make/npm target exists.
4. **N8 EvidenceValidator** and **N10 Reporter** (terminal + Markdown).
5. CLI: `driftwatch scan` prints inventory and runs deterministic checks on all discovered docs with no setup.

Done when: running `scan` on `tests/fixtures/demo_repo` lists broken references with `file:line`. This is the zero-config first impression for the demo.

### Phase 2: Change detection and pipeline (Days 3-4)

1. **N2 ChangeDetector:** `git diff --name-only <base>...HEAD`, `git hash-object`, `git rev-parse HEAD:<folder>`.
2. **N4 Router:** longest-prefix folder match, `global` handling, the four-case matrix, unmapped-folder warnings. Unit-test all four cases in `test_router_matrix.py`.
3. **N9 MappingStore:** read and validate `.drift.json` (write a hand-made one for now).
4. CLI: `driftwatch check --base origin/main --mode warn|enforce`, writing the `DriftReport`.
5. `ci/drift-check.yml` (section 11): run check, post the MR comment with the embedded JSON block.

Done when: a PR in the demo repo gets a Driftwatch comment; a code-only change that touches no claim stays green.

### Phase 3: `map` (feature discovery and doc mapping) (Days 4-6)

1. **N3 FolderDigester:** tree (depth-limited), public symbols, Makefile/package commands, file heads, all size-capped.
2. **L1 FeatureScout** + **N11 UserPrompter** (confirm/edit the feature list once, never re-ask).
3. **L2 DocMapper:** for each confirmed feature, send candidate docs (excerpts) and require a quote.
4. Duplicate handling in the Orchestrator: two or more matches -> ask the user -> store in `resolutions`.
5. **No dedicated doc:** report `skills/<feature>/SKILL.md` as missing so the user generates it with an external skill generator (L5 SkillAuthor retired; MAP creates no skill files).
6. **N9 MappingStore:** write `.drift.json` with owners from `CODEOWNERS`, status `onboarded`.
7. CLI: `driftwatch map [--feature auth]` (one feature at a time is supported so owners can onboard their own).

Done when: `map` on the demo repo yields `.drift.json` with `auth` and `payments` mapped, one duplicate resolved, one doc created.

### Phase 4: Claim extraction and the judge (Days 6-7)

1. **L3 ClaimExtractor** for behavior and convention claims, cached by doc-file hash.
2. **N6 CodeRetriever:** symbol grep in the feature folder, changed files first, token cap.
3. **L4 Judge** with N8 validation, cached by hash(claim + snippets).
4. Wire the full `check` workflow: tier 1 first, judge only for leftovers, per-run budget.
5. Mark tier 3 findings advisory in the report.

Done when: changing `session_expiry = sliding` to `session_expiry = fixed_15m` makes `check` report a contradiction citing both the `SKILL.md` line and the code line.

### Phase 5: `fix` (Day 8)

1. **L6 DocFixer** with `FixRequest` built from the `DriftReport`.
2. **N12 DiffApplier:** show diff, apply on approval, re-run check on the touched features.
3. `fix` sources: local run (default) or `--pr N` reading the embedded JSON block via `gh pr view --comments`.
4. Skip and list claims with `needs_human`.

Done when: red check -> `driftwatch fix` -> approve -> green check, end to end.

### Phase 6: Evaluation harness (Day 9)

1. Write `eval/drifts.yaml`: about 20 injected drifts (renamed function, removed flag, changed command, undocumented module, changed behavior) plus 5 negative cases (code changes unrelated to any claim).
2. `eval/inject.py` applies each to a scratch copy; `eval/run_eval.py` runs `check` and compares to the labels.
3. Output: caught, missed, false alarms, and which tier caught each.

Done when: `make eval` prints the numbers for the demo slide.

### Phase 7: Demo and polish (Day 10)

1. Pre-run onboarding on the demo repo and commit `.drift.json`; pre-warm the cache.
2. Script: break `auth` (unchanged `SKILL.md`) -> PR -> red check with the exact contradiction -> `driftwatch fix` -> green.
3. Show the negative case: unrelated code change, green.
4. Show the eval numbers.
5. README with the three commands (`scan`, `map`, `check`) and the CI snippet.

---

## 10. CLI specification

| Command | What it does | Output |
|---|---|---|
| `driftwatch scan` | Discover context files, run deterministic checks, no setup needed | Terminal report; writes `.drift/runs/...` |
| `driftwatch map [--feature F]` | Propose features, map docs, resolve duplicates, create missing docs, write `.drift.json` | `.drift.json`, new or edited docs after approval |
| `driftwatch check --base REF [--mode warn\|enforce]` | Run the MR check (same command locally and in CI) | `DriftReport` JSON, Markdown, exit code |
| `driftwatch fix [--pr N]` | Propose doc-only diffs for contradictions, apply after approval | Edited docs, re-check result |
| `driftwatch config show` | Print the resolved config (secrets redacted) and where each value came from | Terminal |
| `driftwatch llm ping [--profile P]` | One tiny structured call to test a provider profile | Provider, model, latency, structured mode that worked |
| `driftwatch logs [--run ID] [--agent A] [--feature F] [--level L] [--follow]` | View and filter agent logs for a run | Pretty-printed log lines |

`make drift` is a one-line wrapper: `driftwatch check --base origin/main`.

Global flags on every command: `--config PATH`, `--profile NAME`, `--model NAME` (override the profile's model), `-v` / `-vv` (DEBUG / TRACE), `--log-format pretty|plain|json`, `--quiet`.

Exit codes: `0` pass or warn-only; `1` contradiction in an `enforced` feature; `2` tool error.

---

## 11. CI workflow (GitHub Actions)

```yaml
name: drift-check
on: [pull_request]
jobs:
  drift:
    runs-on: ubuntu-latest
    permissions: { contents: read, pull-requests: write }
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - uses: actions/cache@v4
        with:
          path: .drift/cache
          key: drift-${{ github.event.pull_request.base.sha }}
          restore-keys: drift-
      - run: pip install -e .
      - run: driftwatch check --base origin/${{ github.base_ref }} --out drift_report.md --log-format plain
        env: { BASETEN_API_KEY: ${{ secrets.BASETEN_API_KEY }}, MODEL_API_KEY: ${{ secrets.MODEL_API_KEY }} }
      - if: always()
        run: gh pr comment ${{ github.event.pull_request.number }} --body-file drift_report.md
        env: { GH_TOKEN: ${{ secrets.GITHUB_TOKEN }} }
      - if: always()
        uses: actions/upload-artifact@v4
        with: { name: drift-logs, path: .drift/logs }
```

The report file ends with `<!-- driftwatch:report {json} -->` for `fix --pr`. Failures show: claim (`doc:line`), contradicting code (`file:line`), suggested fix, and the "code may be wrong" option.

---

## 12. Testing strategy

| Test | Covers |
|---|---|
| `test_prompts.py` | Every file in `llm/prompts/` is 500 characters or fewer |
| `test_config.py` | Precedence (flags > env > file > defaults), secrets never printed, missing key only fails for a used profile |
| `test_providers.py` | Registry lookup, dotted-path plug-in loading, mock provider, structured-output downgrade on a 400 |
| `test_logging.py` | Redaction, truncation, step start/end events with params, JSONL lines parse |
| `test_contracts.py` | Envelope and payload validation, round-trip JSON |
| `test_router_matrix.py` | All four change cases, global docs, unmapped folders |
| `test_rule_checker.py` | Path, symbol, command checks on the fixture repo |
| `test_evidence_validator.py` | Rejects citations not in the provided snippets |
| LLM agents | Mocked client with canned JSON for unit tests; a small set of live smoke tests run manually |
| `make eval` | End-to-end: caught, missed, false alarms |

---

## 13. Scaling to many folders and owners

- Onboarding is **per feature**: `driftwatch map --feature auth`, run by the feature's owner (from `CODEOWNERS`).
- Status flow: `unonboarded` -> `onboarded` (warn-only) -> `enforced` (blocking). The pipeline only checks onboarded and enforced features, so it does not wait for all 50 folders.
- Each feature's onboarding is a small PR touching `.drift.json` and that feature's docs.
- After first onboarding, MR checks are cheap: only features whose code or docs changed are processed, and the cache skips unchanged claims.

---

## 14. Cut line if time runs short

Must have: Phases 0-2, Phase 4 (judge) for at least one feature, Phase 5 fix loop, eval numbers.
Can trim: SkillAuthor (L5), behavioral tier 2 (sandbox run), multi-feature onboarding polish.
Not in v1: IDE extension, other CI systems, auto-merge, dashboards.
