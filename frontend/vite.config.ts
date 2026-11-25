import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // In development every /api request is proxied to FastAPI, so the browser
  // talks to a single origin and no CORS round-trips are needed.
  // 127.0.0.1 rather than "localhost": Node may resolve localhost to IPv6 (::1)
  // while uvicorn listens on IPv4 only.
  const backendUrl = env.VITE_BACKEND_URL || "http://127.0.0.1:8000";

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        "/api": { target: backendUrl, changeOrigin: true },
      },
    },
  };
});
