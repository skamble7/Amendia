import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider, useTheme, THEME_STORAGE_KEY } from "./theme";

function Probe() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="mode">{theme}</span>
      <span data-testid="resolved">{resolvedTheme}</span>
      <button onClick={() => setTheme("dark")}>set dark</button>
      <button onClick={() => setTheme("light")}>set light</button>
      <button onClick={() => setTheme("system")}>set system</button>
    </div>
  );
}

const realMatchMedia = window.matchMedia;

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("light", "dark");
});
afterEach(() => {
  window.matchMedia = realMatchMedia;
});

describe("ThemeProvider", () => {
  it("applies the class to <html> and persists the choice", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    // Default is system; the setup mock reports no dark preference → light.
    expect(document.documentElement.classList.contains("light")).toBe(true);

    await user.click(screen.getByText("set dark"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.classList.contains("light")).toBe(false);
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(screen.getByTestId("resolved").textContent).toBe("dark");
  });

  it("reads the persisted theme on mount", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("mode").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("follows the OS live while in system mode", () => {
    // Controllable matchMedia that starts dark and lets us fire a change.
    let listener: ((e: MediaQueryListEvent) => void) | null = null;
    const mql = {
      matches: true,
      media: "(prefers-color-scheme: dark)",
      onchange: null,
      addEventListener: (_: string, cb: (e: MediaQueryListEvent) => void) => {
        listener = cb;
      },
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    } as unknown as MediaQueryList;
    window.matchMedia = vi.fn().mockReturnValue(mql);

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    // system + OS dark → resolved dark
    expect(screen.getByTestId("resolved").textContent).toBe("dark");

    // OS flips to light → provider follows without changing the stored mode.
    act(() => {
      (mql as { matches: boolean }).matches = false;
      listener?.({} as MediaQueryListEvent);
    });
    expect(screen.getByTestId("resolved").textContent).toBe("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(screen.getByTestId("mode").textContent).toBe("system");
  });
});
