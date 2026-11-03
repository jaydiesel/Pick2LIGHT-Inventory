import { defineConfig } from '@playwright/test'

const port = Number(process.env.P2L_E2E_PORT ?? 8765)
const executablePath = process.env.PW_CHROMIUM_PATH || undefined

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
    testIdAttribute: 'data-test',
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [
    { name: 'setup', testMatch: /setup\.spec\.ts/ },
    { name: 'app', testIgnore: /setup\.spec\.ts/, dependencies: ['setup'], use: { storageState: 'e2e/.auth/state.json' } },
  ],
  webServer: {
    command: './e2e/start-server.sh',
    url: `http://127.0.0.1:${port}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'pipe',
  },
})
