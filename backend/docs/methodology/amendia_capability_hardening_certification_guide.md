# Amendia — Capability Hardening & Certification Guide

**Status:** normative for any capability bound into a pack intended for a production deployment; **mandatory** for
every `side_effectful` capability before go-live.
**Audience:** MCP capability developers, and the reviewer/risk function that certifies a capability for
production.
**Companion documents:** `amendia_mcp_implementor_guideline.md` (the *contract* — schemas, acknowledgement,
error signalling), `amendia_process_onboarding_guide.md` (§4 side-effect→HITL coupling), `amendia_go_live_readiness.md`
(the process-level acceptance gate that consumes a capability's certification), `amendia_platform_contracts_v1.md`.

---

## 1. Why this exists — contract-compliant is not production-trustworthy

The MCP Implementor Guideline makes a tool **onboardable**: fully self-describing, closed schemas, a typed
acknowledgement, modeled business errors signalled as `isError` + `error_code`. Passing it means the onboarding
wizard can turn the tool into a capability *without repair*.

It does **not** make the tool **safe to trust with a real-world side effect.** A tool can be perfectly
contract-shaped and still double-release a payment on a retry, leak a secret in an error string, accept an
adversarial argument from an agent reading an untrusted attachment, or fail in a way that leaves the process
unable to tell whether the action happened. Those are behavioural properties the schema cannot express.

This guide defines the **hardening requirements** a capability must meet and the **certification** it must pass
before it is bound into a production pack. The bar is graded: `read_only` capabilities meet a lighter set;
`side_effectful` capabilities — the ones Amendia forces behind an `approve_actions` gate — meet the full set,
because they are the ones that move money, send outward messages, and write systems of record.

Amendia already enforces a great deal as *validated configuration* (side-effect ⇒ human authorization, four-eyes,
gateway-only-on-required-fields, pinned immutable packs). This guide covers the part the platform **cannot**
enforce for you: that the capability behind the gate does exactly, only, and reliably what it claims.

---

## 2. Hardening requirements (H-series)

### H1 · Idempotency under retry (side-effectful — the money-safety requirement)

A `side_effectful` tool **MUST** be idempotent under retry. The platform, the network, and the operator can all
cause the same call to arrive more than once (a timeout that actually succeeded, a runtime retry, a resumed
instance). "Effectively-once" is achieved by **at-least-once delivery + an idempotent receiver** — and the
receiver is *your tool*.

- The caller supplies a stable **idempotency key** for the intended action (Amendia derives a deterministic key
  per bound action — the same anchor as `action_id`). Your tool **MUST**: on first call for a key, perform the
  effect once and return the acknowledgement (with `action_id`); on any subsequent call *with the same key*,
  perform the effect **zero** additional times and return the **same** acknowledgement (`status: "performed"`,
  same `action_id`). It must never perform the effect twice for one key.
- `action_id` (Guideline §4) is the anchor: it is the server-side identity of the performed action, and it is
  what the four-eyes audit record ties the human approval to. Persist it against the idempotency key.
- If a retry arrives while the first is still in flight, resolve it deterministically (idempotency-key lock /
  upsert), not with a duplicate effect.

Idempotency that exists only in the descriptor's `idempotent: true` field but not in the implementation is worse
than none — it invites blind retry. **Prove it (§3, C2).**

### H2 · Ambiguity resolution — "did it happen?"

A side-effectful tool **MUST** provide a way to answer "did action *K* already happen?" without re-performing it
— either the idempotent re-call (H1) returning the prior ack, or a companion read-only status/query tool keyed on
the idempotency key / `action_id`. This is what lets the process recover from a timeout without either losing or
duplicating a money movement.

### H3 · Failure semantics — technical vs modeled, and never a silent partial

- A failure to *perform* the action (downstream down, timeout, crash) is a **technical error** → JSON-RPC/HTTP
  error; the task fails/retries per its idempotency policy. Under H1 that retry is safe.
- A *performed* action with a business-negative outcome (payment **rejected**, screening **hit**, **insufficient
  info**) is a **modeled business error** → `isError: true` + a stable `error_code` that equals the diagram's
  `<bpmn:error>` code (Guideline §4a). It is routed, not failed.
- **No silent partial success.** A tool must not perform half its effect and return success. If the effect is
  multi-part and not atomic downstream, either make it atomic, or make it idempotently resumable and report
  precisely what completed. Getting this wrong is how a process believes money moved when it didn't (or vice
  versa).

