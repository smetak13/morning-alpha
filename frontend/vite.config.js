import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";
const root = fileURLToPath(new URL(".", import.meta.url));
const publicDir = fileURLToPath(new URL("../assets", import.meta.url));

export default defineConfig({
  root,
  publicDir,
  plugins: [react()],
  build: {
    assetsDir: "static",
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/health": apiTarget,
      "/login": apiTarget,
      "/logout": apiTarget,
      "/me": apiTarget,
      "/register": apiTarget,
    },
  },
});
