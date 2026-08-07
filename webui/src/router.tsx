import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "@/app/AppShell";
import { RequireAuth } from "@/app/RequireAuth";
import { SignIn } from "@/features/auth/SignIn";
import { AuthCallback } from "@/auth/AuthCallback";
import { InboxPage } from "@/features/inbox/InboxPage";
import { TaskDetailPage } from "@/features/task/TaskDetailPage";
import { InstancesPage } from "@/features/instances/InstancesPage";
import { InstanceDetailPage } from "@/features/instances/InstanceDetailPage";
import { TriggersPage } from "@/features/triggers/TriggersPage";
import { TriggerDetailPage } from "@/features/triggers/TriggerDetailPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { RegistryPage } from "@/features/registry/RegistryPage";
import { PackDetailPage } from "@/features/registry/PackDetailPage";
import { OnboardingWizard } from "@/features/registry/OnboardingWizard";
import { CopilotFlow } from "@/features/copilot/CopilotFlow";
import { UsersListPage } from "@/features/admin/UsersListPage";
import { UserDetailPage } from "@/features/admin/UserDetailPage";
import { RequireRole } from "@/app/RequireRole";
import { HomeRedirect } from "@/app/HomeRedirect";

/**
 * Route table. Feature screens are stubbed here and replaced milestone by
 * milestone (inbox/task = M3, instances/triggers = M4, dashboard = M5,
 * registry = M6).
 */
export const router = createBrowserRouter([
  { path: "/signin", element: <SignIn /> },
  { path: "/auth/callback", element: <AuthCallback /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <HomeRedirect /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "inbox", element: <InboxPage /> },
      { path: "inbox/:taskId", element: <TaskDetailPage /> },
      { path: "instances", element: <InstancesPage /> },
      { path: "instances/:instanceId", element: <InstanceDetailPage /> },
      { path: "triggers", element: <TriggersPage /> },
      { path: "triggers/:triggerId", element: <TriggerDetailPage /> },
      { path: "registry", element: <RegistryPage /> },
      // ADR-052 2c: the copilot flow is the default front door; the technical wizard demotes to an inspection view.
      { path: "registry/onboard", element: <CopilotFlow /> },
      { path: "registry/onboard/:sessionId", element: <CopilotFlow /> },
      { path: "registry/onboard/technical", element: <OnboardingWizard /> },
      { path: "registry/onboard/technical/:sessionId", element: <OnboardingWizard /> },
      { path: "registry/packs/:packKey/:version", element: <PackDetailPage /> },
      {
        path: "admin/users",
        element: (
          <RequireRole role="role.platform.admin">
            <UsersListPage />
          </RequireRole>
        ),
      },
      {
        path: "admin/users/:userId",
        element: (
          <RequireRole role="role.platform.admin">
            <UserDetailPage />
          </RequireRole>
        ),
      },
    ],
  },
  { path: "*", element: <Navigate to="/dashboard" replace /> },
]);
