import { defineConfig } from "@playwright/test";

const port = process.env.PLAYWRIGHT_PORT ?? "3000";
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL,
  },
  webServer: {
    command: `node scripts/clean-next-cache.mjs && node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port ${port}`,
    reuseExistingServer: !process.env.CI,
    url: baseURL,
  },
});
