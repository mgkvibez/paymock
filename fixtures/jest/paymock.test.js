// Example: prove your Node handler credits exactly once under duplicates.
// Run against YOUR dev server; this fixture ships with a throwaway receiver
// so the example is self-contained for CI.
const http = require('http');
const paymock = require('./paymockFixture');

describe('paymock duplicate webhooks', () => {
  let receiver, credits, received;

  beforeAll((done) => {
    credits = {}; received = [];
    const server = http.createServer((req, res) => {
      let body = '';
      req.on('data', (c) => { body += c; });
      req.on('end', () => {
        const event = JSON.parse(body);
        const ref = event.data.reference;
        credits[ref] = (credits[ref] || 0) === 0 ? 1 : credits[ref]; // credit once
        received.push(event);
        res.writeHead(200); res.end();
      });
    });
    receiver = server.listen(0, '127.0.0.1', () => done());
  });

  afterAll((done) => receiver.close(() => done()));

  test('3 deliveries, exactly 1 credit', async () => {
    const url = `http://127.0.0.1:${receiver.address().port}/webhook`;
    const report = await paymock.duplicate(url, {
      reference: 'T-JEST-DEMO', amount: 50000, currency: 'NGN', gateway: 'paystack',
    });
    expect(report.duplicates).toBe(2);
    expect(received.length).toBe(3);
    expect(credits['T-JEST-DEMO']).toBe(1);
  });
});
