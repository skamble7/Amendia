# Claude Code prompt — vulnerability remediation: LangGraph checkpoint chain, LangChain floors, XML hardening

Remediation for the 2026-08-19 scan (`backend/docs/known-issues/vulnerability-scan-2026-08-19.md`). Four
independently testable phases, ordered by real risk. **Phase 1 is the only urgent one** — the rest are
hygiene. Dependency floors + four small code fixes; **no feature work, no architectural change.**

Two things I found while scoping this that change the shape of the work — read them before starting:

- **`langgraph-checkpoint` is transitive.** It is pulled by `langgraph-checkpoint-mongodb` (pinned 0.2.2) and
  `langgraph`. You cannot bump it directly; you bump its parent, and only if a release exists that requires
  the fixed version. Phase 1 is therefore an **investigation first, a bump second** — and a legitimate
  outcome is "no compatible release exists, here is the evidence, stopping."
- **`libs/polyllm` deliberately caps the LangChain family** (`langchain>=0.2,<0.4`,
  `langchain-openai>=0.1,<0.3`, `langchain-anthropic>=0.1,<0.3`, `langchain-aws>=0.1,<0.3`). Several CVE
  fixes land in 1.x, *above those caps*. **Do not relax a cap.** Fix what fits inside the existing ranges and
  report precisely what remains unfixable and what crossing the boundary would cost — that is Sandeep's call,
  not yours.

## Why

The scan found 11 Python packages carrying ~20 CVEs, 12 npm advisories (all dev tooling), and 0 HIGH bandit
findings. Almost all of it is routine. One item is not:

**`langgraph-checkpoint==3.0.1` — CVE-2026-48775 (`JsonPlusSerializer` reconstructs Python objects from JSON
checkpoint payloads, fix 4.1.1) and CVE-2026-27794 (RCE via `BaseCache`, fix 4.0.0); plus `langgraph==1.0.1`
CVE-2026-28277, the same class over msgpack (fix 1.0.10).** Both advisories are gated on *"an attacker who
can modify checkpoint bytes at rest in the backing store."* In Amendia that store is MongoDB, `lg_checkpoints`
is written at every graph-node boundary and doubles as the audit trail (ADR-011), and **MongoDB runs with no
credentials** in compose *and* in the Helm in-cluster deployment. The precondition the advisory treats as the
hard part is, here, "can reach Mongo."

Authenticating MongoDB is the other half of that fix and is **deliberately out of scope** — it touches every
connection string, the Helm chart and Vault, and needs its own decision. Claude will write that up separately.

The remaining phases: LangChain floors within the existing caps, a tested-real XML entity-expansion DoS, and
dev-tooling npm advisories.

## Read first

- `backend/docs/known-issues/vulnerability-scan-2026-08-19.md` — the full report. §A/V-1 for the checkpoint
  chain, §C-2 for the XML testing (note which attacks were **blocked** vs **confirmed**), §E for priority.
- `backend/services/agent-runtime/pyproject.toml` — lines 26–28: `langgraph>=0.2.0`,
  `langgraph-checkpoint-mongodb>=0.1.0`, `langchain-core>=0.3.0`. Note there is **no direct
  `langgraph-checkpoint` dependency** — confirm this before planning Phase 1.
- `backend/services/agent-runtime/app/engine/engine.py:30,140` — `from langgraph.checkpoint.mongodb import
  MongoDBSaver` and its construction. This is the only checkpointer call site; it is what a major bump risks.
- `libs/polyllm/pyproject.toml:15-20` — the capped LangChain extras, shared by agent-runtime **and**
  process-registry. Changing polyllm changes both.
- `libs/amendia_bpmn/amendia_bpmn/{parser.py:153,182 · semantics.py:162 · dmn.py:101}` and
  `backend/services/process-registry/app/services/onboarding.py:1310` — the five `ET.fromstring` call sites.
- `backend/services/process-registry/app/routers/packs.py:77` and `.../routers/onboarding.py:44-48,185` — the
  two BPMN upload routes and their `role.process.owner` guards.
- `libs/amendia_auth/amendia_auth/dependencies.py:105-113` and `settings.py:37` — the internal-token compare
  and its empty default (the default is correct — do not change it).
