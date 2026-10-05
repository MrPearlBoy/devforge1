import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/**
 * The dev server proxies `/api` to the FastAPI backend so the browser only ever talks to
 * one origin (no CORS surprises, and the app works behind a preview/sandbox host).
 */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    strictPort: false,
    // sandbox/preview hosts are dynamic, so allow any host in development
    allowedHosts: true,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://127.0.0.1:8001",
        changeOrigin: true,
        ws: false,
      },
    },
  },
  preview: { host: true, port: 4173, allowedHosts: true },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
});
