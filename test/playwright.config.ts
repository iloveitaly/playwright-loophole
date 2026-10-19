import { defineConfig } from '@playwright/test';
export default defineConfig({
  testMatch: '**/*.spec.ts',
  outputDir: '/tmp/loophole-test-results',
  workers: 1,
});
