// capMatch.ts — capability pre-select scoring for the onboarding Bindings step (ADR-048 / batch-4).
//
// Real MCP tool ids are short and canonical (`draft_return`, `assess_beneficiary`) while the BPMN task names
// that should bind them are long and descriptive ("Draft payment return (pacs.004)"). A symmetric name-token
// Jaccard misses those, leaving a cold "Select…". This module raises recall with deterministic English
// morphology + directional set containment — NO domain token lists, synonym tables, or ML (ADR-047 neutral):
// a task with genuinely zero token overlap still asks the operator.

/** Light deterministic stemmer — suffix-fold common English endings so morphological variants unify
 * (`investigate`≈`investigation`, `screen`≈`screening`, `notify`≈`notification`, `parties`≈`party`). Generic
 * morphology only; applies the first matching rule and never over-strips below a 3-char stem. */
export function stem(t: string): string {
  const rules: [RegExp, string][] = [
    [/fication$/, "f"],            // notification -> notif  (== notify)
    [/ization$/, "iz"],            // organization -> organiz
    [/ation$/, "at"],              // investigation -> investigat
    [/ate$/, "at"],                // investigate  -> investigat
    [/ing$/, ""],                  // screening -> screen
    [/fy$/, "f"],                  // notify -> notif
    [/(ss|sh|ch|x|z)es$/, "$1"],   // boxes -> box, batches -> batch
    [/ies$/, "y"],                 // parties -> party, beneficiaries -> beneficiary
    [/s$/, ""],                    // codes -> code
  ];
  for (const [re, rep] of rules) {
    if (re.test(t)) {
      const out = t.replace(re, rep);
      if (out.length >= 3) return out;   // don't nuke short tokens (e.g. "is" -> "i")
    }
  }
  return t;
}

/** Tokenize an id or a human name into a stemmed token bag: strip the `cap.<domain>.` namespace, split on
 * non-alphanumerics, drop noise (the literal `cap`, single-character and pure-numeric tokens like `004`), stem. */
export function tokenize(s: string): string[] {
  return s.toLowerCase()
    .replace(/^cap\.[a-z0-9_]+\./, "")
    .split(/[^a-z0-9]+/)
    .filter((x) => x && x !== "cap" && x.length > 1 && !/^\d+$/.test(x))
    .map(stem);
}

/**
 * Score how well a candidate capability id fits an element's token bag, in [0, 1]. The bag is the stemmed
 * tokens of the task name (+ its inferred `cap.<domain>.<name>` id). Blends three signals and takes the best:
 *  - **directional containment** — fraction of the CANDIDATE's tokens present in the bag (the key fix: a short
 *    canonical tool id fully contained in a long descriptive name scores 1.0);
 *  - **symmetric Jaccard** — keeps well-aligned names strong (and unchanged from before);
 *  - **substring/prefix** nudge on a shared long token (catches un-split joins like `screenparty`⊃`screen`).
 * Returns 0 when the candidate shares no token with the bag (no signal → the caller leaves the row blank).
 */
export function scoreCapMatch(elementBag: string[], candidateId: string): number {
  const cand = tokenize(candidateId);
  if (cand.length === 0) return 0;
  const bag = new Set(elementBag);
  const candSet = new Set(cand);
  const inter = [...candSet].filter((t) => bag.has(t)).length;
  const containment = inter / candSet.size;
  const jaccard = inter / new Set([...bag, ...candSet]).size;
  let score = Math.max(containment, jaccard);
  if (score < 0.5) {
    const sub = [...candSet].some((c) =>
      [...bag].some((e) => e !== c && Math.min(e.length, c.length) >= 4 && (e.includes(c) || c.includes(e))));
    if (sub) score = 0.5;   // a strong substring overlap is a plausible (not confident) match
  }
  return score;
}

export type MatchTier = "suggested" | "likely";

export interface RankedMatch { ref: string; score: number; tier: MatchTier }

/** Rank every candidate ref for one element (best first) and classify the top: `suggested` when confident and
 * clearly ahead of the runner-up, else `likely` (a one-click best guess) when there is any signal, else null
 * (leave the row blank). AUTO bar: score ≥ 0.6 AND a ≥ 0.1 margin over the runner-up. */
export function rankCapMatches(elementBag: string[], candidateRefs: string[]): { ranked: string[]; top: RankedMatch | null } {
  const scored = candidateRefs
    .map((ref) => ({ ref, score: scoreCapMatch(elementBag, ref.split("@")[0] ?? "") }))
    .sort((a, b) => b.score - a.score);
  const ranked = scored.map((s) => s.ref);
  const best = scored[0];
  if (!best || best.score <= 0) return { ranked, top: null };
  const runner = scored[1]?.score ?? 0;
  const tier: MatchTier = best.score >= 0.6 && best.score - runner >= 0.1 ? "suggested" : "likely";
  return { ranked, top: { ref: best.ref, score: best.score, tier } };
}
