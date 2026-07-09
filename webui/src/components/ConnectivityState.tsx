import { WifiOff } from "lucide-react";
import { isConnectivityError, connectivityService } from "@/api/client";

const COMPOSE_HINT = "docker compose -f backend/deploy/docker-compose.yml up";

/**
 * Single connectivity treatment for a service-unreachable error. Detection is
 * centralized in the API client (status 0); screens render this in place of an
 * empty table when their primary query fails to reach the backend, so a stopped
 * stack reads as "backend down", not "empty but healthy".
 */
export function ConnectivityState({ error }: { error: unknown }) {
  if (!isConnectivityError(error)) return null;
  const service = connectivityService(error) ?? "the backend";
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-danger/40 bg-danger-muted/20 px-6 py-14 text-center">
      <WifiOff className="size-7 text-danger" />
      <div className="space-y-1">
        <p className="text-sm font-medium">{service} is unreachable</p>
        <p className="max-w-md text-sm text-muted-foreground">
          Is the backend stack running? Start it with:
        </p>
        <code className="mt-1 inline-block rounded bg-surface px-2 py-1 font-mono text-xs">{COMPOSE_HINT}</code>
      </div>
    </div>
  );
}

/** Inline (compact) variant for detail screens and cards. */
export function ConnectivityBanner({ error }: { error: unknown }) {
  if (!isConnectivityError(error)) return null;
  const service = connectivityService(error) ?? "the backend";
  return (
    <div className="mb-4 flex items-start gap-2 rounded-md border border-danger/40 bg-danger-muted/20 p-3 text-sm">
      <WifiOff className="mt-0.5 size-4 shrink-0 text-danger" />
      <p>
        <span className="font-medium">{service} is unreachable.</span>{" "}
        <span className="text-muted-foreground">Is the backend stack running? </span>
        <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-xs">{COMPOSE_HINT}</code>
      </p>
    </div>
  );
}