### H4 · Endpoint security — only Amendia may call it

The MCP endpoint is a live door to a system of record. It **MUST**:

- Authenticate its caller (mutual TLS, a bearer/OAuth token, or network isolation such that only the Amendia
  deployment can reach it) — an unauthenticated MCP endpoint that releases payments is an open relay.
- Be served over TLS at the deployment-facing endpoint.
- Carry no literal secrets in the descriptor `headers` — secret **references** only (`env:`/`file:`/`vault:`),
  resolved by the deployment (Guideline §5).
- Use **least-privilege downstream credentials** — the credential the tool uses against the real system grants
  only what that one tool needs (e.g. "release this payment," not "admin on the payments rail").

### H5 · Input safety & injection resistance

The tool **MUST NOT** trust its arguments. It validates against its own closed `inputSchema` and rejects
anything else. This matters doubly for a tool a **`deep_agent`** may call: that agent reads *untrusted* content
(exception narratives, counterparty messages, attachments) and could be induced to pass adversarial arguments.
The tool is the last line — it must be safe against malformed, oversized, or hostile input, and must never
interpolate an argument into a downstream command/query without sanitisation (no injection into SQL, shell,
downstream API paths). The agent's tool-whitelist + egress controls are the outer mitigation; a hardened tool is
the inner one.

### H6 · Honest side-effect boundary

- A `read_only` tool performs **no** external write, ever — no "read that also logs a decision," no lazy
  create-on-read. If it writes, it is `side_effectful` and must be gated. A hidden write in a "read" tool
  bypasses the entire control model.
- A `side_effectful` tool performs **exactly one** well-defined effect. Bundling two irreversible effects behind
  one approval means the human authorized less than what happened.

### H7 · No sensitive-data leakage

Outputs and **error messages** must not leak secrets, credentials, full PANs, or unnecessary PII. Error detail is
often overlooked — a stack trace or downstream error echoed verbatim can expose connection strings or tokens.
Return the modeled `error_code` + a sanitised `detail`, not the raw downstream failure.

### H8 · Bounded behaviour

Declare and honour a **timeout budget** (the runtime treats a hung tool as a technical failure); apply **rate
limits / concurrency bounds** appropriate to the downstream; bound response size. A tool that can hang or flood
the downstream is a production incident waiting for load.

### H9 · Auditability at the tool

Every side-effectful call emits, and the acknowledgement returns, enough to reconstruct it: `action_id`, the
idempotency key/correlation, a timestamp (`performed_at`), and the salient parameters of what was done. This is
what makes the platform's immutable decision record *complete* — the human approval ties to the `action_id`, and
the `action_id` ties to the real-world effect.

### H10 · Version & contract stability

Per Guideline §6: input/output shape, tool name, field names, and `error_code`s are the tool's contract. Changing
any is a new version requiring re-onboarding; a live pack runs the pinned version. Certification is **per version**.

---

## 3. Certification suite — the tests a capability passes before go-live

Certification is a **repeatable test suite run against the deployment-facing server** (or a faithful staging
mirror), producing a **certification record** (§4). Graded by `side_effect`:

**Both `read_only` and `side_effectful`:**
- **C0 · Contract conformance.** The Guideline §7 self-check, automated: `inputSchema`/`outputSchema` present,
  object roots, closed shapes, no external `$ref`, stable snake_case, decision-driving fields `required`.
- **C1 · Error-mapping correctness.** Each modeled business outcome returns `isError: true` + the exact
  `error_code` the target pack's error boundary references; each technical failure returns a transport/JSON-RPC
  error — asserted against the *real* server, and cross-checked that every `error_code` the tool can emit has a
  matching `<bpmn:error>` in the pack (ties to go-live).
- **C5 · Input-safety / fuzz.** Malformed, oversized, and adversarial inputs are rejected safely (no crash, no
  injection, no leak) — with emphasis on any tool a `deep_agent` may call (H5).
