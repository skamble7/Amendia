import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "@/app/AppShell";
import { RequireAuth } from "@/app/RequireAuth";
import { SignIn } from "@/features/auth/SignIn";
import { AuthCallback } from "@/auth/AuthCallback";
import { InboxPage } from "@/features/inbox/InboxPage";
import { TaskDetailPage } from "@/features/task/TaskDetailPage";
import { InstancesPage } from "@/features/instances/InstancesPage";
import { InstanceDetailPage } from "@/features/instances/InstanceDetailPage";
import { ExceptionsPage } from "@/features/exceptions/ExceptionsPage";
import { ExceptionDetailPage } from "@/features/exceptions/ExceptionDetailPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { RegistryPage } from "@/features/registry/RegistryPage";
import { PackDetailPage } from "@/features/registry/PackDetailPage";
import { OnboardingWizard } from "@/features/registry/OnboardingWizard";
import { UsersListPage } from "@/features/admin/UsersListPage";
import { UserDetailPage } from "@/features/admin/UserDetailPage";
import { RequireRole } from "@/app/RequireRole";
import { HomeRedirect } from "@/app/HomeRedirect";

/**
 * Route table. Feature screens are stubbed here and replaced milestone by
 * milestone (inbox/task = M3, instances/exceptions = M4, dashboard = M5,
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
      { path: "exceptions", element: <ExceptionsPage /> },
      { path: "exceptions/:exceptionId", element: <ExceptionDetailPage /> },
      { path: "registry", element: <RegistryPage /> },
      { path: "registry/onboard", element: <OnboardingWizard /> },
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
