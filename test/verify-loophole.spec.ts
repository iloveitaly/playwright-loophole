import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const url = process.env.LOOPHOLE_TEST_URL;

test('managed Chromium policy disables QUIC', async ({ playwright }) => {
  // Full Chromium supports chrome://policy; the legacy headless shell does not.
  const browser = await playwright.chromium.launch({ channel: 'chromium' });
  try {
    const page = await browser.newPage();
    await page.goto('chrome://policy');
    const policy = page.locator('policy-table').locator('policy-row').filter({ hasText: 'QuicAllowed' });
    await expect(policy).toContainText('false');
    await expect(policy).toContainText('OK');
  } finally {
    await browser.close();
  }
});

for (const address of ['127.0.0.1', '[::1]']) {
  test(`TLS relay preserves SNI via ${address}`, async () => {
    test.skip(!url, 'Set LOOPHOLE_TEST_URL to a host-served https://*.localhost URL.');
    const target = new URL(url!);
    expect(target.protocol).toBe('https:');
    const port = target.port || '443';
    // No -k: mounting the CA must permit a verified TLS connection.
    const args = ['--noproxy', '*', '--fail', '--silent', '--show-error', '--max-time', '15'];
    if (process.env.LOOPHOLE_CA_CERT) args.push('--cacert', process.env.LOOPHOLE_CA_CERT);
    args.push('--resolve', `${target.hostname}:${port}:${address}`, target.href);
    execFileSync('curl', args);
  });
}

test('Chromium reaches localias with default TLS verification', async ({ page }) => {
  test.skip(!url, 'Set LOOPHOLE_TEST_URL and mount its root CA.');
  const response = await page.goto(url!);
  expect(response?.ok()).toBeTruthy();
});
