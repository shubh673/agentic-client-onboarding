import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        ws: true,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("error", (err) => {
            // ECONNABORTED/ECONNRESET happen when a client closes a WS mid-write — harmless in dev
            const code = (err as NodeJS.ErrnoException).code ?? "";
            if (["ECONNABORTED", "ECONNRESET", "EPIPE"].includes(code)) return;
            console.error("[proxy error]", err);
          });
        },
      },
    },
  },
});
