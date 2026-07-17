import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { IdentityContext, type Identity } from "@/session/IdentityContext";
import { setTestToken } from "@/auth/authToken";
import { ROLE } from "@/lib/roles";
import { SERVICE_BASE } from "@/api/config";
import { server } from "@/test/server";
import type { UserView } from "@/api/services/identity";
import { UsersListPage } from "./UsersListPage";
import { UserDetailPage } from "./UserDetailPage";

const ID = SERVICE_BASE.identity;
const REG = SERVICE_BASE.registry;

function identity(userId: string, roles: string[]): Identity {
  return { amendiaUserId: userId, displayName: userId, email: `${userId}@test.local`, roles };
}

function makeUser(over: Partial<UserView> = {}): UserView {
  return {
    amendia_user_id: "usr-1",
    identities: [{ iss: "http://idp/realms/x", sub: "sub-1" }],
    email: "u1@test.local",
    display_name: "User One",
    status: "active",
    roles: [],
    role_details: [],
    created_at: "2099-01-01T00:00:00Z",
    updated_at: "2099-01-01T00:00:00Z",
    ...over,
  };
}

function renderAdmin(path: string, who: Identity) {
  setTestToken("test-token");
  const value = {
    identity: who,
    isLoading: false,
    isDisabled: false,
    error: null,
    hasRole: (r: string) => who.roles.includes(r),
    refetch: () => {},
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <IdentityContext.Provider value={value}>
        <TooltipProvider delayDuration={0}>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path="/admin/users" element={<UsersListPage />} />
              <Route path="/admin/users/:userId" element={<UserDetailPage />} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </IdentityContext.Provider>
    </QueryClientProvider>,
  );
}

const ADMIN = identity("usr-admin", [ROLE.platformAdmin]);

describe("Users list (A1)", () => {
  it("renders users with status, role badges, and a disabled row", async () => {
    server.use(
      http.get(`${ID}/users`, () =>
        HttpResponse.json([
          makeUser({ amendia_user_id: "usr-a", display_name: "Alice Admin", roles: [ROLE.platformAdmin] }),
          makeUser({ amendia_user_id: "usr-d", display_name: "Dana Disabled", status: "disabled" }),
        ]),
      ),
    );
    renderAdmin("/admin/users", ADMIN);
    expect(await screen.findByText("Alice Admin")).toBeInTheDocument();
    // Assert the row badges specifically — "Platform admin"/"Disabled" also appear
    // as filter <option>s, so scope to the table.
    const table = screen.getByRole("table");
    expect(within(table).getByText("Platform admin")).toBeInTheDocument();
    expect(within(table).getByText("Dana Disabled")).toBeInTheDocument();
    expect(within(table).getByText("Disabled")).toBeInTheDocument();
  });

  it("filters to users with no roles", async () => {
    server.use(
      http.get(`${ID}/users`, () =>
        HttpResponse.json([
          makeUser({ amendia_user_id: "usr-a", display_name: "Has Role", roles: [ROLE.analyst] }),
          makeUser({ amendia_user_id: "usr-n", display_name: "No Role", roles: [] }),
        ]),
      ),
    );
    const user = userEvent.setup();
    renderAdmin("/admin/users", ADMIN);
    await screen.findByText("Has Role");
    await user.selectOptions(screen.getByLabelText("Filter by role"), "__none__");
    expect(screen.getByText("No Role")).toBeInTheDocument();
    expect(screen.queryByText("Has Role")).not.toBeInTheDocument();
  });
});

