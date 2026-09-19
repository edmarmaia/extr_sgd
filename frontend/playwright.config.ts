import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
import { join } from "node:path";

const canary = join(
  process.env.LOCALAPPDATA || "",
  "Microsoft/Edge SxS/Application/msedge.exe",
);
const edgeChannel = existsSync(canary) ? "msedge-canary" : "msedge";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  use: {
    baseURL: "http://127.0.0.1:5178",
    channel: edgeChannel,
    viewport: { width: 1440, height: 1000 },
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5178 --strictPort",
    url: "http://127.0.0.1:5178",
    reuseExistingServer: false,
  },
});
