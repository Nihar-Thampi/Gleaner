import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  server: {
    port: 5173,
    // Bind IPv4 and IPv6 so "localhost" works whichever one the browser resolves to.
    host: true,
    // In Docker the source is a bind mount from Windows or macOS, which sends no file events
    // into the container, so the dev server polls for changes instead (VITE_POLL is set there).
    watch: process.env.VITE_POLL ? { usePolling: true, interval: 300 } : undefined,
    proxy: {
      // 127.0.0.1, not localhost: on macOS, localhost may resolve to IPv6 first.
      // Set API_URL to point at a backend on another port.
      ...Object.fromEntries(
        // The API plus the backend's own pages: OpenAPI docs, the crawler info page and the practice store.
        ["/api", "/docs", "/openapi.json", "/bot", "/practice"].map((path) => [
          path,
          { target: process.env.API_URL ?? "http://127.0.0.1:8000", changeOrigin: true, xfwd: true },
        ])
      ),
    },
  },
})
