const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const script = resolve(__dirname, '../docker-entrypoint.sh');
function run(env, command = ['sh', '-c', 'exit 23']) {
  const home = mkdtempSync(join(tmpdir(), 'loophole-test-'));
  try {
    return spawnSync('sh', [script, ...command], {
      env: { ...process.env, HOME: home, LOOPHOLE_CA_CERT: join(home, 'absent'), ...env },
      encoding: 'utf8',
    });
  } finally { rmSync(home, { recursive: true, force: true }); }
}
test('disabled relay preserves command exit status', () => {
  const result = run({ LOOPHOLE_ENABLED: '0' });
  assert.equal(result.status, 23);
  assert.match(result.stdout, /skipping/);
});
test('loopback override bypasses relay', () => {
  for (const ip of ['127.0.0.1', '127.42.0.1', '::1']) {
    assert.equal(run({ LOOPHOLE_TARGET_IP: ip }).status, 23);
  }
});
test('rejects configuration injection and malformed addresses before launch', () => {
  const result = run({ LOOPHOLE_TARGET_IP: '192.0.2.1\nfrontend injected' });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Invalid host IP/);
});
test('rejects invalid or conflicting ports', () => {
  for (const port of ['0', '65536', '443', '80\nmalicious', '-1']) {
    const result = run({ LOOPHOLE_HTTP_PORT: port, LOOPHOLE_TARGET_IP: '192.0.2.1' });
    assert.equal(result.status, 1);
  }
});
