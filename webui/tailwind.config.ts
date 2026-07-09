import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

/**
 * Design tokens are defined as CSS variables in src/index.css and consumed here.
 * When the Amendia.dc.html prototype is reconciled, adjust the *values* in
 * index.css — component classes never hard-code colors.
 *
 * Semantic color system (from the design brief):
 *   agent      = purple  (agent activity)
 *   artifact   = teal    (artifacts / data)
 *   attention  = amber   (human attention / SLA)
 *   process    = coral   (process / routing)
 *   success/danger = green/red (outcomes only)
 */
const semantic = (name: string) => ({
  DEFAULT: `hsl(var(--${name}))`,
  foreground: `hsl(var(--${name}-foreground))`,
  muted: `hsl(var(--${name}-muted))`,
});

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        surface: {
          DEFAULT: "hsl(var(--surface))",
          raised: "hsl(var(--surface-raised))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // Diagram/BPMN canvas — intentionally light in both themes (see index.css).
        canvas: "hsl(var(--canvas))",
        // semantic tokens
        agent: semantic("agent"),
        artifact: semantic("artifact"),
        attention: semantic("attention"),
        process: semantic("process"),
        success: semantic("success"),
        danger: semantic("danger"),
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontFeatureSettings: {
        tabular: '"tnum" 1, "lnum" 1',
      },
      keyframes: {
        "amber-flash": {
          "0%": { backgroundColor: "hsl(var(--attention) / 0.18)" },
          "100%": { backgroundColor: "transparent" },
        },
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "amber-flash": "amber-flash 1.6s ease-out",
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [
    animate,
    ({ addUtilities }: { addUtilities: (u: Record<string, object>) => void }) => {
      addUtilities({
        ".tabular-nums": { fontVariantNumeric: "tabular-nums lining-nums" },
      });
    },
  ],
} satisfies Config;
