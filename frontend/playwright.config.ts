import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 60000,
  use: {
    baseURL: "http://127.0.0.1:8788",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
  },
  webServer: {
    command:
      process.platform === "win32"
        ? "..\\.venv\\Scripts\\python.exe ..\\scripts\\browser-test-server.py"
        : "python ../scripts/browser-test-server.py",
    url: "http://127.0.0.1:8788/api/health",
    reuseExistingServer: false,
    timeout: 20000,
  },
});
