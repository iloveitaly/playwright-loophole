// Self-contained container integration test: the namespace's non-loopback address
// stands in for the host. No external localias installation is needed.
const { execFileSync, spawn } = require('node:child_process');
const { networkInterfaces } = require('node:os');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const http = require('node:http');
const https = require('node:https');
const assert = require('node:assert/strict');
(async () => {
  const address = Object.values(networkInterfaces()).flat().find(x => x.family === 'IPv4' && !x.internal).address;
  const dir = mkdtempSync('/tmp/loophole-fixture-');
  const cert = `${dir}/root.crt`;
  const key = `${dir}/root.key`;
  execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
    '-keyout', key, '-out', cert, '-subj', '/CN=loophole.localhost',
    '-addext', 'subjectAltName=DNS:loophole.localhost', '-addext', 'basicConstraints=critical,CA:TRUE'], { stdio: 'ignore' });
  let sniSeen = false;
  const handler = (req, res) => {
    assert.equal(req.headers.host, 'loophole.localhost');
    if (req.socket.encrypted) {
      assert.equal(req.socket.servername, 'loophole.localhost');
      sniSeen = true;
    }
    res.end('loophole fixture');
  };
  const servers = [http.createServer(handler), https.createServer({ key: readFileSync(key), cert: readFileSync(cert) }, handler)];
  try {
    await Promise.all(servers.map((s, i) => new Promise(r => s.listen(i ? 443 : 80, address, r))));
    const code = `
      const {execFileSync}=require('node:child_process');
      (async()=>{
        for(const ip of ['127.0.0.1','[::1]']) {
          for(const [scheme,port] of [['http',80],['https',443]]) {
            const body=execFileSync('curl',['--noproxy','*','--fail','--silent','--show-error','--max-time','10','--cacert',process.env.LOOPHOLE_CA_CERT,'--resolve','loophole.localhost:'+port+':'+ip,scheme+'://loophole.localhost'],{encoding:'utf8'});
            if(body!=='loophole fixture') throw Error(body);
          }
        }
        const {chromium}=require('playwright');
        const browser=await chromium.launch();
        try {
          const page=await browser.newPage();
          const response=await page.goto('https://loophole.localhost');
          if(response.status()!==200) throw Error('Navigation failed');
        } finally {await browser.close();}
        console.log('IPv4/IPv6 HTTP, TLS SNI/Host, and Chromium NSS trust passed');
      })().catch(e=>{console.error(e);process.exit(1)});
    `;
    const child = spawn('/usr/local/bin/docker-entrypoint.sh', ['node', '-e', code], {
      env: { ...process.env, LOOPHOLE_ENABLED: '1', LOOPHOLE_TARGET_IP: address, LOOPHOLE_CA_CERT: cert }, stdio: 'inherit',
    });
    const status = await new Promise(r => child.on('exit', r));
    assert.equal(status, 0);
    assert(sniSeen);
  } finally {
    await Promise.all(servers.map(s => new Promise(r => s.close(r))));
    rmSync(dir, { recursive: true, force: true });
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
