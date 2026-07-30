import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { screen, render } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthContext } from "react-oidc-context";
import type { AuthContextProps } from "react-oidc-context";
import { TooltipProvider } from "@/components/ui/tooltip";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { RequireAuth } from "@/app/RequireAuth";
import { AppShell } from "@/app/AppShell";
import { AuthCallback } from "@/auth/AuthCallback";
import { IdentityProvider } from "@/session/IdentityContext";
import { configureAuthBridge, setTestToken } from "@/auth/authToken";
import { request } from "@/api/client";

// ---- a fake OIDC auth context ----
function makeAuth(over: Partial<AuthContextProps> = {}): AuthContextProps {
  return {
    isLoading: false,
    isAuthenticated: false,
    user: undefined,
    error: undefined,
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
    signinSilent: vi.fn(),
    removeUser: vi.fn(),
    ...over,
  } as unknown as AuthContextProps;
}

function withProviders(auth: AuthContextProps, ui: React.ReactNode, initial = "/") {
  // Mirror AuthWiring: the API client reads the bearer from the auth bridge.
  const token = auth.isAuthenticated ? ((auth.user?.access_token as string | undefined) ?? "t") : undefined;
  setTestToken(token);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <AuthContext.Provider value={auth}>
      <QueryClientProvider client={qc}>
        <TooltipProvider delayDuration={0}>
          <MemoryRouter initialEntries={[initial]}>{ui}</MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>
    </AuthContext.Provider>,
  );
}

describe("route protection", () => {
  it("bounces an unauthenticated deep link to the sign-in screen", () => {
    withProviders(
      makeAuth({ isAuthenticated: false }),
      <IdentityProvider>
        <Routes>
          <Route path="/inbox/:id" element={<RequireAuth><div>SECRET TASK</div></RequireAuth>} />
          <Route path="/signin" element={<div>SIGN-IN SCREEN</div>} />
        </Routes>
      </IdentityProvider>,
      "/inbox/xyz",
    );
    expect(screen.getByText("SIGN-IN SCREEN")).toBeInTheDocument();
    expect(screen.queryByText("SECRET TASK")).not.toBeInTheDocument();
  });
});

