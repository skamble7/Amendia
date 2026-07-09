import { toast } from "sonner";
import { SERVICE_BASE, SERVICE_LABEL, type ServiceKey } from "./config";
import { authBridge } from "@/auth/authToken";

/** Normalized API error surfaced to features + the toast layer. */
export class ApiError extends Error {
  /** HTTP status, or 0 for a connectivity failure (service unreachable). */
  status: number;
  /** FastAPI `detail` (string, or a validation error array). */
  detail: unknown;
  /** the service the request targeted, for connectivity messaging */
  service?: ServiceKey;
  constructor(status: number, message: string, detail: unknown, service?: ServiceKey) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.service = service;
  }

  /** True when the service was unreachable (network error), not an HTTP response. */
  get isConnectivity(): boolean {
    return this.status === 0;
  }

  /** Best-effort human string from a FastAPI error body. */
  get detailText(): string {
    if (typeof this.detail === "string") return this.detail;
    if (Array.isArray(this.detail)) {
      return this.detail
        .map((d: any) => (d?.msg ? `${(d.loc ?? []).join(".")}: ${d.msg}` : JSON.stringify(d)))
        .join("; ");
    }
    return this.message;
  }
}

/** Type guard for a connectivity (service-unreachable) failure. */
export function isConnectivityError(err: unknown): err is ApiError {
  return err instanceof ApiError && err.isConnectivity;
}

/** The service name behind a connectivity error, for the unreachable banner. */
export function connectivityService(err: unknown): string | undefined {
  return isConnectivityError(err) && err.service ? SERVICE_LABEL[err.service] : undefined;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  /** raw text body (e.g. BPMN XML upload) with an explicit content type */
  rawBody?: { content: string; contentType: string };
  /** suppress the automatic error toast (caller handles it, e.g. expected 403/409) */
  silent?: boolean;
  signal?: AbortSignal;
}

function buildUrl(service: ServiceKey, path: string, query?: RequestOptions["query"]): string {
  const base = SERVICE_BASE[service].replace(/\/$/, "");
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

function connectivityError(service: ServiceKey): ApiError {
  return new ApiError(0, `${SERVICE_LABEL[service]} is unreachable — is the backend stack running?`, null, service);
}

/** 401 from a genuine end-of-session (bearer expired / revoked), not a domain 403. */
function sessionExpiredError(service: ServiceKey): ApiError {
  return new ApiError(401, "Your session has expired — signing you in again.", { error: "invalid_token" }, service);
}

/**
 * The single fetch seam. All service modules call this; the Vite/nginx proxy
 * forwards to the live services underneath. Every request carries the OIDC access
 * token (Authorization: Bearer). Errors are normalized to ApiError.
 *
 * Auth handling: a 401 triggers one silent-renew + retry; if that still fails,
 * we hand off to a full sign-in (preserving location) and surface a silent error.
 * A 403 is a domain decision (missing role / SoD) — never a redirect; the caller
 * renders it. Connectivity failures (status 0) never toast — screens show the
 * inline "service unreachable" banner (ConnectivityState). Other 4xx/5xx toast
 * unless `silent`.
 */
export async function request<T>(service: ServiceKey, path: string, opts: RequestOptions = {}): Promise<T> {
  return requestAuthed<T>(service, path, opts, false);
}

async function requestAuthed<T>(
  service: ServiceKey,
  path: string,
  opts: RequestOptions,
  retried: boolean,
): Promise<T> {
  const { method = "GET", query, body, rawBody, silent, signal } = opts;
  const token = authBridge.token();

  // No token means we're not authenticated — fail closed to a sign-in rather than
  // firing an unauthenticated request. (The route guard normally prevents this.)
  if (!token) {
    authBridge.onAuthLost();
    throw sessionExpiredError(service);
  }

  const headers: Record<string, string> = { accept: "application/json", authorization: `Bearer ${token}` };
  let payload: BodyInit | undefined;

  if (rawBody) {
    headers["content-type"] = rawBody.contentType;
    payload = rawBody.content;
  } else if (body !== undefined) {
    headers["content-type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let res: Response;
  try {
    res = await fetch(buildUrl(service, path, query), { method, headers, body: payload, signal });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw connectivityError(service); // no toast — the screen banner owns this state
  }

  // Token expired: one silent renew + retry, then a full sign-in.
  if (res.status === 401 && !retried) {
    const renewed = await authBridge.renew();
    if (renewed) return requestAuthed<T>(service, path, opts, true);
    authBridge.onAuthLost();
    throw sessionExpiredError(service);
  }

  const isJson = res.headers.get("content-type")?.includes("application/json");
  const parsed = isJson ? await res.json().catch(() => null) : await res.text().catch(() => null);

  if (!res.ok) {
    const detail = isJson && parsed && typeof parsed === "object" ? (parsed as any).detail ?? parsed : parsed;
    const message =
      (typeof detail === "string" && detail) ||
      (Array.isArray(detail) && "Validation error") ||
      `${res.status} ${res.statusText}`;
    const apiErr = new ApiError(res.status, message, detail, service);
    if (!silent) toast.error(apiErr.detailText || message);
    throw apiErr;
  }

  return parsed as T;
}

/** Convenience for a GET that returns text/xml (e.g. BPMN). */
export async function requestText(service: ServiceKey, path: string, opts: RequestOptions = {}): Promise<string> {
  return requestTextAuthed(service, path, opts, false);
}

async function requestTextAuthed(
  service: ServiceKey,
  path: string,
  opts: RequestOptions,
  retried: boolean,
): Promise<string> {
  const token = authBridge.token();
  if (!token) {
    authBridge.onAuthLost();
    throw sessionExpiredError(service);
  }
  const base = SERVICE_BASE[service].replace(/\/$/, "");
  let res: Response;
  try {
    res = await fetch(`${base}${path}`, { signal: opts.signal, headers: { authorization: `Bearer ${token}` } });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw connectivityError(service);
  }
  if (res.status === 401 && !retried) {
    const renewed = await authBridge.renew();
    if (renewed) return requestTextAuthed(service, path, opts, true);
    authBridge.onAuthLost();
    throw sessionExpiredError(service);
  }
  if (!res.ok) {
    const apiErr = new ApiError(res.status, `${res.status} ${res.statusText}`, null, service);
    if (!opts.silent) toast.error(apiErr.message);
    throw apiErr;
  }
  return res.text();
}
