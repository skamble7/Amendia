# Claude Code Prompt — Capability pre-select recall: stemming + containment + ranked best-guess (never a cold "Select…")

The Bindings step auto-selects a capability per task only on a symmetric name-token Jaccard ≥ 0.5. On real MCP
packs this misses every task whose descriptive BPMN name diverges from the canonical tool id — e.g.
`Enrich`↔`enrich_investigation`, `Assess`↔`assess_beneficiary`, `Screen`↔`screen_party`,
`Notify`↔`notify_parties`, `DraftReturn`↔`draft_return`. Those stay `Select…`, the operator hand-picks each, and
(because `input_map` now keys off the bound capability) the input-source inference can't fire until they do — so
one weak match costs a whole row. On a large process that is a lot of manual clicks. Raise recall and **never
leave a cold "Select…" when staged capabilities exist** — make Bindings confirm-only. Keep it domain-neutral
(ADR-047): stemming + generic structure only, no domain token lists.

## Recon first

- `webui/src/features/registry/OnboardingWizard.tsx`: `suggestedCapRef` / `tok()` (strips `cap.<domain>.` prefix,
  splits on non-alphanum, Jaccard ≥ 0.5), `capOptions` (staged + reused), `capByBareId`. This is where the match
  lives today.
- `backend/services/process-registry/app/services/inference.py`: `suggested_capability_id = cap.<domain>.<sanitize
  (name)>` (the element side of the comparison).

## Change 1 · A better, shared scoring function (pure + unit-tested)

Extract a pure `scoreCapMatch(element, candidateId)` (share it, or mirror it, between the wizard and any backend
suggestion). Inputs: the element token bag (from the task **name** + its inferred `suggested_capability_id`) and a
candidate capability's bare id. Steps:

1. **Tokenize + generic noise-strip**: drop the `cap.<domain>.` prefix, pure-numeric tokens (`004`), and
   single-character tokens. Do **not** hardcode domain words (`payment`, `pacs`, …) — that would couple the
   platform to a domain. (Both sides already share the domain prefix, so it contributes nothing anyway.)
2. **Light deterministic stemming** (no NLP dependency): suffix-fold common English endings so tokens unify —
   `investigate`≈`investigation` (`-ate`/`-ation`→`-at`), `screen`≈`screening` (`-ing`), `notify`≈`notification`,
   `parties`≈`party` and plural `-s/-es/-ies`. A small rule table is fine; keep it generic English morphology.
3. **Score = blend of three signals**, take the max/weighted best:
   - **Directional containment** — fraction of the *candidate id's* tokens present in the element bag. This is the
     key fix: MCP tool ids are short/canonical (`draft_return`, `assess_beneficiary`) while task names are long and
     descriptive, so "are the tool's tokens in the task name?" scores `draft_return` ⊂ "Draft payment return
     (pacs.004)" at 1.0 where symmetric Jaccard gave 0.4.
   - **Symmetric Jaccard** (as today) — keeps well-aligned names strong.
   - **Substring/prefix bonus** on the primary (longest) shared token (`screen` in `screen_party`).

## Change 2 · Rank, auto-select confidently, else surface a one-click "best guess"

For each capability task, rank **all** `capOptions` by `scoreCapMatch`, descending:

- **Auto-select** the top when it is confident *and* clearly ahead — e.g. containment ≥ 0.6 (or Jaccard ≥ 0.5)
  **and** a margin over the runner-up. Show the existing **"suggested"** chip; bump HITL to the floor as today.
- **Best-guess (below the auto bar but plausible)**: pre-fill the top candidate but mark it with a distinct,
  dimmer chip (e.g. **"likely"**) so the operator sees it's a lower-confidence guess to confirm or change in one
  click — **instead of** a cold `Select…`. This is the key UX change for large processes.
- **Only** when there is genuinely no signal (zero token overlap with any candidate) does the row stay `Select…`.
- Order the dropdown options by score (best first) so even a manual change is one glance.

Because `input_map` inference keys off the bound `capability_ref`, an auto- or best-guess selection immediately
cascades: `chooseExecutor` re-derives the input sources, so confirming the capability fills the whole row. The
Bindings step becomes confirm-only on well-formed packs.

## Change 3 (optional) · Mirror the ranking in backend inference

Have `inference.py` emit a **ranked** candidate list per element (top-K by the shared score) rather than a single
fuzzy id, so the wizard's pre-fill and any future server-side use agree. Not required if the wizard remains the
single match site, but it keeps one scoring definition.

## Non-goals

- No domain-specific token lists, synonym tables, or ML — this is deterministic morphology + set containment. A
  task with no token overlap still asks the operator (no wild guessing). No change to the bijection, HITL floor,
  `input_map` contract, or validation.

## Definition of done

- On `ws-stan`, all ten capability tasks either **auto-bind** (confident) or show a correct **one-click best
  guess** — no cold `Select…` for `Enrich`/`Assess`/`Screen`/`Notify`/`DraftReturn`; confirming each cascades into
  its `input_map` with no further authoring.
- `scoreCapMatch` is a pure, unit-tested function: cases for stemming (`investigate`↔`investigation`),
  containment (`draft_return` ⊂ a long name), substring (`screen`↔`screen_party`), a no-overlap task staying
  blank, and correct ranking when several caps are close. A wizard render test asserting a divergent-name task now
  shows a pre-filled capability + chip.
- Seed packs and already-aligned names behave exactly as before (the auto bar still fires; no regressions).
  `registry` + `webui` green, `tsc` clean. Onboarding guide §4 notes ranked pre-fill + the "likely" best-guess.

## Grouping note

This is the anchor of the **onboarding inference & guardrails** batch (batch-4): together with the capability-id
**collision guardrail** (flag an introspected id colliding with the active catalog at the Capabilities step) and
the **triage field-schema validation** (validate a triage rule's `field`/`op` against the trigger schema — the
`reason_code`/`reason_codes` class of bug). All three are "infer/validate against real schemas at authoring time"
and can ship together or as three focused prompts.
