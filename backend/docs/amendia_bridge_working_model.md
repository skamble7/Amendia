# Amendia — Bridge & Working Model (Claude ⇄ Sandeep ⇄ Claude Code)

**Purpose.** The Claude (Cowork) session acts as **reviewer/supervisor** for implementation done by
**Claude Code (CC)** in Sandeep's local VS Code workspace. A device bridge connects the session to the
workspace. Claude writes **documents and prompts, never code**.

**Doc status:** consolidated 2026-08-28; ADR-065 log added + closed out 2026-09-01. Supersedes the 2026-08-13 project-doc version; kept on disk from
now on (`backend/docs/amendia_bridge_working_model.md`) with a mirror at project doc
`claude/amendia_bridge_working_model.md`.

---

## Locations

- **Workspace root (code):** `/Users/sandeep/Documents/Projects/Amendia` (macOS, device `sandeeps-macbook-pro-local`)
- **ADRs:** `backend/docs/adr/ADR-0XX-*.md` — on disk through **ADR-065**; **next is ADR-066**. Always
  `ls backend/docs/adr/` before writing to confirm.
- **Docs root + doc map:** `backend/docs/` (see its `README.md`); front door is
  `backend/docs/methodology/amendia_operating_model.md`.
- **CC build prompts:** `backend/docs/_build-prompts/claude_code_prompt_*.md` (on disk) **and** a durable
  copy as project doc `claude/claude_code_prompt_*.md`.
- **CC implementation reports:** `backend/docs/_build-reports/<prompt_slug>_report.md` — CC writes these;
  Claude reads them first at review time.
- **Design mockups:** `backend/docs/design/*.html` (mirrored to `claude/design/`).
- **Known issues:** `backend/docs/known-issues/cleanup-backlog.md` (the CB register — single on-disk source)
  and `known-issues/vulnerability-scan-2026-08-19.md`.
- **Engineering notes:** `backend/docs/engineering/` — incl. `amendia_pii_processor_gap_analysis.md` and
  `running-e2e-tests.md`.
- **Authoring guides:** `backend/docs/methodology/cohort_authoring_guide.html` (cohort DAG + SLA, ADR-064).
  **§6 "Situations — which SLA catches what" added 2026-09-01**: the guide taught the model concept-first, so
  an author arriving with a *worry* ("what if the trigger never comes?") had to reverse-engineer the knobs.
  §6 inverts it — a recipe table from situation → which of the three attachment points (edge / node-runtime /
  end-to-end), owner, clock — plus owner-choice, how to pick the numbers, when NOT to declare one (a breach is
  permanent, so a too-tight SLA leaves a permanent mark on a case that finished fine), and the mistake table.
  Sections 6–9 renumbered to 7–10.
- **Worked examples:** `backend/docs/methodology/worked-examples/` — `ach_exposure/` is the standing cohort
  regression fixture (3 segment BPMNs, trigger + cohort-close schemas, samples, `ONBOARDING.md`).
- **MCP stub servers:** `mcp_stub/servers/` (wire/dine reference + 3 ACH per-segment servers); compose at
  `mcp_stub/deploy/docker-compose.yml`.
- **Mock Pega orchestrator:** `pega_stub/` (alias `pega-stub:9095`). Scenarios `credit_approve` /
  `debit_reject` / `route_uw` (immediate) + **`late_closeout`** (delays Segment C ~25s to breach an SLA).
- **Browser e2e:** `e2e/` (Playwright) + `tools/e2e.sh` (deterministic CI gate) and `tools/e2e-copilot.sh`
  (copilot lifecycle, non-blocking). Fast headless smoke: `backend/tests/smoke/` + `tools/smoke.sh`.
- **Helm:** `deploy/helm/amendia/` (umbrella chart **0.2.0** + gke/eks/aks/onprem overlays).

## Repo shape

`backend/services/{agent-runtime, ingestor, process-registry, platform/{identity, config-forge-service,
notification-service, glea-service}}` · `libs/{amendia_auth, amendia_bpmn, amendia_common,
amendia_contracts, amendia_telemetry, polyllm}` · `webui/` · `stub_trigger_generator/` · `mcp_stub/` ·
`pega_stub/` · `e2e/` · `deploy/` · `tools/` · `openspec/`.

## The loop (per decision/feature)

1. **Synthesize requirements** together (Claude + Sandeep).
2. **Capture the decision as an ADR** → Claude writes `backend/docs/adr/ADR-0XX-*.md`.
3. **Generate the CC implementation prompt** → saved to `backend/docs/_build-prompts/` **and** as a
   `claude/claude_code_prompt_*.md` project doc.
