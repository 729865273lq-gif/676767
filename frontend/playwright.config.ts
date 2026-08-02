import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://127.0.0.1:3000",
  },
  webServer: {
    command: "node scripts/clean-next-cache.mjs && node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3000",
    reuseExistingServer: !process.env.CI,
    url: "http://127.0.0.1:3000",
  },
});
