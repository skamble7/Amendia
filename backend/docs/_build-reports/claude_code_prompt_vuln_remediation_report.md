# Vulnerability remediation — 2026-08-19 scan

**Outcome.** LangChain floors raised inside the caps, five XML parse sites hardened with defusedxml, a BPMN
upload size cap (413), and a constant-time internal-token compare — all suites green. **Phase 1 (the urgent V-1
checkpoint bump) is a documented STOP**: the fix is unsatisfiable under polyllm's `langchain-core<1.0` cap, so it
is Sandeep's caps decision (or MongoDB auth), not this task's. No Mongo/compose/Helm/ADR changes; no git writes.

## 1. Changes by file & phase (before → after)

| Phase | File | Change | Before → After |
|---|---|---|---|
| 1 (STOP) | `agent-runtime/pyproject.toml` | reverted exploratory bump to baseline + comment | `langgraph>=0.2.0`, `langgraph-checkpoint-mongodb>=0.1.0` (unchanged) |
| 2 | `agent-runtime/pyproject.toml` | `langchain-core` floor | `>=0.3.0` → **`>=0.3.85`** |
| 2 | `libs/polyllm/pyproject.toml` | `langchain` floor + shared `langchain-core` floor | `langchain>=0.2,<0.4` → **`>=0.3.30,<0.4`**; added **`langchain-core>=0.3.85`** |
| 2 | 3 × `uv.lock` relock | resolved versions | `langchain` 0.3.28→**0.3.30**; `langchain-core` 0.3.76/0.3.86→**0.3.86** (drift closed); langgraph/checkpoint **unchanged** 1.0.1/3.0.1 |
| 3a | `libs/amendia_bpmn/pyproject.toml`, `process-registry/pyproject.toml` | add dep | `defusedxml>=0.7` (resolves **0.7.1**) |
| 3a | `amendia_bpmn/{parser,semantics,dmn}.py`, `process-registry/…/onboarding.py` | swap `xml.etree` → `defusedxml.ElementTree` at the 5 `fromstring` sites; broaden 3 `except ET.ParseError` → `except (ET.ParseError, DefusedXmlException)` | hardened |
| 3a | `libs/amendia_bpmn/tests/test_xxe_hardening.py` | new billion-laughs regression (4 tests) | +4 |
| 3b | `process-registry/app/config.py` | new setting | `MAX_BPMN_UPLOAD_BYTES: int = 5_242_880` (env `REGISTRY_MAX_BPMN_UPLOAD_BYTES`) |
| 3b | `process-registry/app/routers/{packs,onboarding}.py` | 413 on the two BPMN upload routes | added (packs: `len(body)`; onboarding: `len(req.bpmn_xml.encode())`) |
| 3b | `process-registry/tests/test_upload_size_limit.py` | new (2 tests) | +2 |
| 3c | `libs/amendia_auth/amendia_auth/dependencies.py` | `secrets.compare_digest` at **:111** (`principal_or_internal`) **and :124** (`require_internal`); `import secrets` | `==`/`!=` → constant-time |
| 3c | `libs/amendia_auth/tests/test_dependencies.py` | new fail-closed tests (2) | +2 |
| 4 | `webui/package-lock.json` | `npm audit fix` (non-force, transitive-only) | 12 → **7** advisories; no declared-major bump |

## 2. Decisions & deviations

