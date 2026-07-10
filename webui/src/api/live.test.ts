import { describe, it, expect } from "vitest";
import { pollInterval, SSE_HEALTHY_POLL_MS, FALLBACK_POLL_MS } from "@/api/live";

describe("pollInterval (SSE-health-driven fallback cadence)", () => {
  it("SSE up → slow safety poll, regardless of caller cadence", () => {
    expect(pollInterval("up", undefined)).toBe(SSE_HEALTHY_POLL_MS);
    expect(pollInterval("up", 5000)).toBe(SSE_HEALTHY_POLL_MS);
  });

  it("SSE down/connecting → fast fallback (or the caller's cadence)", () => {
    expect(pollInterval("down", undefined)).toBe(FALLBACK_POLL_MS);
    expect(pollInterval("connecting", undefined)).toBe(FALLBACK_POLL_MS);
    expect(pollInterval("down", 5000)).toBe(5000);
  });

  it("one-shot (false) stays one-shot in every state", () => {
    expect(pollInterval("up", false)).toBe(false);
    expect(pollInterval("down", false)).toBe(false);
  });
});
