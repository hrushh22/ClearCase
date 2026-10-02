import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  // relative asset paths: the same build works at / (local, Space) and at /<repo>/ (GitHub Pages)
  base: "./",
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/.well-known": "http://localhost:8000",
      "/auth": "http://localhost:8000",
    },
  },
});
