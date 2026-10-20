/**
 * paymock Jest helper — test webhook handling in Node without a real gateway.
 *
 * Requires paymock running (default http://localhost:9090, override with
 * PAYMOCK_URL). Node 18+ (global fetch).
 *
 *   const { Paymock, webhookCollector } = require("./jest/paymock.js");
 *
 *   let app, collector;
 *   beforeAll(async () => {
 *     collector = webhookCollector(yourExpressApp);   // POST /test-webhooks
 *     const paymock = new Paymock();
 *     await paymock.register("paystack", collector.url);
 *     const { reference } = await paymock.initialize("paystack", 50000);
 *     await paymock.settle("paystack", reference, "success", "duplicate");
 *   });
 *   test("no double credit", async () => {
 *     await collector.waitFor(2);
 *     const refs = collector.events("charge.success")
 *       .map((e) => e.data.reference);
 *     expect(new Set(refs).size).toBe(1);       // same order, delivered twice
 *     expect(yourCreditCount(refs[0])).toBe(1); // credited once, not twice
 *   });
 */
class Paymock {
  constructor(baseUrl = process.env.PAYMOCK_URL || "http://localhost:9090") {
    this.base = baseUrl.replace(/\/$/, "");
  }

  async _call(method, path, body) {
    const res = await fetch(this.base + path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}: ${JSON.stringify(json)}`);
    return json;
  }

  async initialize(gateway = "paystack", amount = 50000, email = "jest@paymock.dev") {
    if (gateway === "paystack") {
      const out = await this._call("POST", "/paystack/transaction/initialize", { email, amount });
      return { reference: out.data.reference };
    }
    const tx_ref = `jest-${Date.now()}`;
    await this._call("POST", "/flutterwave/v3/payments", { tx_ref, amount: amount / 100 });
    return { reference: tx_ref };
  }

  async settle(gateway, reference, status = "success", scenario = "none", delaySeconds = 30) {
    return this._call("POST", `/${gateway}/_settle/${reference}`,
      { status, scenario, delay_seconds: delaySeconds });
  }

  async register(gateway, url, schedule) {
    return this._call("POST", `/${gateway}/_webhooks/register`,
      schedule ? { url, schedule } : { url });
  }

  async deliveries(gateway) {
    const out = await this._call("GET", `/${gateway}/_webhooks/deliveries`);
    return out.deliveries;
  }
}

/**
 * Attach a webhook collector to YOUR express app (or any http.Server handler
 * using req/res). Requests are recorded and replayable.
 */
function webhookCollector(expressApp, path = "/test-webhooks") {
  const requests = [];
  expressApp.post(path, (req, res) => { requests.push(req.body); res.sendStatus(200); });
  return {
    url: `${process.env.TEST_BASE_URL || "http://localhost:3000"}${path}`,
    events: (event) => requests.filter((r) => r && r.event === event),
    all: () => requests.slice(),
    count: () => requests.length,
    async waitFor(n, timeoutMs = 10000) {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        if (requests.length >= n) return;
        await new Promise((r) => setTimeout(r, 20));
      }
      if (requests.length < n) throw new Error(`timed out: ${requests.length}/${n} webhooks`);
    },
  };
}

module.exports = { Paymock, webhookCollector };
