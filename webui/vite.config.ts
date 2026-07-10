import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

// The four backend services. In `live` mode the app calls same-origin `/api/*`
// paths and Vite proxies them to the services, which avoids CORS in dev.
// In `mock` mode MSW intercepts before any network call, so the proxy is unused.
const PROXY_TARGETS: Record<string, string> = {
  "/api/stub": process.env.VITE_STUB_URL ?? "http://localhost:8081",
  "/api/ingestor": process.env.VITE_INGESTOR_URL ?? "http://localhost:8082",
  "/api/runtime": process.env.VITE_RUNTIME_URL ?? "http://localhost:8083",
  "/api/registry": process.env.VITE_REGISTRY_URL ?? "http://localhost:8084",
  "/api/identity": process.env.VITE_IDENTITY_URL ?? "http://localhost:8086",
  "/api/notifications": process.env.VITE_NOTIFICATIONS_URL ?? "http://localhost:8088",
};

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      Object.entries(PROXY_TARGETS).map(([prefix, target]) => [
        prefix,
        {
          target,
          changeOrigin: true,
          // strip the `/api/<service>` prefix; services are mounted at root
          rewrite: (p: string) => p.replace(new RegExp(`^${prefix}`), ""),
        },
      ]),
    ),
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    // Absolute base URLs so undici's fetch (used in jsdom) can resolve them and
    // MSW node can intercept; both the client and handlers read these.
    env: {
      VITE_STUB_BASE: "http://localhost/api/stub",
      VITE_INGESTOR_BASE: "http://localhost/api/ingestor",
      VITE_RUNTIME_BASE: "http://localhost/api/runtime",
      VITE_REGISTRY_BASE: "http://localhost/api/registry",
      VITE_IDENTITY_BASE: "http://localhost/api/identity",
      VITE_NOTIFICATIONS_BASE: "http://localhost/api/notifications",
    },
  },
});