describe("Pending access (A1/A4)", () => {
  it("stages access for a new email", async () => {
    server.use(
      http.get(`${ID}/users`, () => HttpResponse.json([])),
      http.get(`${ID}/pending-role-assignments`, () => HttpResponse.json([])),
      http.post(`${ID}/pending-role-assignments`, async ({ request }) => {
        const body = (await request.json()) as { email: string; roles: string[] };
        return HttpResponse.json(
          { email: body.email, roles: body.roles, staged_by: "usr-admin", staged_at: "2099-01-01T00:00:00Z" },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderAdmin("/admin/users", ADMIN);
    await user.click(screen.getByRole("tab", { name: /pending access/i }));
    await user.click((await screen.findAllByRole("button", { name: /stage access/i }))[0]!);

    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Email"), "new@org.com");
    // Roles live under their pack in the master-detail rail — open the pack, then pick the role.
    await user.click(within(dialog).getByText("wire-repair-standard"));
    await user.click(await within(dialog).findByText("Analyst"));
    await user.click(within(dialog).getByRole("button", { name: /^stage access$/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("offers a redirect when the staged email already belongs to a user (409 user_exists)", async () => {
    server.use(
      http.get(`${ID}/users`, () => HttpResponse.json([])),
      http.get(`${ID}/pending-role-assignments`, () => HttpResponse.json([])),
      http.post(`${ID}/pending-role-assignments`, () =>
        HttpResponse.json(
          { detail: { error: "user_exists", amendia_user_id: "usr-existing", email: "taken@org.com" } },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderAdmin("/admin/users", ADMIN);
    await user.click(screen.getByRole("tab", { name: /pending access/i }));
    await user.click((await screen.findAllByRole("button", { name: /stage access/i }))[0]!);

    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Email"), "taken@org.com");
    await user.click(within(dialog).getByText("wire-repair-standard"));
    await user.click(await within(dialog).findByText("Analyst"));
    await user.click(within(dialog).getByRole("button", { name: /^stage access$/i }));

    expect(await within(dialog).findByText(/already belongs to a provisioned user/i)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /go to user/i })).toBeInTheDocument();
  });
});

describe("User detail (A2/A3)", () => {
  it("shows role rows with assigned-by and assigns a new role", async () => {
    const target = makeUser({
      amendia_user_id: "usr-1",
      display_name: "User One",
      roles: [ROLE.analyst],
      role_details: [{ role: ROLE.analyst, assigned_by: "usr-admin", assigned_at: "2099-01-01T00:00:00Z" }],
    });
    server.use(
      http.get(`${ID}/users/usr-1`, () => HttpResponse.json(target)),
      http.get(`${ID}/users`, () => HttpResponse.json([makeUser({ amendia_user_id: "usr-admin", roles: [ROLE.platformAdmin] })])),
      http.post(`${ID}/users/usr-1/roles`, async ({ request }) => {
        const body = (await request.json()) as { role: string };
        return HttpResponse.json({ ...target, roles: [...target.roles!, body.role] }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderAdmin("/admin/users/usr-1", ADMIN);
    expect(await screen.findByText("User One")).toBeInTheDocument();
    expect(screen.getByText("Analyst")).toBeInTheDocument();
    expect(screen.getByText(/assigned by/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /assign role/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByText("Process owner"));
    await user.click(within(dialog).getByRole("button", { name: /^assign role$/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("lists a pack-supplied role in the assign picker (derived from active packs)", async () => {
    const target = makeUser({ amendia_user_id: "usr-1", display_name: "User One", roles: [] });
    server.use(
      http.get(`${ID}/users/usr-1`, () => HttpResponse.json(target)),
      http.get(`${ID}/users`, () => HttpResponse.json([makeUser({ amendia_user_id: "usr-admin", roles: [ROLE.platformAdmin] })])),
      // A pack that invented its own role, with no authored metadata → humanized label.
      http.get(`${REG}/roles`, () =>
        HttpResponse.json([
          { role_id: "role.lending.underwriter", label: null, description: null, sources: ["lending-review@1.0.0"] },
        ]),
      ),
    );
    const user = userEvent.setup();
    renderAdmin("/admin/users/usr-1", ADMIN);
    expect(await screen.findByText("User One")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /assign role/i }));
    const dialog = await screen.findByRole("dialog");
    // The derived pack appears as a rail entry (labeled by pack_key, no title stubbed); opening
    // it reveals its role with a humanized label (no authored metadata for this pack).
    await user.click(await within(dialog).findByText("lending-review"));
    expect(await within(dialog).findByText("Underwriter")).toBeInTheDocument();
  });

  it("disables self-targeting controls with a guardrail (own admin account)", async () => {
    const self = makeUser({
      amendia_user_id: "usr-admin",
      display_name: "Me Admin",
      roles: [ROLE.platformAdmin],
      role_details: [{ role: ROLE.platformAdmin, assigned_by: "seed", assigned_at: "2099-01-01T00:00:00Z" }],
    });
    server.use(
      http.get(`${ID}/users/usr-admin`, () => HttpResponse.json(self)),
      http.get(`${ID}/users`, () => HttpResponse.json([self])), // sole active admin
    );
    renderAdmin("/admin/users/usr-admin", ADMIN);
    expect(await screen.findByText("Me Admin")).toBeInTheDocument();
    // Both self-protection and last-admin apply — revoke + disable are locked.
    expect(screen.getByRole("button", { name: /revoke/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /disable account/i })).toBeDisabled();
  });

  it("disables revoke on the last active admin (not self)", async () => {
    const bob = makeUser({
      amendia_user_id: "usr-bob",
      display_name: "Bob Admin",
      roles: [ROLE.platformAdmin],
      role_details: [{ role: ROLE.platformAdmin, assigned_by: "seed", assigned_at: "2099-01-01T00:00:00Z" }],
    });
    server.use(
      http.get(`${ID}/users/usr-bob`, () => HttpResponse.json(bob)),
      http.get(`${ID}/users`, () => HttpResponse.json([bob])), // bob is the only active admin
    );
    renderAdmin("/admin/users/usr-bob", ADMIN);
    expect(await screen.findByText("Bob Admin")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /revoke/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /disable account/i })).toBeDisabled();
  });
});