- **Phase 1 dependency-chain finding (the headline).** Investigated against live PyPI + `uv lock`. The checkpoint
  fix is **unsatisfiable** under polyllm's `langchain-core<1.0` cap, which the prompt forbids relaxing:

  | Package | Constraint that matters | Effect |
  |---|---|---|
  | `langgraph-checkpoint` 4.1.1/4.2.0 | `langchain-core>=0.2.38` | fine on its own |
  | `langgraph-checkpoint-mongodb` 0.4.0 | `langgraph-checkpoint>=3.0.0` (open) | permits checkpoint 4.x — NOT the blocker |
  | `langgraph>=1.0.6` (first with `checkpoint<5.0.0`) | pulls `langgraph-prebuilt>=1.0.2` | required to reach checkpoint 4.x |
  | **`langgraph-prebuilt>=1.0.2`** | **`langchain-core>=1.0.0`** | **crosses the cap** |

  So reaching `langgraph-checkpoint>=4.1.1` forces `langchain-core>=1.0.0` (via `langgraph-prebuilt`), which
  collides with polyllm's `<1.0`; `langgraph>=1.0.10` (CVE-2026-28277) is blocked identically. `uv lock` result:
  *"your project's requirements are unsatisfiable."* **Levers, both out of scope:** (a) MongoDB auth (the
  deliberately-separate half of V-1); (b) cross the polyllm caps to LangChain 1.x (cascades the whole family to
  1.x — Sandeep's call). `engine.py:140` untouched; no restart-and-resume demo (there is no bump to prove).
  **CVE-2026-27794 (BaseCache RCE) is not applicable** — no LangGraph cache backend / `CachePolicy` is configured
  (verified: no `CachePolicy`/`BaseCache` usage anywhere in agent-runtime).

- **What the polyllm caps block (Phase 2, report-only — NOT fixed).** All need 1.x, above the `<0.3`/`<0.4` caps:
  `langchain-openai` CVE-2026-41488 (fix 1.1.14), `langchain-anthropic` CVE-2026-55443 (fix 1.4.6),
  `langchain-text-splitters` CVE-2026-41481 (fix 1.1.2), `langgraph-sdk` CVE-2026-48776 (fix 0.3.15).
  **Reachability (grepped):** polyllm only constructs `ChatOpenAI`/`ChatAnthropic`/`ChatBedrock` and calls
  `invoke`/`ainvoke`; nothing in `backend`/`libs` calls `get_num_tokens_from_messages`, uses `image_url`,
  `_url_to_size`, `HTMLHeaderTextSplitter.split_text_from_url`, or a `langgraph-sdk` client — so the SSRF/path CVEs
  are **not reached**. Follow-up (not fixed): the `aio-pika` 9.6.2/10.0.1 split persists across the workspace.

- **No call-site change was forced.** langgraph/checkpoint stayed at 1.0.1/3.0.1; the LangChain floors are
  patch/minor within range. The only code edits are the four small fixes.

- **Phase 3c scope.** Fixed `secrets.compare_digest` at the cited **:111** and also at **:124** (`require_internal`
  — identical `!=` on the same secret, same file); leaving one un-fixed would be inconsistent. Both preserve the
  fail-closed short-circuit (empty configured token ⇒ reject). `internal_token`'s empty default is unchanged.

- **Phase 4 — stopped at the safe subset (as instructed).** `npm audit fix` (non-force) cleared **5 of 12**
  (12 → 7), lock-only, no declared-major bump; **build + vitest stay green**. The remaining **7** all require
  `npm audit fix --force` with SemVer-**majors** — `vitest 2→4`, `vite 5→8`, `react-router-dom 6→7`. I applied
  `--force` to test it: it reaches **0 vulnerabilities and the build passes**, but **vitest 4 throws an uncaught
  jsdom `scrollIntoView` exception** (`OnboardingWizard.tsx:285`) that fails the run — clearing it needs a
  one-line polyfill in `vitest.setup.ts` (a test-config change). Per the plan's guardrail I **reverted the
  `--force`** and left the safe subset. **New finding beyond the scan:** two of the remaining 7 are **react-router
  runtime advisories** (open-redirect via backslash in `<Link>`/`useNavigate`; arbitrary-constructor injection in
  SSR `deserializeErrors`) — not in the scan's dev-tooling-only list. The SSR one does not apply (client-only SPA);
  the open-redirect is low and needs the react-router-dom 7 major. These + the dev-tooling majors are a deliberate
  tooling upgrade for Sandeep.

## 3. Deliberately left alone
MongoDB auth (V-1's other half); the polyllm `<0.3`/`<0.4` caps; the 15 B608 ClickHouse "SQL injection" false
positives (`reader.py` — server-side params + hardcoded `where` literals); `internal_token`'s empty default; ADRs;
compose/Helm; `cryptography` (CVE-2026-69247 not exploitable — no PKCS7 — next pass); the `webui/e2e` audit (clean).
No git writes (the only git command used was `git checkout -- webui/package.json webui/package-lock.json` to undo my
own `--force` experiment; nothing committed).

## 4. Verification

**Green in tests** (local uv venvs / vitest), per suite — before → after collected, all passing:

| Suite | Before | After | Note |
|---|---|---|---|
| `libs/amendia_bpmn` | 194 | **198** | +4 billion-laughs |
| `libs/amendia_auth` | 20 | **22** | +2 fail-closed |
| `process-registry` | 405 | **407** | +2 upload-413 |
| `agent-runtime` | 397 | **393 passed + 4 skipped** | no reduction (integration auto-skips, no stack) |
| `identity` / `notification-service` / `ingestor` / `glea-service` | — | **27 / 19 / 23 / 82** passed | amendia_auth consumers — no regression |
| `webui` | — | typecheck ✓ · build ✓ (2165 modules) · **204 tests / 29 files passed** | |

Commands: per project `uv run --extra dev pytest` (amendia_bpmn: `uv run --with pytest --with pytest-asyncio pytest`);
`cd webui && npm run build && npm test`. Phase-3 proofs: billion-laughs BPMN → `(None, [bpmn_parse_error])` in
**0.02s** (not expanded); oversized upload → **413**; internal-token **fails closed** with `internal_token==""`.

**Not yet live in the running stack (standing convention):** the Python floors (`langchain-core` 0.3.86,
`langchain` 0.3.30) and `defusedxml` are green in the resolved locks + pytest, but are **not live until
`docker compose build agent-runtime process-registry`** rebuilds the images; likewise the webui lock fix is live
only after the webui image rebuild. The four code fixes (defusedxml swap, 413, compare_digest) are effective in
tests now and ship on that same rebuild.

## 5. CVE delta — closed / still open / why

| CVE(s) | Package | Status | Why |
|---|---|---|---|
| CVE-2026-45134 | `langchain` 0.3.28→0.3.30 | **CLOSED** | within `<0.4` cap |
| CVE-2026-44843, -40087, -34070, -26013 | `langchain-core` 0.3.76/0.3.86→**0.3.86** | **CLOSED** | ≥0.3.85 floor; process-registry drift closed |
| entity-expansion DoS (C-2) | `amendia_bpmn`/registry parsers | **CLOSED** | defusedxml at 5 sites + 413 cap + regression test |
| D-1 timing side-channel | `amendia_auth` | **CLOSED** | `secrets.compare_digest` (:111 + :124) |
| 5 of 12 npm advisories | webui dev tooling | **CLOSED** | `npm audit fix` (non-force) |
| **CVE-2026-48775** (JsonPlusSerializer), **CVE-2026-28277** (msgpack) | `langgraph-checkpoint` 3.0.1 / `langgraph` 1.0.1 | **OPEN** | V-1 — fix needs `langchain-core≥1.0` (via `langgraph-prebuilt`), crosses the caps; or MongoDB auth. Sandeep's call |
| CVE-2026-27794 (BaseCache RCE) | `langgraph-checkpoint` | **OPEN but N/A** | no cache backend / `CachePolicy` configured |
| CVE-2026-41488 | `langchain-openai` 0.2.14 | **OPEN** | fix 1.1.14 above `<0.3` cap; helper not reached |
| CVE-2026-55443 | `langchain-anthropic` 0.2.4 (+`langchain`) | **OPEN** | fix 1.4.6/1.3.9 above caps; not reached |
| CVE-2026-41481 | `langchain-text-splitters` 0.3.11 | **OPEN** | fix 1.1.2 above cap; helper not reached |
| CVE-2026-48776 | `langgraph-sdk` 0.2.15 | **OPEN** | fix 0.3.15; no `langgraph-sdk` client used |
| CVE-2026-69247 | `cryptography` 49.0.0 | **OPEN but N/A** | no PKCS7; next pass |
| 7 of 12 npm advisories (incl. critical `vitest`, + `react-router` runtime) | webui | **OPEN** | need `--force` majors (vitest 4 / vite 8 / react-router-dom 7); vitest 4 breaks the test run (jsdom scrollIntoView). Deliberate tooling upgrade — deferred |

**Not "all clear":** V-1 remains open behind the caps (its real mitigation is MongoDB auth or the LangChain 1.x
migration), several LangChain-family CVEs remain behind the caps (not reached), and 7 npm advisories remain behind
the tooling-major wall. Reporting them open is the correct outcome.
