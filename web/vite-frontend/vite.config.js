import { defineConfig } from "vite";

// ADK's _OriginCheckMiddleware blocks non-safe HTTP methods (POST/DELETE/…)
// when the Origin header doesn't match the server's own host. Vite forwards
// the browser's Origin (e.g. http://localhost:5173) unchanged, which ADK
// rejects. Stripping the header makes the proxy behave like Python requests
// (no Origin → ADK skips the check entirely).
function stripOrigin(proxy) {
  proxy.on("proxyReq", (proxyReq) => {
    proxyReq.removeHeader("origin");
  });
}

export default defineConfig({
  server: {
    proxy: {
      "/api": "http://localhost:8001",
      "/run_sse": {
        target: "http://localhost:8000",
        changeOrigin: true,
        configure: stripOrigin,
      },
      "/apps": {
        target: "http://localhost:8000",
        changeOrigin: true,
        configure: stripOrigin,
      },
      "/list-apps": {
        target: "http://localhost:8000",
        changeOrigin: true,
        configure: stripOrigin,
      },
    },
  },
});