describe("role-aware navigation", () => {
  function me(roles: string[]) {
    return http.get(`${SERVICE_BASE.identity}/me`, () =>
      HttpResponse.json({
        amendia_user_id: "usr-1",
        identities: [],
        email: "u@test.local",
        display_name: "Test User",
        status: "active",
        roles,
      }),
    );
  }

  it("hides Registry for a user without role.process.owner", async () => {
    server.use(me(["role.payments.ops_analyst"]));
    withProviders(
      makeAuth({ isAuthenticated: true, user: { access_token: "t" } as never }),
      <IdentityProvider>
        <Routes>
          <Route path="/" element={<AppShell />} />
        </Routes>
      </IdentityProvider>,
    );
    await screen.findByText("Test User");
    // nav renders in both the sidebar and the mobile fallback, hence *All*.
    expect(screen.queryAllByRole("link", { name: /Registry/i })).toHaveLength(0);
    expect(screen.getAllByRole("link", { name: /Task inbox/i }).length).toBeGreaterThan(0);
  });

  it("shows Registry for a process owner", async () => {
    server.use(me(["role.process.owner"]));
    withProviders(
      makeAuth({ isAuthenticated: true, user: { access_token: "t" } as never }),
      <IdentityProvider>
        <Routes>
          <Route path="/" element={<AppShell />} />
        </Routes>
      </IdentityProvider>,
    );
    await screen.findByText("Test User");
    expect(screen.getAllByRole("link", { name: /Registry/i }).length).toBeGreaterThan(0);
  });

  // Domain-neutral nav gating (ADR-026): operator surfaces show for ANY non-platform-admin
  // role; Registry/Administration remain the two platform-role special cases. Asserted
  // against every seeded persona so none regress, plus a fabricated unknown-pack role.
  async function renderNavFor(roles: string[]) {
    server.use(me(roles));
    withProviders(
      makeAuth({ isAuthenticated: true, user: { access_token: "t" } as never }),
      <IdentityProvider>
        <Routes>
          <Route path="/" element={<AppShell />} />
        </Routes>
      </IdentityProvider>,
    );
    await screen.findByText("Test User");
  }
  const OPERATOR_SURFACES = [/Dashboard/i, /Task inbox/i, /Instances/i, /Exceptions/i];
  const hasNav = (name: RegExp) => screen.queryAllByRole("link", { name }).length > 0;

  it("alex (role.platform.admin only) → Administration only, no operator surfaces", async () => {
    await renderNavFor(["role.platform.admin"]);
    expect(hasNav(/Administration/i)).toBe(true);
    expect(hasNav(/Registry/i)).toBe(false);
    for (const s of OPERATOR_SURFACES) expect(hasNav(s)).toBe(false);
  });

  it("priya (role.process.owner + role.platform.admin) → operator surfaces + Registry + Administration", async () => {
    await renderNavFor(["role.process.owner", "role.platform.admin"]);
    expect(hasNav(/Administration/i)).toBe(true);
    expect(hasNav(/Registry/i)).toBe(true);
    for (const s of OPERATOR_SURFACES) expect(hasNav(s)).toBe(true);
  });

  it("riya (payments analyst) → operator surfaces, no Registry/Administration", async () => {
    await renderNavFor(["role.payments.ops_analyst"]);
    for (const s of OPERATOR_SURFACES) expect(hasNav(s)).toBe(true);
    expect(hasNav(/Registry/i)).toBe(false);
    expect(hasNav(/Administration/i)).toBe(false);
  });

  it("marcus (payments approver) → operator surfaces", async () => {
    await renderNavFor(["role.payments.ops_approver"]);
    for (const s of OPERATOR_SURFACES) expect(hasNav(s)).toBe(true);
  });

  it("gio (role.rest_stan.diner — another pack) → operator surfaces (the fix)", async () => {
    await renderNavFor(["role.rest_stan.diner"]);
    for (const s of OPERATOR_SURFACES) expect(hasNav(s)).toBe(true);
    expect(hasNav(/Registry/i)).toBe(false);
    expect(hasNav(/Administration/i)).toBe(false);
  });

  it("a single role from an arbitrary/unknown pack (role.foo.bar) grants operator surfaces", async () => {
    await renderNavFor(["role.foo.bar"]);
    for (const s of OPERATOR_SURFACES) expect(hasNav(s)).toBe(true);
    expect(hasNav(/Registry/i)).toBe(false);
    expect(hasNav(/Administration/i)).toBe(false);
  });
});

describe("auth callback", () => {
  it("restores the pre-login deep link stashed in OIDC state", async () => {
    withProviders(
      makeAuth({ isAuthenticated: true, user: { state: "/inbox/deep-1", access_token: "t" } as never }),
      <Routes>
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="/inbox/:id" element={<div>DEEP LINK TARGET</div>} />
      </Routes>,
      "/auth/callback",
    );
    expect(await screen.findByText("DEEP LINK TARGET")).toBeInTheDocument();
  });
});

describe("API client — 401 → silent renew → retry", () => {
  beforeEach(() => {
    let token = "expired";
    configureAuthBridge({
      getToken: () => token,
      renew: async () => {
        token = "fresh";
        return token;
      },
      onAuthLost: () => {},
    });
  });

  it("renews once on 401 and retries with the fresh token", async () => {
    const R = SERVICE_BASE.runtime;
    server.use(
      http.get(`${R}/hitl-tasks/x`, ({ request: req }) => {
        const auth = req.headers.get("authorization");
        if (auth === "Bearer fresh") return HttpResponse.json({ ok: true });
        return new HttpResponse(JSON.stringify({ detail: { error: "invalid_token" } }), {
          status: 401,
          headers: { "content-type": "application/json" },
        });
      }),
    );
    const result = await request<{ ok: boolean }>("runtime", "/hitl-tasks/x", { silent: true });
    expect(result).toEqual({ ok: true });
  });

  it("hands off to sign-in when renew fails", async () => {
    const onAuthLost = vi.fn();
    configureAuthBridge({ getToken: () => "stale", renew: async () => undefined, onAuthLost });
    const R = SERVICE_BASE.runtime;
    server.use(http.get(`${R}/hitl-tasks/y`, () => new HttpResponse(null, { status: 401 })));
    await expect(request("runtime", "/hitl-tasks/y", { silent: true })).rejects.toMatchObject({ status: 401 });
    expect(onAuthLost).toHaveBeenCalled();
  });
});
