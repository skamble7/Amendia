import { Monitor, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme, type ThemeMode } from "@/app/theme";

const OPTIONS: { mode: ThemeMode; label: string; icon: typeof Sun }[] = [
  { mode: "light", label: "Light", icon: Sun },
  { mode: "dark", label: "Dark", icon: Moon },
  { mode: "system", label: "System", icon: Monitor },
];

/**
 * Theme control for the top-bar user menu. A compact segmented control (Light /
 * Dark / System) — plain buttons so selecting one doesn't dismiss the menu.
 */
export function ThemeMenu() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="px-2 py-1.5">
      <div className="mb-1.5 text-xs font-medium text-muted-foreground">Theme</div>
      <div className="grid grid-cols-3 gap-1" role="radiogroup" aria-label="Theme">
        {OPTIONS.map(({ mode, label, icon: Icon }) => {
          const active = theme === mode;
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => setTheme(mode)}
              className={cn(
                "flex flex-col items-center gap-1 rounded-md border px-2 py-1.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                active
                  ? "border-primary bg-accent text-foreground"
                  : "border-transparent text-muted-foreground hover:bg-accent/60 hover:text-foreground",
              )}
            >
              <Icon className="size-4" />
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