- **C7 · Data-leak scan.** Outputs and error paths asserted free of secrets/credentials/unmasked sensitive data
  (H7).

**Additionally required for `side_effectful`:**
- **C2 · Idempotency proof.** Call twice with the **same** idempotency key → the effect occurs **once**, both
  calls return the **same** `action_id`/ack. Assert against the real downstream's effect count, not just the tool
  response (H1). *This is the single most important test in the suite.*
- **C3 · Failure-injection / recovery.** Inject a timeout/partial-failure after the effect began → the process's
  retry (same key) does **not** double the effect, and the "did it happen?" query (H2) returns the truth. No
  silent partial (H3).
- **C4 · Endpoint-security probe.** An unauthenticated/unauthorized caller is rejected; TLS enforced; no literal
  secret reachable via the descriptor (H4).
- **C8 · Load/latency smoke.** Sustained representative load stays within the timeout budget and rate limits (H8).

A capability that clears its graded suite is **certified for that version**. A `side_effectful` capability that
has not passed **C2, C3, C4** is **not** eligible to be bound into a go-live pack — this is the hard line.

---

## 4. The certification gate & record

- **Who certifies.** The capability developer runs the suite; for a `side_effectful` capability, a **second
  party** (reviewer/risk) confirms the result and signs off — mirroring four-eyes at the capability level. The
  same person who built it should not be its sole certifier.
- **The record.** A **Capability Certification Record** per `capability_id@version`: the version, the graded
  suite run + results, the downstream/environment it was certified against, known limitations, and the
  sign-off(s). Store it where the go-live gate can read it (alongside the pack's go-live package).
- **Consumed by go-live.** The process-level go-live gate (`amendia_go_live_readiness.md`) checks that **every
  `side_effectful` capability the pack binds has a current, passing certification record for the pinned version**.
  No certification → no go-live. A new capability version → re-certify before the pack that pins it goes live.

---

## 5. Certification checklist (extends the Guideline §7 pre-onboarding self-check)

For each capability, before it is bound into a production pack:

- [ ] **Contract (C0):** Guideline §7 clean — schemas, closed shapes, no external `$ref`, decision fields required.
- [ ] **Error mapping (C1):** every modeled outcome → `isError`+correct `error_code`; technical failures →
      transport error; every emittable `error_code` has a matching boundary in the target pack.
- [ ] **Input safety (C5):** rejects malformed/adversarial input safely; no injection into downstreams; extra
      scrutiny if a `deep_agent` calls it.
- [ ] **No leakage (C7):** outputs and error messages carry no secrets/credentials/unmasked PII.
- [ ] **Honest boundary (H6):** `read_only` truly performs no write; `side_effectful` performs exactly one effect.

Additionally, for every `side_effectful` capability:

- [ ] **Idempotency proven (C2):** same key → one effect, same `action_id` — asserted on the real downstream.
- [ ] **Failure recovery (C3):** retry-after-timeout never doubles the effect; "did it happen?" (H2) is
      answerable; no silent partial.
- [ ] **Endpoint secured (C4):** authenticated caller only, TLS, least-privilege downstream credential, no
      literal secrets.
- [ ] **Bounded (H8/C8):** timeout budget, rate limits, size bounds honoured under representative load.
- [ ] **Auditable (H9):** `action_id`, correlation, timestamp, and salient parameters emitted and returned.
- [ ] **Certified & signed off:** graded suite passed for this exact version; second-party sign-off recorded;
      Certification Record filed.

---

## 6. Non-goals & relationship to the MCP Implementor Guideline

- The Implementor Guideline defines the **contract** (can Amendia onboard this tool?). This guide defines
  **production trust** (may a live process rely on it to take a real action?). A capability needs both.
- This guide does not change any platform contract, schema, or validator — it is a **process discipline** the
  methodology enforces via the go-live gate, plus behavioural requirements the capability developer implements.
- It does not replace the platform's controls (approval gates, SoD, pinning); it ensures the thing *behind* the
  gate is worthy of the gate.

---

*Living document. As new downstream integration patterns and failure modes are learned, add hardening
requirements and certification tests. The rule of thumb: if a capability could cause a wrong, doubled, or
irreversible real-world effect, there is a test here that must catch it before go-live.*
