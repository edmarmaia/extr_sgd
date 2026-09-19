import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import localConfig from "../config.local.json";

export default defineConfig({
  plugins: [react()],
  base: "./",
  define: {
    __DEPARTMENTS__: JSON.stringify(
      Object.keys(localConfig.schedule_departments),
    ),
  },
});
