import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // In local dev the API runs on :8000; proxying keeps requests same-origin.
    proxy: { "/api": "http://localhost:8000" },
  },
  build: {
    rollupOptions: {
      // Vendor code changes rarely; separate chunks keep it cached across deploys.
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          return /[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id) ? "react" : "charts";
        },
      },
    },
  },
  test: {
    environment: "node",
  },
});
