import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const API = process.env.API_URL ?? "http://127.0.0.1:8000";
const proxied = ["/v1", "/auth", "/api-keys", "/health", "/docs", "/redoc", "/openapi.json"];

export default defineConfig({
  plugins: [react()],
  server: { proxy: Object.fromEntries(proxied.map((path) => [path, API])) },
  build: { outDir: "dist", sourcemap: true },
  // Component tests choose jsdom per file (`// @vitest-environment jsdom`); src/test/api.ts fakes the API for them.
  test: { include: ["src/**/*.test.{ts,tsx}"], environment: "node", setupFiles: ["src/test/api.ts"] },
});
