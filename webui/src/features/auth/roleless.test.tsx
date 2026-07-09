import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthContext, type AuthContextProps } from "react-oidc-context";
import { TooltipProvider } from "@/components/ui/tooltip";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { RequireAuth } from "@/app/RequireAuth";
import { AppShell } from "@/app/AppShell";
import { IdentityProvider } from "@/session/IdentityContext";
import { setTestToken } from "@/auth/authToken";

function makeAuth(over: Partial<AuthContextProps> = {}): AuthContextProps {
  return {
    isLoading: false,
    isAuthenticated: true,
    user: { access_token: "t" },
    signoutRedirect: vi.fn(),
    signinRedirect: vi.fn(),
    signinSilent: vi.fn(),
    removeUser: vi.fn(),
    ...over,
  } as unknown as AuthContextProps;
}

function meWithRoles(roles: string[]) {
  return http.get(`${SERVICE_BASE.identity}/me`, () =>
    HttpResponse.json({
      amendia_user_id: "usr-sam",
      identities: [],
      email: "sam@test.local",
      display_name: "Sam",
      status: "active",
      roles,
    }),
  );
}

function renderGated(auth: AuthContextProps) {
  setTestToken("t");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <AuthContext.Provider value={auth}>
      <QueryClientProvider client={qc}>
        <TooltipProvider delayDuration={0}>
          <MemoryRouter initialEntries={["/"]}>
            <IdentityProvider>
              <Routes>
                <Route
                  path="/"
                  element={
                    <RequireAuth>
                      <AppShell />
                    </RequireAuth>
                  }
                />
              </Routes>
            </IdentityProvider>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>
    </AuthContext.Provider>,
  );
}

describe("roleless-user state (A5)", () => {
  it("shows the calm 'no access yet' state (not the app shell) when /me has zero roles", async () => {
    server.use(meWithRoles([]));
    renderGated(makeAuth());
    expect(await screen.findByText(/doesn't have any roles yet/i)).toBeInTheDocument();
    // The app shell nav must not render for a roleless user.
    expect(screen.queryByRole("link", { name: /Task inbox/i })).not.toBeInTheDocument();
  });

  it("renders the app shell when the user has a role", async () => {
    server.use(meWithRoles(["role.payments.ops_analyst"]));
    renderGated(makeAuth());
    expect(await screen.findByText("Sam")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Task inbox/i }).length).toBeGreaterThan(0);
  });

  it("shows only Administration in the nav for a platform-admin-only user", async () => {
    server.use(meWithRoles(["role.platform.admin"]));
    renderGated(makeAuth());
    await screen.findByText("Sam");
    expect(screen.getAllByRole("link", { name: /Administration/i }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: /Task inbox/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Instances/i })).not.toBeInTheDocument();
  });
});
