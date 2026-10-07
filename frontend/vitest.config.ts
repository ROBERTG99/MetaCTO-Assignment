// Unit tests for pure frontend logic (src/**/*.test.ts). The Playwright specs in e2e/ run with `make e2e`.
import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config.ts'

export default mergeConfig(viteConfig, defineConfig({ test: { include: ['src/**/*.test.ts'], environment: 'node' } }))
