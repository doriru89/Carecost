import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  // GitHub Pages serves the site under /<repo>/; VITE_BASE sets it at build time (default "/").
  base: process.env.VITE_BASE || "/",
  server: {
    // Stream D runs on 5180 (8080 is the legacy dev server). VITE_PORT overrides.
    host: "127.0.0.1",
    port: Number(process.env.VITE_PORT || 5180),
    strictPort: true,
    // mock mode imports contracts/fixtures and data/redflags from the repo root
    fs: { allow: [path.resolve(__dirname, "..")] },
    hmr: {
      overlay: true,
    },
    proxy: {
      // the merged backend (app.server) runs on 8100; 8000 is the legacy server
      "/api": {
        target: `http://127.0.0.1:${process.env.VITE_API_PORT || '8100'}`,
        changeOrigin: true,
      },
    },
  },
  // maplibre-gl 6 starts its worker from ./maplibre-gl-worker.mjs next to its own module; the dep
  // pre-bundler moves the module and breaks that path, so serve it from node_modules as is.
  optimizeDeps: { exclude: ["maplibre-gl"] },
  worker: { format: "es" },
  plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
    dedupe: ["react", "react-dom", "react/jsx-runtime", "react/jsx-dev-runtime"],
  },
}));
