/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: { outDir: "../src/burpweb/static", emptyOutDir: true },
  server: { proxy: { "/api": { target: "http://127.0.0.1:8765", ws: true } } },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