4. **Sandeep runs CC** in VS Code against the prompt.
5. **CC writes an implementation report** to `backend/docs/_build-reports/`.
6. **Claude reviews** — report first, then verifies against the actual files/diff and runtime logs over the
   bridge; reports findings; iterate.

**Working-model invariant:** Claude **writes prompts and docs, not code**. When scaffolding is needed
(worked-example assets, stubs, test harnesses), Claude authors a CC prompt rather than editing the repo.

## Prompt conventions (follow exactly)

- House style (see the ADR-058/ADR-063/ADR-064 phase prompts): a **Read-first** list, **Why**,
  phased/independently-testable deliverables, an explicit **DO NOT change** list, **acceptance/exit
  criteria**, and a working-agreement footer (scope; **CC/operator does the git add/commit/push — Claude
  and CC must not commit**).
- **Every CC prompt ends with a required "implementation report" step** (standing since 2026-08-07). CC
  writes `backend/docs/_build-reports/<prompt_slug>_report.md`, **uncommitted**, covering: (1) outcome
  one-liner; (2) changes by file/area; (3) decisions & deviations; (4) what was deliberately left as-is;
  (5) verification — exact commands run and results; (6) follow-ups / questions for the reviewer. It is a
  cover sheet, not a narration of every edit — Claude still verifies independently.
- **Large features split into sub-phases, backend-before-frontend**, so the UI always has live endpoints
  (ADR-063: P1 runtime → P2 close ingress → P3A GLEA read-model → P3B webui). Verify each phase against
  the code before writing the next.
- **Debug/fix prompts must make CC confirm the root cause empirically before patching, and bisect rather
  than assume.** Lesson from the wire-screen hunt: Claude's initial hypothesis was wrong on specifics;
  CC's live repro + `git bisect` corrected it. Reward "the premise is unsupported, here's the evidence".
- **A guard implemented by CC is not live until its service image is rebuilt.** CC's edits are
  uncommitted; running compose images predate them. Always separate "validated by tests" from "active in
  the running stack" when reviewing.

## Platform invariants

- **Domain neutrality (ADR-047/049/059):** no `exception`/`wire`/`payment` terms in platform code, wire
  contracts, event/queue vocabulary, the trigger source, or the webui platform surface. The inbound-payload
  concept is **"trigger"**; the dev source is `stub-trigger-generator`; one `trigger_messages` store
  (`trigger_id`/`trigger_type`/`schema_version`/`source`/`payload`). Reference-domain **data** (wire/dine
  payload contents, seed packs, domain MCP servers, sample files) legitimately stays domain-named.
  `logger.exception(...)` is the Python logging API, never renamed.
- **Pack ownership (ADR-060):** capabilities & artifact schemas are owned per pack version
  (`pack_key`+`pack_version` on every row; unique `(pack_key, pack_version, id, version)`). No shared
  catalog; reads are pack-scoped. This is what makes ADR-061 pack deletion a clean cascade.
- **Cohorts are observational (ADR-063):** zero execution authority — never sequence, gate, hand off state
  or terminate a segment. Explicitly **not a saga**. `correlation_value` is the sole handle and a
  globally-unique V1 invariant; it is **distinct** from the per-instance `correlation_id` (OTel trace).
- **Cohort SLAs are observational (ADR-064):** a breach flags / warns / attributes — never aborts, forces,
  skips or synthesises. Owner ∈ {external, amendia, shared}. A breach **stands** even if the work later
  arrives (`arrived_late`).
- **Any side-effectful activity is human-gated.** The assemble HITL guard requires an `approve_actions`
  gate on a `side_effectful` capability.
- **Cohort-definition management is `role.process.owner` only** — create/inline-edit/delete, membership,
  and the DAG/SLA editor, in UI **and** backend. Seeded owner persona is **priya**.
- **Notifications are SSE only.** notification-service is the fan-out hub (bus consumer → `signal_mapper`
  **whitelist, never payload** → `hub` → `GET /stream`); the browser re-fetches authorized data over REST.
  **No email/push/webhook sender exists anywhere** (that is CB-7).

## Service/port map (host→container)

config-forge 18040→8040 · **stub-trigger-generator 18081→8081** · ingestor 18082→8082 · agent-runtime
18083→8083 · process-registry 18084→8084 · webui 18085→8085 · identity 18086→8086 · keycloak 8087→8080 ·
notification-service 18088→8088 · glea-service 18090→8090. Infra: mongo 27017, rabbit 5672/15672,
clickhouse 8123 & 9001→9000, otel 4317/4318. MCP stubs: wire/dine + ACH assess/enforce/closeout on
8075/8076/8077. pega-stub 9095.

