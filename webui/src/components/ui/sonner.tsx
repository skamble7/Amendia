import { Toaster as Sonner, type ToasterProps } from "sonner";
import { useTheme } from "@/app/theme";

/**
 * Toast surface. Colors come from the token system so light/dark both work; the
 * sonner base theme follows the app's ThemeProvider (not the OS directly).
 * error/success toasts are normalized in api/client.ts.
 */
export function Toaster(props: ToasterProps) {
  const { resolvedTheme } = useTheme();
  return (
    <Sonner
      theme={resolvedTheme}
      position="bottom-right"
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-popover group-[.toaster]:text-popover-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg",
          description: "group-[.toast]:text-muted-foreground",
          actionButton: "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton: "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
          error: "group-[.toaster]:border-danger/40",
          success: "group-[.toaster]:border-success/40",
        },
      }}
      {...props}
    />
  );
}
