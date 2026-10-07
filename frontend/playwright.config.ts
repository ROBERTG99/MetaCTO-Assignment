// Golden paths against the seeded app in offline mode (no API key, no network): `make e2e`.
// Playwright starts a fresh API on :8001 with its own database (backend/data/e2e.db, reseeded every run from
// the recorded Haiku snapshot) and the in-process worker, plus the web app on :5174. Dev servers on :8000 and
// :5173 are left alone. The specs share that database, so they run one at a time.
import { defineConfig, devices } from '@playwright/test'

const API_PORT = 8001
const WEB_PORT = 5174
export const API_URL = `http://127.0.0.1:${API_PORT}`
// `make e2e-live` sets this to live for a paid validation run; CI and `make e2e` stay offline.
export const AI_MODE = process.env.E2E_AI_MODE === 'live' ? 'live' : 'offline'

const backend = [
  'cd ../backend',
  'mkdir -p data',
  // a live run keeps its own database, so an offline run never overwrites the live ai_runs
  `export DATABASE_URL=sqlite:///./data/${AI_MODE === 'live' ? 'e2e-live' : 'e2e'}.db AI_MODE=${AI_MODE} APP_ENV=test HF_HUB_OFFLINE=1`,
  'uv run python -m seed.load',
  `uv run uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT} --no-access-log`,
].join(' && ')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    actionTimeout: 10_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    { command: backend, url: `${API_URL}/requesters`, reuseExistingServer: false, timeout: 180_000, stdout: 'pipe' },
    {
      command: 'npm run dev',
      env: { API_URL, WEB_PORT: String(WEB_PORT) },
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
    },
  ],
})