## Dev personas & roles

Identity is **Amendia-assigned by email (ADR-026), NOT from Keycloak** (realm personas are seeded
role-less; roles JIT-materialise on first login). Seed:
`backend/services/platform/identity/app/seeding/seed.py`; all passwords `dev-password`; realm
`amendia-dev` on :8087.

- **priya** — `role.process.owner` + `role.platform.admin` + wire_repair.supervisor → **the** persona for
  Registry, pack onboarding, and every cohort-definition / membership / DAG-SLA action.
- **marcus** — payments/wire `ops_approver` (NO owner → no owner-gated controls, no Registry nav).
- **riya** — `ops_analyst`. **alex** — `platform.admin` only. **gio/lucia/matteo/elena** — rest_stan.

If an owner-gated UI looks "missing", you are signed in as a non-owner. Sign in as **priya**.
A freshly-granted role can take up to ~30s to appear (`amendia_auth` (iss,sub) resolve cache) — poll,
don't cache.

## Bridge notes

- Access is granted to the whole `Amendia` folder per session; on the bridge it mounts at
  `$HOME/mnt/Amendia`. Large `device_list_dir -r` output can exceed limits — list narrowly or grep.
- `device_bash` on the Mac **cannot delete** files; to "delete", move into a `_to_delete/` subfolder and
  tell Sandeep.
- Avoid `git status`/`diff`/commits via the bridge (stale `index.lock`); Sandeep/CC owns git.
- Re-seed a consumed reference pack:
  `docker exec deploy-process-registry-1 python3 -m app.seeding.onboard_seed`.
- Local re-run remedy for a stale runtime bundle-cache: `docker restart deploy-agent-runtime-1`.

---

# Ground truth (dated log)

## Through 2026-08-13 — cohorts and cohort SLAs

- **README correction (2026-08-07).** Root `README.md` had described a different system ("ASTRA"); replaced
  wholesale with an accurate Amendia README.
- **ADR-059 (2026-08-07)** — exception→trigger rename + single `trigger_messages` store. HITL gating
  verified healthy on both reference packs (`stan-dine`, `wire-stan`). Dine-in gotcha: an onboarding
  triage-value typo (`dne_in`) routes to `no_process` — operator data entry, not a code defect.
