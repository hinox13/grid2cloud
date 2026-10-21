import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// GitHub Pages serves a project site under /<repo>/. The app uses a hash router, so every route is
// served by index.html and a refresh never 404s. C2G_BASE=/ for a root deployment.
export default defineConfig({
  base: process.env.C2G_BASE ?? "/grid2cloud/",
  plugins: [react()],
  build: { target: "es2022", sourcemap: false, chunkSizeWarningLimit: 300 },
  preview: { port: 4173, strictPort: true },
});
