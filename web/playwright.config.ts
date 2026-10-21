import { defineConfig, devices } from "@playwright/test";

// Runs against the production build served under the GitHub Pages project path (/grid2cloud/).
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 2,
  reporter: [["list"]],
  // C2G_URL=https://hinox13.github.io/grid2cloud/ runs the same checks against a deployed site
  use: { baseURL: process.env.C2G_URL ?? "http://localhost:4173/grid2cloud/", trace: "off" },
  webServer: process.env.C2G_URL ? undefined : { command: "npx vite preview --port 4173 --strictPort", url: "http://localhost:4173/grid2cloud/", reuseExistingServer: true, timeout: 30_000 },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, grepInvert: /@mobile/ },
    { name: "mobile", use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } }, grep: /@mobile/ },
    // opt-in engines: C2G_BROWSERS=firefox,webkit npx playwright test --project firefox
    ...(process.env.C2G_BROWSERS?.includes("firefox")
      ? [
          { name: "firefox", use: { ...devices["Desktop Firefox"], viewport: { width: 1440, height: 900 } }, grepInvert: /@mobile/ },
          { name: "firefox-mobile", use: { browserName: "firefox" as const, viewport: { width: 390, height: 844 }, hasTouch: true }, grep: /@mobile/ },
        ]
      : []),
    ...(process.env.C2G_BROWSERS?.includes("webkit")
      ? [
          { name: "webkit", use: { ...devices["Desktop Safari"], viewport: { width: 1440, height: 900 } }, grepInvert: /@mobile/ },
          { name: "webkit-mobile", use: { ...devices["iPhone 13"], viewport: { width: 390, height: 844 } }, grep: /@mobile/ },
        ]
      : []),
  ],
});