- **Wire "Screen" silent-hold — root-caused & resolved 2026-08-07.** Not the rename (`git bisect`
  exonerated `ed5dbd8`). The copilot mapped `Screen.party ← trigger.payment.creditor`, but `screen_party`'s
  `inputSchema` typed `party.account` as **string** while the trigger's is an **object** `{id, scheme}` →
  the real MCP server rejected the closed schema → runtime fallback `MCP_TOOL_ERROR` → a **catch-all error
  boundary** masked it as a compliance "hold".
  - **Fix 1 (runtime fail-loud):** the compiler's boundary router excludes the codeless `MCP_TOOL_ERROR`
    fallback from catch-all boundaries → `FAILURE_SINK` + loud log. Explicit `errorRef` still wins.
  - **Fix 2 (design-time guard):** `process-registry/app/validation/type_compat.py`
    (compatible/incompatible/**unknown**; unknown NEVER blocks), soft as a copilot warning and hard at
    commit (`input_map_type_incompatible`, rejects only on definite incompatible).
  - **Fix 3:** relaxed the over-strict wire MCP-stub contracts — the mapping was right, the contract wrong.
- **ADR-060 + ADR-061 (2026-08-08)** — pack-owned capabilities/schemas (shared catalog evicted; UI tabs
  moved to each pack's detail page), then owner-only `DELETE /packs/{key}[/{version}]` as a
  **force-delete, audit-first, idempotent cascade** (a `PackLifecycleOp.DELETE` is emitted to GLEA
  **before** row removal, so the audit survives). Verified live. Known minor gap (accepted): the
  version-delete endpoint 404s up front and deletes `process_packs` first, so a retry after a mid-cascade
  failure can't clean the inert orphans — the ordering is deliberate (inert orphans beat a
  loadable-but-broken pack).
- **ADR-062 (2026-08-08)** — precise diagram highlighting: a terminal instance greens **only the executed
  path** (from `actor_log`); the blanket terminal⇒done fallback in `webui/src/lib/steps.ts` is gone.
- **ADR-063 (2026-08-08, 6 CC prompts)** — Cohorts. A cohort groups the Amendia segments of one larger
  cross-system case, correlated by a business key from the trigger; other segments run in an external
  orchestrator (Pega) and are invisible.
  - **Vocabulary:** definition (`cohort_def_id`) vs instance (`cohort_instance_id`, one per
    `correlation_value`); `correlation_key` is a design-time dotpath, **per-membership**.
  - **Membership:** optional `cohort_membership {cohort_def_id, correlation_key}` on the pack manifest;
    absent → the segment runs standalone (graceful non-membership). Stamped **in place** (see CB-6).
  - **Runtime (P1):** `cohort_instances` Mongo SoR, unique index on `correlation_value`, atomic
    first-writer-wins get-or-create + idempotent `add_member`; join-on-spawn is **fail-soft**; persisted
    crash-safe `open → closing → closed`.
  - **Close (P2 + guard):** the external orchestrator's end-of-process message is recognized by the
    definition's registered close schema, folded into registry `/resolve` as a discriminated `kind`
    (`cohort_close | trigger`). Close **never terminates** a running member; the shared atomic
    `finalize_if_drained` ({CLOSING, active_member_count:0}→CLOSED) is run by both the close path and the
    last-member drain, so **exactly one** `closed` fires. Late sibling → `late_join` (attached + flagged).
    An ordering guard ensures `closing` is never emitted after `closed`.
  - **Read (P3A, GLEA):** dedicated `cohort_events` ClickHouse table (`audit_events` untouched);
    `GET /cohorts`, `/cohorts/{id}`, `/cohorts/by-correlation/{value}` with a done/running/failed rollup
    joined from member outcomes. **Observability-grade** — the agent-runtime Mongo SoR stays authoritative.
  - **UI (P3B):** Cohorts list; detail with per-member live BPMN diagrams (ADR-062 precision per member);
    instance backlink banner; New-cohort flow. External (Pega) segments are an honest **scope note, not
    drawn** — drawing them would be fabrication.
  - **Parked by design:** `late_join` members appear in `roster` (`late:true`) but are excluded from
    `member_count`/`rollup`, so `roster.length` can exceed `member_count`.
- **ADR-063 validated end-to-end 2026-08-09** via the **ACH Exposure Limit Violation** worked example —
  Pega-orchestrated 3 segments (A assess → B enforce → C closeout), case `case-93fc267702`: cohort opened,
  3 members joined, drained open→closing→closed with `closing` before `closed` (ordering guard confirmed
  live), outcome Released, 3 done / 0 failed, SoD enforced across two distinct actors, per-member ADR-062
  highlighting correct. **The ACH assets are the standing regression fixture for Cohorts.**
- **Cohort UX refinements (2026-08-09).** Instances | Definitions toggle (Instances default, persisted in
  `?tab=`); membership management **relocated** off the immutable runtime instance onto a new
  `/cohorts/definitions/:id` detail page (editing membership from an instance was a category error).
  **V1 membership edits are forward-only** — they affect future spawns; existing members are never
  re-homed (amber warning when ≥1 instance exists; deeper versioning is CB-6). Added
  `PUT /cohort/definitions/{id}` (owner-gated, `cohort_def_id` immutable) + real inline edit.
  Deliberately **not** guarding deletion while instances exist — GLEA cohort instances are self-contained.
- **ADR-064 (Proposed 2026-08-12; P1–P4 shipped; validated live 2026-08-13)** — Cohort SLAs.
  - **The primitive:** after an anchor event, expect a satisfying event within a deadline (duration +
    clock); else breach, owned by an accountable owner. One shape covers missing-trigger, missing-close,
    inter-segment-gap, segment-overrun and end-to-end.
  - **Expectation graph (DAG) on the definition:** nodes = member segments + synthetic `__start__` /
    `__close__`; edges = precedence. **AND** = all branches expected; **XOR** = exactly one, siblings
    **voided** on first arrival. Node type expected vs conditional. Two clocks per node: arrival (owner
    external) and completion (owner amendia). A conditional node is voided (not breached) by an XOR-sibling
    arrival or the cohort close — which is *why* the DAG must live in the definition.
  - **At-risk → breached** (amber before red); wall-clock & business-hours per SLA.
  - **Mechanics:** a **sibling** SLA-timer substrate, not an overload of the ADR-027 instance `Timer` —
    `cohort_sla_expectations` (SoR) + `cohort_sla_timers` + a sibling poller. **Snapshot-at-open**
    (`expectation_graph_snapshot`) is the forward-only guarantee. Fire = evaluate-and-flag;
    cancel-on-satisfy wired fail-soft into the join/close handlers; exactly-once via compare-and-set;
    crash-safe late-but-never-missed via `due_at`/`detected_at`. A satisfy/void after a breach records
    `arrived_late` and **the breach stands**.
  - **GLEA (P3):** sibling `cohort_sla_events` table (ReplacingMergeTree, idempotent by `event_id`, read
    with FINAL); `current_sla_states` + owner-attributed `sla_summary`; surfaced on `CohortDetailOut.sla`
    and list badges, degrading to empty. The global `audit` `sla_breaches` metric is **deliberately not**
    unified with cohort SLA counts.
  - **webui (P4):** tabular DAG+SLA editor on the definition **detail** page in Edit mode (not the
    New-cohort form) — `__start__`/`__close__` are edge-endpoint options, not addable nodes. The graph
    always rides the PUT, which also fixed a latent wipe. Thin SSE relay: `signal_mapper` whitelists
    `cohort_instance_id`/`sla_id`/`state`/`owner` **only** (a backend test asserts `due_at`/`ref`/
    `correlation_value` are absent).
  - **Decisions (Sandeep):** AND + XOR in V1; edits forward-only-with-warning; GLEA surfaces
    transition-derived state only (pending expectations live in the agent-runtime snapshot SoR); cohort SLA
    counts are their own surface; **no active alerting in V1** — surface-only (CB-7). Scoped out: loops,
    runtime-dynamic branching, a visual DAG canvas, outbound nudges, version-pinning, business-calendar UI.
  - **Live capstone 2026-08-13:** fresh redeploy, graph `__start__ → assess → enforce → closeout →
    __close__`, arrival SLA on the enforce→closeout edge (20s, at-risk 12s, wall, owner **external**); the
    pega stub's `late_closeout` held closeout ~25s. Cohort `coh-6d6879e29aa7` (`case-9b944527b8`): breach
    recorded, owner **external** (amendia 0, shared 0), closeout arrived late, case **closed, Released** —
    **the breach stands**. Rendered live over SSE. Cross-system accountability — *who was late* — proven
    end to end.

## 2026-08-14 → 2026-08-19 — test harness, packaging, security

- **Playwright browser e2e is now the primary e2e** (`webui/e2e/` → `e2e/`; `tools/e2e.sh`). Drives the
  real stack as a user: per-persona Keycloak login once in `global-setup`, with a **sessionStorage**
  snapshot re-injected via `addInitScript` (react-oidc keeps tokens in sessionStorage, which Playwright's
  `storageState` does not capture). Journeys: cohorts · onboarding condition-normalization banner ·
  owner-gating (priya editor / marcus read-only) · dag-sla-editor (save + server 422 + forward-only
  warning) · **hitl-arc** (every gate resolved through the Task Inbox UI to cohort Closed/Released) ·
  live-sse · instance-diagram. **Zero webui source changes and no `data-testid` hooks** — all selectors use
  existing roles/labels/text. The pytest smoke (`backend/tests/smoke/`) stays as the fast headless layer
  and both reuse the same scenario YAML.
- **ACH lifecycle correction (faithful membership).** Every side-effectful action tool is
  `approve_actions`-gated in all three segments (A's `notify_pega` handback gate was never a fabrication);
  **no manifest SoD** inside enforce (an intra-segment `distinct_actor` would exclude the single approver
  and stall B) — SoD is cross-segment via an exclusive role split: enforce → **marcus**, assess + closeout
  → **riya**; priya onboards and steps out. Every flow asserts `assertThreeMembersClosed` (members 3, done
  3, running 0, failed 0) — a 1-member stall now **fails**. The runtime **does** enforce role at claim
  (403), correcting an earlier "runtime role-agnostic" note.
- **Hybrid e2e — two commands, no flags.** `tools/e2e.sh` = the deterministic **CI gate** (19 passed,
  ~2.7m, always tears down). `tools/e2e-copilot.sh` = a separate **non-blocking** command proving the real
  copilot onboarding path (4 passed, 4.5m against a live LLM; retains everything; skips cleanly on `502
  copilot_llm_unavailable`). Two findings worth keeping:
  1. **Ordering: create the cohort definition BEFORE membership** — the registry 422s
     `PUT …/cohort-membership` with "unknown cohort definition" otherwise.
  2. **The copilot frequently infers a 4-eyes `distinct_actor` SoD inside enforce**, which a single
     approver cannot satisfy. With two process humans the SoD-correct distribution is to grant every gate
     role to **both** marcus and riya and drive gates with an SoD-aware picker.
  Also: manual-gate values are **synthesized from the copilot-inferred artifact schema** (pack-scoped
  `GET /packs/{k}/{v}/artifact-schemas/…`), never hardcoded — this is what cleared the 422s. Fresh pack
  keys per run dodge the runtime's non-evicting bundle-cache; membership needs a read-after-write poll.
- **ADR-022 revised → chart 0.2.0 (2026-08-19).** The Helm umbrella chart caught up to ADR-058 onward:
  ClickHouse datastore + glea-service as pure values entries; PVC-backed persistence for
  mongo/rabbit/clickhouse; the OTel collector moved to the **`-contrib`** image with a real ClickHouse
  exporter (traces **and** logs); `vault.method` default corrected to `csi`; webui egress opened to
  identity + glea. Verified by `helm lint` + `helm template` across bare defaults and all four overlays —
  **rendering only, no cluster, no runtime behaviour asserted**. Notable derived fact: glea has **no**
  internal token and makes **no** identity call (see CB-9).
- **Vulnerability scan + remediation (2026-08-19).** Scan: 11 Python packages carrying ~20 CVEs, 12 npm
  advisories (all dev/build tooling), bandit 0 HIGH, **no live credentials**, no dangerous sinks. Coverage
  gaps stated up front (no semgrep, no osv.dev, no image scanning, no DAST). Remediation closed:
  `langchain`/`langchain-core` floors within the caps; **defusedxml at 5 XML parse sites** + a
  billion-laughs regression; a **5 MB BPMN upload cap (413)**; `secrets.compare_digest` on the internal
  token; 5 of 12 npm advisories via non-force `npm audit fix`.
  **Still open — Sandeep's call:** **V-1** (`langgraph-checkpoint` CVE-2026-48775 / `langgraph`
  CVE-2026-28277) is **unsatisfiable under polyllm's `langchain-core<1.0` cap** — reaching checkpoint 4.x
  forces `langgraph-prebuilt>=1.0.2` which needs `langchain-core>=1.0`. The two real levers are **MongoDB
  auth** or a **LangChain 1.x migration**. The remaining 7 npm advisories need SemVer majors (vitest 4 /
  vite 8 / react-router-dom 7); vitest 4 breaks the run on a jsdom `scrollIntoView` throw.

## 2026-08-28 → 2026-09-01 — ADR-065: the side-effect gate becomes waivable

- **ADR-065 written 2026-08-28.** The platform invariant "any side-effectful capability is human-gated" becomes
  **default-on but waivable**, per binding, with a **required written justification**. Sandeep's call: a full
  `hitl: none` is permitted — some processes legitimately have no human in them.
  - **The argument for building it:** the gate was *already* removable, dishonestly. `side_effect` is not
    transmitted by MCP — it is inferred from the output ack-shape (`mcp_introspect.py:88-107`, `:321`) and then
    freely editable by the operator, the copilot's `set_side_effect` mutation, and any headless caller. The ACH
    e2e fixture does exactly this (`onboard_ach.py:171-176`). An explicit, justified, auditable waiver is
    strictly safer than an untraceable mislabel.
  - **Decided (each confirmed by Sandeep):** **`min_hitl_mode` is the capability author's non-waivable floor** —
    the mechanism by which an MCP team marks its own tool's gate un-waivable; **the copilot may never waive** (no
    `set_waiver` mutation, clamp still clamps up); **a side-effectful capability stays ineligible as a
    multi-instance host**, waiver or not (today that block is *accidental* — it falls out of the gate invariant —
    and allowing `none` would otherwise permit un-gated N-way fan-out); **warn on downgrading** an
    ack-shape-inferred `side_effectful` to `read_only`.
  - Also folded in: the `assist_capability` hole (stage 4 never side-effect-checked a human task's assist, which
    `task_runner.py:871-874` runs in `mode="execute"` *before* the interrupt) and a `human` executor at
    `hitl: none` (passes validation, raises at runtime).
- **P1 shipped + reviewed (contracts + registry).** `SideEffectWaiver{justification}` on `Binding`, ≥20 chars at
  parse time, no boolean form. Nine finding codes through stage 4, mirrored into `_check_hitl_guard`. The
  non-waivable set holds. Assist hole confirmed empirically and closed. Waiver survives
  `set_bindings → session → assemble → manifest → from-pack → copilot`. Seed packs unchanged. The seven
  human-task tests that the new `hitl_none_on_human_executor` rule broke were fixed by binding them at
  `manual`/`role.server` — the real configuration — not by relaxing the rule.
- **P1 review found one blocking hole — closed by a follow-up phase.** Waiver preservation across a copilot chat
  turn was keyed on `element_id` alone, while `set_executor` (in the closed mutation vocabulary) can rebind that
  element to a **different** capability in the same turn. A waiver written for `notify_pega` could silently
  carry onto `execute_payment` — and it **validated clean**. The letter of Part C held (no `set_waiver`
  mutation); the intent did not. Writing the fix surfaced the mirror image: a `set_hitl` **raise** on a waived
  binding was silently discarded, so asking the copilot to put a gate back did nothing.
  - **Fix (`reconcile.py::_waiver_drop_reason`):** a waiver survives only when *neither the capability nor the
    gate changed*. Capability compared on the **bare id** (version bumps don't drop); missing/unequal ⇒ drop
    (fail-safe); a strictly-stronger proposed mode is honoured and drops the waiver; every drop emits a
    decision-trace entry. Verified end to end — a rebound binding now **fails** stage 4 until re-waived.
  - **Guard against the mirror failure:** `HitlProposal.mode` defaults to `"none"` (`proposal.py:30`), so an
    unrelated turn cannot look like a gate raise and erode waivers turn by turn. The preserve test fires a
    `set_hitl` at a *different* element and asserts survival.
- **Known boundary, for P4.** The guarantee is **registry-emission-side, not a signature**: nothing binds the
  justification text to the capability it justifies, so a hand-edited manifest could still carry a mismatched
  waiver. Planned fix: stamp `waived_capability_id` into the waiver object alongside `waived_by`/`waived_at`, so
  stage 4 re-verifies the bond on every validate. The waiver is an object precisely to allow this without a wire
  break.
- **P2 prompt written (runtime enforcement).** The runtime has never enforced this invariant —
  `task_runner.py:410-441` dispatches on the declared `hitl_mode` and the only fail-closed check keys on
  `deep_agent`. P2 threads the waiver onto `NodeContext`, adds the fail-closed check on both the capability and
  human-assist paths, propagates through `call_activity._scope_ctx`, and adds the compiler MI rule. Safety
  property that makes it cheap: **no existing pack can trip it** — before P1 an ungated side-effect could not be
  activated. Critical requirement carried from the wire-screen hunt: `side_effect_ungated` must be excluded from
  **catch-all error-boundary** routing, or it resurfaces as a fake business "hold".
- **P2 shipped (runtime).** Waiver threaded onto `NodeContext` (`bundle.py`), fail-closed check on the
  capability path and — separately — the human-**assist** path (human executors route to `_run_manual` *before*
  the hitl dispatch, so one check can't cover both), propagation through `call_activity._scope_ctx`, and the
  compiler MI refusal. **Deliverable 4 came out better than the prompt asked:** `side_effect_ungated` is
  *structurally* unmaskable — only `CapabilityBusinessError` ever becomes a boundary entry, so a
  `NodeExecutionError` propagates to a hard `_fail` and never reaches the boundary router. Nothing needed
  extending; CC reused the exception class and touched the router zero times.
- **Assist-ordering correction (ADR Part G amended 2026-09-01).** Review of P2 found the assist rule keyed on the
  HITL rank ladder, and `_HITL_RANK` scores `manual` and `approve_actions` **equally (2)** — so a human task at
  `manual`, the normal mode, skipped the check and ran a side-effectful assist un-gated. **The ladder encodes how
  much authorization a task carries, not ordering**; on the assist path the effect always precedes the
  `interrupt()`, so no rank buys anything. Corrected in all three places: a side-effectful assist is un-gated by
  construction and **always** needs a waiver. Survey confirmed nothing existing was newly rejected (the only
  assist anywhere is `cap.payment.draft_rfi`, `read_only`).
- **P3 shipped (webui).** Shared `WaiverAffordance` (required justification, ≥20 chars, live count, never a
  toggle) used by both the wizard's Bindings step and the copilot review — **decided 2026-09-01: the operator may
  waive from copilot review**, since forcing them into the technical wizard pushes people back toward
  mislabeling; the LLM still may never propose one. `policyByCap` splits `minFloor` (non-waivable) from `floor`,
  so waiving drops to the capability author's floor, **not** unconditionally to `none`. `gatesOf` no longer
  filters waived steps — they sort first, danger-styled, with a count banner.
- **P4a shipped (provenance + bond).** `waived_by` / `waived_at` / `waived_capability_id`, **server-stamped at
  `set_bindings`**, never client-asserted (client-sent values are ignored and overwritten — there is a test that
  sends `waived_by="attacker"`). Stage 4 verifies the bond (`side_effect_waiver_capability_mismatch`); absent
  provenance is a warning, never an error. **CC correctly declined the instruction to mirror the bond check in
  `_check_hitl_guard`** — a hand-edited manifest never passes through onboarding, and assemble runs the full
  validator anyway, so the mirror would be dead code contradicting "ignore client provenance."
- **P4b shipped (audit + fixtures), closing the ADR.** The P4a preserve gap closed (preserve author/timestamp
  only when justification **and** bond match — a same-text/new-capability re-send was crediting the prior author
  with a bond the server had just re-derived to match, making the mismatch check unfalsifiable). Audit: the
  publish `PackLifecycleEvent` carries `waivers`, fanned out by GLEA to one `pack_waiver` row each, so the
  auditor query is `kind = 'pack_waiver'` — no new column, no new channel. **Well-evidenced refutation on the ACH
  fixture:** `ach-lifecycle.spec.ts:116-131` asserts every handback is gated at `approve_actions`, so an *honest*
  fixture carries **no waiver** — the fix was to the *derivation* (gating-derived → nature-derived
  `suggested_side_effect`), and the waiver is exercised by the new Playwright journey's own pack instead.
- **THE STANDING GAP: nothing in ADR-065 has been verified on a running stack.** Every phase was green in tests
  and carried the same "not live until `docker compose build`" caveat; `tools/e2e.sh` needs a live compose stack
  and could not run. Before this can be called done: rebuild `process-registry`, `agent-runtime`, `glea-service`
  and webui, **restart** (the runtime's bundle cache is non-evicting), then waive a step as **priya**, watch it
  run un-gated, and find it in the audit store. The ADR stays **Proposed** until that pass.
- **Docs updated 2026-09-01:** the MCP implementor guideline gained **§4b** (`min_hitl_mode` as the capability
  author's non-waivable floor — new guidance: the tool's builder decides whether a process owner may ever run it
  unattended), and the trust/accountability business view gained a dated update restating the gating claim
  honestly (*"a person approves every real-world action — unless a named owner recorded, in advance and on the
  record, why this one does not need it"*).

## Open decisions on the table (2026-08-28)

1. **Amendia as data processor (PII) — needs a new ADR number (065 is taken by the gate waiver; use 066+).** `backend/docs/engineering/amendia_pii_processor_gap_analysis.md`
   (2026-08-18) is explicitly *input to ADR-065* and is the largest open item. 28 findings (9 Critical,
   11 High). Headline: **nothing in the codebase field-encrypts, masks, tokenizes, redacts or classifies
   customer data** — verified by exhaustive search, not assumed. Worst two: **G-19** — every `llm`-kind
   capability serialises the entire trigger envelope + all upstream artifacts into a prompt and sends it to
   AWS Bedrock unredacted, on a path explicitly excluded from the platform's own egress blocking; and a
   confirmed **PII leak path into the ~7-year ClickHouse audit retention**. Open sub-decisions: D1 — does
   Amendia implement the Decrypt service or call a sibling? — and the Gateway boundary. The one genuine
   data-minimization control that exists is the notification-service SSE allow-list.
2. **CB-9 — glea-service has no authentication layer at all** (verified by reading the source, 2026-08-19):
   no `amendia_auth` dependency, no principal in any `Depends`, no internal token. It is the only service
   without the ADR-012 baseline, and it fronts `audit_events.payload` — the entire raw event JSON under a
   ~7-year TTL — published on host 18090 and proxied by the webui nginx. **Severity high; a go-live blocker
   against real customer data.** Options: (a) mount `amendia_auth` with a baseline principal + read role
   (the consistent answer), or (b) declare glea internal-only and enforce that at the network layer.
3. **V-1 caps decision** (above): MongoDB auth vs the LangChain 1.x migration.
4. **CB-6** — cohort membership stamped in place vs version-gated (default: keep in place).
5. **CB-7** — SLA alerting: a new owner-routed consumer of `agent_runtime.cohort_sla.v1`; net-new because
   the platform has no outbound channel. Deferred 2026-08-12 (observe first); likely its own small ADR.
6. **CB-8** — an agent-runtime snapshot endpoint for pending expectations + countdowns; friendlier duration
   entry; a visual DAG canvas.
7. **CB-5** — webui `npm run gen:api` full sync (operational; needs the stack up).

## Housekeeping / caveats

- `backend/docs/amendia_project_brief.md` is **stale**: it still describes Amendia as a
  *payment-exception-handling platform* with an `exception_id`/`exception_raised` vocabulary and a
  `stub_exception_generator`. ADR-047/049/059 made the platform domain-neutral (trigger vocabulary,
  `stub_trigger_generator`) and ADR-063/064 added cohorts. Do not quote the brief as current; rewrite it
  when there is a natural moment.
- Branch is `feat/cohort-imp`; recent commits cover cohorts, Playwright tests, and the revised Helm charts.
  The working tree is routinely dirty — **Sandeep/CC owns git**.
