import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "react-oidc-context";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { oidcConfig } from "@/auth/oidc";
import { AuthWiring } from "@/auth/AuthWiring";
import { IdentityProvider } from "@/session/IdentityContext";
import { NotificationsProvider } from "@/app/NotificationsProvider";
import { ThemeProvider } from "@/app/theme";
import { useState, type ReactNode } from "react";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 2000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  return (
    <ThemeProvider>
      <AuthProvider {...oidcConfig}>
        <AuthWiring />
        <QueryClientProvider client={queryClient}>
          <NotificationsProvider>
            <IdentityProvider>
              <TooltipProvider delayDuration={200}>
                {children}
                <Toaster />
              </TooltipProvider>
            </IdentityProvider>
          </NotificationsProvider>
        </QueryClientProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
