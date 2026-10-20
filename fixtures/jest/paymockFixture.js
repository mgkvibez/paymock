// Jest fixture: fire paymock scenarios at your running dev server.
// Usage (in your Jest test):
//   const paymock = require('./paymockFixture');
//   const report = await paymock.duplicate('http://localhost:3000/webhook', {
//     reference: 'T-JEST-1', amount: 50000, currency: 'NGN', gateway: 'paystack',
//   });
//   expect(report.duplicates).toBe(2);
//   // then assert your API/DB credited exactly once.

const { spawn } = require('child_process');
const https = require('https');
const http = require('http');

function post(url, body, headers) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const data = JSON.stringify(body);
    const req = mod.request(url, { method: 'POST', headers }, (res) => {
      res.resume();
      resolve({ status: res.statusCode });
    });
    req.on('error', reject);
    req.end(data);
  });
}

function paymockCLI(args) {
  return new Promise((resolve, reject) => {
    const proc = spawn('paymock', args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    proc.stdout.on('data', (d) => { out += d; });
    proc.stderr.on('data', (d) => { out += d; });
    proc.on('close', (code) => {
      try { resolve(JSON.parse(out)); }
      catch { reject(new Error(`paymock CLI exited ${code}: ${out}`)); }
    });
  });
}

async function duplicate(targetUrl, txn) {
  return paymockCLI([
    'deliver', '--scenario', 'duplicate', '--url', targetUrl,
    '--gateway', txn.gateway || 'paystack',
    '--reference', txn.reference, '--amount', String(txn.amount),
    '--currency', txn.currency || 'NGN', '--email', txn.email || 'jest@test.dev',
    '--copies', String(txn.copies || 3),
  ]);
}

async function outOfOrder(targetUrl, txn) {
  return paymockCLI([
    'deliver', '--scenario', 'out_of_order', '--url', targetUrl,
    '--gateway', txn.gateway || 'paystack',
    '--reference', txn.reference, '--amount', String(txn.amount),
    '--currency', txn.currency || 'NGN', '--email', txn.email || 'jest@test.dev',
  ]);
}

async function failed(targetUrl, txn) {
  return paymockCLI([
    'deliver', '--scenario', 'failed', '--url', targetUrl,
    '--gateway', txn.gateway || 'paystack',
    '--reference', txn.reference, '--amount', String(txn.amount),
    '--currency', txn.currency || 'NGN', '--email', txn.email || 'jest@test.dev',
    '--time-scale', String(txn.timeScale || 0.001),
  ]);
}

module.exports = { duplicate, outOfOrder, failed, post };
