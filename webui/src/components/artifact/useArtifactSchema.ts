import { useQuery } from "@tanstack/react-query";
import { getArtifactSchema } from "@/api/services/registry";
import { parsePinnedRef, type JsonSchema } from "./schema";

/**
 * Fetch + cache an artifact's pinned JSON Schema from the registry. Keyed by the
 * pinned ref (+ owning pack coords) so a schema@version is fetched once and shared
 * across every view. ADR-060: artifact-schema reads are pack-scoped, so the owning
 * pack's coordinates are required to resolve the schema — the fetch is disabled until
 * they're known (the view degrades to a schema-less field tree in the meantime).
 */
export function useArtifactSchema(pinnedRef: string | undefined, packKey?: string, packVersion?: string) {
  const parsed = pinnedRef ? parsePinnedRef(pinnedRef) : null;
  return useQuery({
    queryKey: ["artifact-schema", packKey, packVersion, pinnedRef],
    enabled: !!parsed && !!packKey && !!packVersion,
    staleTime: Infinity, // pinned versions are immutable
    queryFn: async () => {
      const reg = await getArtifactSchema(packKey!, packVersion!, parsed!.key, parsed!.version);
      return (reg.json_schema ?? {}) as JsonSchema;
    },
  });
}
