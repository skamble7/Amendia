// capMatch.test.ts — the capability pre-select scorer (batch-4). Deterministic morphology + set containment;
// no domain token lists. Divergent descriptive names must still recall their canonical MCP tool id.
import { describe, it, expect } from "vitest";

import { stem, tokenize, scoreCapMatch, rankCapMatches } from "./capMatch";

describe("stem", () => {
  it("folds common English suffixes so variants unify", () => {
    expect(stem("investigate")).toBe(stem("investigation"));   // -ate / -ation
    expect(stem("screening")).toBe("screen");                  // -ing
    expect(stem("notify")).toBe(stem("notification"));         // -fy / -fication
    expect(stem("parties")).toBe("party");                     // -ies plural
    expect(stem("codes")).toBe("code");                        // -s plural (not -es)
    expect(stem("batches")).toBe("batch");                     // -ches -> -ch
  });
  it("never over-strips a short token", () => {
    expect(stem("is")).toBe("is");
    expect(stem("ate")).toBe("ate");                           // stripping would leave < 3 chars
  });
});

describe("tokenize", () => {
  it("strips the cap.<domain>. prefix, numerics and single chars, then stems", () => {
    expect(tokenize("cap.payment.draft_return")).toEqual(["draft", "return"]);
    expect(tokenize("Draft payment return (pacs.004)")).toEqual(["draft", "payment", "return", "pac"]);
  });
});

describe("scoreCapMatch", () => {
  const bag = (name: string, id?: string) => [...tokenize(name), ...(id ? tokenize(id) : [])];

  it("scores a short canonical id fully contained in a long name at 1.0 (the key fix)", () => {
    expect(scoreCapMatch(bag("Draft payment return (pacs.004)"), "cap.payment.draft_return")).toBe(1);
    expect(scoreCapMatch(bag("Assess beneficiary details"), "cap.payment.assess_beneficiary")).toBe(1);
  });

  it("recalls a stemmed divergence (Enrich vs enrich_investigation) above zero", () => {
    const s = scoreCapMatch(bag("Enrich", "cap.payment.enrich"), "cap.payment.enrich_investigation");
    expect(s).toBeGreaterThanOrEqual(0.5);   // one of two candidate tokens present
    expect(s).toBeLessThan(0.6);             // …but not confident → a "likely" best guess
  });

  it("gives a substring match a plausible (not confident) score", () => {
    // an un-split join: candidate token `screenparty` shares the `screen` substring with the task.
    const s = scoreCapMatch(["screen", "party"], "cap.x.screenparty");
    expect(s).toBe(0.5);
  });

  it("returns 0 when nothing overlaps (row stays blank)", () => {
    expect(scoreCapMatch(bag("Reconcile ledger"), "cap.payment.assess_beneficiary")).toBe(0);
  });
});

describe("rankCapMatches", () => {
  const OPTS = [
    "cap.payment.enrich_investigation@^1.0.0",
    "cap.payment.assess_beneficiary@^1.0.0",
    "cap.payment.draft_return@^1.0.0",
  ];

  it("auto-suggests a confident, clearly-ahead top match", () => {
    const { top } = rankCapMatches(tokenize("Draft payment return"), OPTS);
    expect(top?.ref).toBe("cap.payment.draft_return@^1.0.0");
    expect(top?.tier).toBe("suggested");
  });

  it("best-guesses (likely) a low-confidence top instead of leaving it blank", () => {
    const { top } = rankCapMatches([...tokenize("Enrich"), ...tokenize("cap.payment.enrich")], OPTS);
    expect(top?.ref).toBe("cap.payment.enrich_investigation@^1.0.0");
    expect(top?.tier).toBe("likely");
  });

  it("ranks options best-first and returns null top on no signal", () => {
    const { ranked } = rankCapMatches(tokenize("Assess beneficiary"), OPTS);
    expect(ranked[0]).toBe("cap.payment.assess_beneficiary@^1.0.0");
    expect(rankCapMatches(tokenize("Reconcile ledger"), OPTS).top).toBeNull();
  });
});