- `webui/package.json` + the `npm audit` output.

## Deliverables

### Phase 1 — LangGraph checkpoint chain (the urgent one)

1. **Investigate before changing anything.** Determine whether a `langgraph-checkpoint-mongodb` release
   exists that depends on `langgraph-checkpoint >= 4.1.1`, and what `langgraph` version it requires. Record
   the resolved dependency chain in the report. **If no such release exists, STOP** — do not pin
   `langgraph-checkpoint` directly to force it past its parent's constraint, and do not vendor a patch.
   Report the finding and the options instead; a blocked Phase 1 is a valid outcome and Phase 2–4 still stand.
2. If a compatible release does exist: raise the floors in `backend/services/agent-runtime/pyproject.toml`
   (`langgraph-checkpoint-mongodb`, `langgraph`) so the resolved `langgraph-checkpoint` is **≥ 4.1.1** and
   `langgraph` is **≥ 1.0.10**, and relock. Note this crosses a `langgraph-checkpoint` **major** (3 → 4);
   check the changelog for `JsonPlusSerializer` / serde and `MongoDBSaver` API changes and call out anything
   that touches `engine.py:140`.
3. **Verify the checkpoint path empirically, not just by test suite.** The checkpoint trail is the
   resumability mechanism *and* the audit record, so a green unit run is not sufficient evidence. Demonstrate,
   with the stack up: an instance runs to a HITL gate, the checkpoint persists, and the instance **resumes
   from that checkpoint** after an agent-runtime restart (the engine's `running`-instance recovery path).
   `tools/demo_wire_repair.sh` is the existing end-to-end driver. Show the commands and the observed outcome.
4. Do **not** enable any LangGraph cache backend / `CachePolicy` as part of this (CVE-2026-27794's affected
   surface). If one is already in use, say so in the report — I do not believe it is.

### Phase 2 — LangChain floors, inside the existing caps

5. Raise `langchain-core` to **≥ 0.3.85** everywhere it is declared (agent-runtime; anywhere else it appears).
   This is inside the current range and closes CVE-2026-44843 and CVE-2026-40087. Relock every affected
   project so **process-registry stops sitting 10 patch versions behind agent-runtime** — today they resolve
   0.3.76 and 0.3.86 respectively, which is its own maintenance risk.
6. Raise `langchain` to **≥ 0.3.30** within polyllm's `<0.4` cap (closes CVE-2026-45134).
7. **Report, do not fix, what the caps block.** `langchain-openai` (CVE-2026-41488, fix 1.1.14),
   `langchain-anthropic` (CVE-2026-55443, fix 1.4.6), `langchain-text-splitters` (CVE-2026-41481, fix 1.1.2)
   and the rest of CVE-2026-55443 all need 1.x, above polyllm's caps. For each: state the fixed version, why
   the cap blocks it, and your assessment of whether Amendia actually calls the affected code path (the SSRF
   ones are in image-token-counting and URL-fetching helpers — say whether anything reaches them). Do **not**
   relax `<0.3` / `<0.4`.
8. Note the `aio-pika` split (9.6.2 and 10.0.1 resolve across the workspace) in the report. Do not unify it
   here unless it falls out for free — flag it as a follow-up.

### Phase 3 — XML hardening + two small fixes

9. Add `defusedxml` and swap `xml.etree.ElementTree` for `defusedxml.ElementTree` at the **five** parse sites
   listed in Read-first. Keep the existing exception handling working — `defusedxml` raises its own
   `EntitiesForbidden`/`DTDForbidden` types, so the `except ET.ParseError` / `except Exception` blocks must
   still produce the same caller-visible validation errors. Add a regression test with a billion-laughs
   payload asserting it is **rejected** rather than expanded.
   *Confirmed by testing, so you can skip re-deriving it:* XXE file-read and SSRF are already **blocked** by
   CPython's ElementTree (both raise `ParseError: undefined entity`). Only **entity expansion** is real — a
   5-level payload expanded to 300 000 chars in 0.02 s, and depth is attacker-chosen.
10. Add a **request body size limit** on the two BPMN upload routes (`PUT /packs/{key}/{version}/bpmn`,
    `PUT /onboarding/{session_id}/bpmn`). There is currently **no body-size cap anywhere** in the codebase or
    in `webui/nginx.conf`. Pick a defensible ceiling for a BPMN document, make it configurable via the
    service's existing settings pattern, and return a clean 413. Do not add a global middleware that changes
    behaviour on unrelated routes.
11. `libs/amendia_auth/amendia_auth/dependencies.py:111` — replace the `==` on the shared internal token with
    `secrets.compare_digest`. Preserve the existing short-circuit semantics exactly: an empty configured token
    must still mean "internal auth disabled" (fail closed), never "matches empty".

### Phase 4 — webui dev tooling

12. `npm audit fix` in `webui` for the 12 advisories (1 critical `vitest`/`@vitest/mocker`, plus `vite`,
    `postcss`, `js-yaml` via `@redocly/openapi-core`, `nanoid`, `brace-expansion`). All report
    `fixAvailable`. These are **build/test-time only** — none ships in the nginx bundle — so the bar is "does
    the build and the test suite still pass", not a runtime proof.
13. If any fix requires `--force` / a breaking major (vitest is the likely one), do that bump deliberately and
    verify `npm run build` + `vitest` are green; if it cascades into config changes beyond a version bump,
    stop and report rather than rewriting test config. `e2e` audits clean — leave it alone.

## Do not

- **Do not touch MongoDB authentication, connection strings, compose or the Helm chart.** That is the other
  half of V-1 and is deliberately a separate decision.
- Do not relax polyllm's LangChain version caps, and do not pin `langgraph-checkpoint` directly past its
  parent's constraint.
- Do not change application logic beyond what a bump strictly requires. If a bump forces a call-site change,
  make the minimal one and call it out; if it forces a design change, stop and report.
- Do not "fix" the 15 bandit B608 SQL-injection findings in `glea-service/app/clickhouse/reader.py` — I traced
  every call site and they are **false positives** (values bind via ClickHouse server-side parameters; every
  `where` fragment is a hardcoded literal). Rewriting them would add risk for nothing.
- Do not add XXE-specific defences beyond `defusedxml`, and do not claim XXE was exploitable — it was not.
- Do not write or edit ADRs. Do not change `internal_token`'s empty default.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- Per-service `pytest` green with no reduction in collected tests: agent-runtime, process-registry,
  glea-service, notification-service, identity, ingestor. State before/after counts for any suite you touched.
- `webui`: `tsc`, `npm run build` and `vitest` green.
- Phase 1: either (a) the resolved lock shows `langgraph-checkpoint >= 4.1.1` and `langgraph >= 1.0.10`
  **and** the restart-and-resume demonstration is shown with real commands and output, or (b) a documented
  STOP with the dependency-chain evidence.
- Phase 3: a test proving a billion-laughs BPMN payload is rejected; an oversized upload returns 413; the
  internal-token path still fails closed with an empty configured token (assert this).
- Re-run the dependency check and show the delta: which of the ~20 CVEs are now closed, which remain, and why
  each remaining one remains. **Do not report "all clear"** — several will legitimately still be open behind
  the polyllm caps, and saying so plainly is the correct outcome.
- **Reviewer note:** separate "green in tests" from "live in the running stack" — per the standing convention,
  a dependency bump is not live until `docker compose build <service>` has rebuilt the image. Say which is which.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_vuln_remediation_report.md` (uncommitted):
(1) outcome one-liner; (2) changes by file and phase, with before → after versions in a table; (3) decisions &
deviations — especially the Phase 1 dependency-chain finding, anything the polyllm caps blocked, and any
call-site change a bump forced; (4) what you deliberately left alone (Mongo auth, the B608 false positives,
the caps, ADRs); (5) verification — exact commands and results per suite, plus the Phase 1 restart-and-resume
evidence; (6) the CVE delta table: closed / still open / why. One to two screens.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Dependency floors + the four small code fixes only;
no feature work, no compose/Helm/ADR changes. Where this prompt's assessment conflicts with what you observe
in the code or the resolver, **the evidence wins** — say so in the report rather than bending the work to
match the prompt. A blocked Phase 1 with good evidence is a better outcome than a forced upgrade.
