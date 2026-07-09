import { useQuery } from "@tanstack/react-query";
import { getArtifactSchema } from "@/api/services/registry";
import { parsePinnedRef, type JsonSchema } from "./schema";

/**
 * Fetch + cache an artifact's pinned JSON Schema from the registry. Keyed by the
 * pinned ref so a schema@version is fetched once and shared across every view.
 */
export function useArtifactSchema(pinnedRef: string | undefined) {
  const parsed = pinnedRef ? parsePinnedRef(pinnedRef) : null;
  return useQuery({
    queryKey: ["artifact-schema", pinnedRef],
    enabled: !!parsed,
    staleTime: Infinity, // pinned versions are immutable
    queryFn: async () => {
      const reg = await getArtifactSchema(parsed!.key, parsed!.version);
      return (reg.json_schema ?? {}) as JsonSchema;
    },
  });
}
