import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { IdentityContext, type Identity } from "@/session/IdentityContext";
import { setTestToken } from "@/auth/authToken";
import { ROLE } from "@/lib/roles";
import { InboxPage } from "@/features/inbox/InboxPage";
import { TaskDetailPage } from "@/features/task/TaskDetailPage";
import { InstancesPage } from "@/features/instances/InstancesPage";
import { InstanceDetailPage } from "@/features/instances/InstanceDetailPage";
import { ExceptionsPage } from "@/features/exceptions/ExceptionsPage";
import { ExceptionDetailPage } from "@/features/exceptions/ExceptionDetailPage";
import { RegistryPage } from "@/features/registry/RegistryPage";
import { PackDetailPage } from "@/features/registry/PackDetailPage";
import { OnboardingWizard } from "@/features/registry/OnboardingWizard";
import { DashboardPage } from "@/features/dashboard/DashboardPage";

/**
 * Test personas: the `amendia_user_id` a test passes doubles as the id SoD /
 * assignee comparisons key off, and its roles drive eligibility. (In the real
 * app both come from GET /me — here we inject them synchronously.)
 */
const PERSONA_ROLES: Record<string, string[]> = {
  "analyst-1": [ROLE.analyst],
  "approver-1": [ROLE.approver],
  "owner-1": [ROLE.processOwner, ROLE.platformAdmin],
};

export function testIdentity(userId: string, roles?: string[]): Identity {
  return {
    amendiaUserId: userId,
    displayName: userId,
    email: `${userId}@test.local`,
    roles: roles ?? PERSONA_ROLES[userId] ?? [ROLE.analyst],
  };
}

/** Render a slice of the app with a preset identity + a static bearer for the API client. */
export function renderApp(initialPath: string, userId: string, extra?: ReactElement) {
  setTestToken("test-token");
  const identity = testIdentity(userId);
  const identityValue = {
    identity,
    isLoading: false,
    isDisabled: false,
    error: null,
    hasRole: (role: string) => identity.roles.includes(role),
    refetch: () => {},
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <IdentityContext.Provider value={identityValue}>
        <TooltipProvider delayDuration={0}>
          <MemoryRouter initialEntries={[initialPath]}>
            <Routes>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/inbox" element={<InboxPage />} />
              <Route path="/inbox/:taskId" element={<TaskDetailPage />} />
              <Route path="/instances" element={<InstancesPage />} />
              <Route path="/instances/:instanceId" element={<InstanceDetailPage />} />
              <Route path="/exceptions" element={<ExceptionsPage />} />
              <Route path="/exceptions/:exceptionId" element={<ExceptionDetailPage />} />
              <Route path="/registry" element={<RegistryPage />} />
              <Route path="/registry/onboard" element={<OnboardingWizard />} />
              <Route path="/registry/packs/:packKey/:version" element={<PackDetailPage />} />
              {extra}
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </IdentityContext.Provider>
    </QueryClientProvider>,
  );
}
