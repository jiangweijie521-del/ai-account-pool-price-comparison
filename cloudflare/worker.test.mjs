import test from "node:test";
import assert from "node:assert/strict";

import * as worker from "./worker.mjs";

function createUpstreamFixture() {
  let calls = 0;
  const row = {
    name: "Plus 已接码",
    goods_key: "ITEM1",
    price: "12.50",
    category: { name: "PLUS" },
    extend: { stock_count: "2" },
    link: "https://pay.ldxp.cn/item/ITEM1",
  };
  return {
    count: () => calls,
    fetch: async (url, options) => {
      calls += 1;
      const path = new URL(url).pathname;
      const body = JSON.parse(options.body);
      if (path.endsWith("/info")) {
        return Response.json({ code: 1, data: { nickname: "远端测试店", goods_count: 1 } });
      }
      const rows = body.goods_type === "card" ? [row] : [];
      return Response.json({ code: 1, data: { list: rows, total: rows.length } });
    },
  };
}

function createMemoryCache() {
  const entries = new Map();
  return {
    async match(request) {
      return entries.get(request.url)?.clone();
    },
    async put(request, response) {
      entries.set(request.url, response.clone());
    },
  };
}

test("classify preserves the existing product grouping contract", () => {
  const cases = [
    [["【Chat GP-T Free号】已绑手机，可用Codex", "gpt低价"], "GPT Free"],
    [["低价 Plus成品号（登录codex要接码）", "PLUS"], "GPT Plus · 未接码"],
    [["Plus 已接码成品号", "PLUS"], "GPT Plus · 已接码"],
    [["Codex 接码 美国实体卡", "接码服务"], "Codex 接码"],
    [["Gemini Pro 12个月", "Gemini"], "Gemini"],
    [["iCloud邮箱", "plus手搓商品"], "iCloud 邮箱"],
    [["【正规货付】Super Grok 12个月", "K12"], "Grok"],
    [["一键部署本地中转站", "K12", "resource"], "资源 · K12"],
    [["【教程】未接码plus gpt号接码并导入教程", "GPT"], "教程 · GPT"],
    [["美国实体卡长效接码codex绑定注册通用 PLUS接码", "接码"], "Codex 接码"],
    [["Codex Free(Gmail注册)", "Gpt Free"], "GPT Free"],
  ];

  for (const [args, expected] of cases) {
    assert.equal(worker.classify(...args), expected);
  }
});

test("transformItem rejects unsafe fields and emits the browser payload", () => {
  assert.equal(typeof worker.transformItem, "function");

  const item = worker.transformItem(
    {
      name: "<b>Plus 已接码</b> &amp; 可用",
      goods_key: "ABC123",
      price: "12.50",
      category: { name: "PLUS" },
      extend: { stock_count: "3" },
      link: "https://attacker.example/steal",
    },
    { name: "测试店", token: "SHOP1", url: "https://pay.ldxp.cn/shop/SHOP1" },
    "card",
  );

  assert.deepEqual(
    {
      name: item.name,
      price: item.price,
      stock: item.stock,
      available: item.available,
      group: item.group,
      link: item.link,
      canonical: item.canonical,
    },
    {
      name: "Plus 已接码 & 可用",
      price: 12.5,
      stock: 3,
      available: true,
      group: "GPT Plus · 已接码",
      link: "https://pay.ldxp.cn/item/ABC123",
      canonical: "plus已接码可用",
    },
  );
});

test("collectInventory aggregates a complete upstream shop response", async () => {
  assert.equal(typeof worker.collectInventory, "function");
  const calls = [];
  const shop = { name: "测试店", token: "SHOP1", url: "https://pay.ldxp.cn/shop/SHOP1" };
  const fetchFixture = async (url, options) => {
    const body = JSON.parse(options.body);
    calls.push({ path: new URL(url).pathname, body });
    if (new URL(url).pathname.endsWith("/info")) {
      return Response.json({ code: 1, data: { nickname: "远端测试店", goods_count: 2 } });
    }
    const rows = body.goods_type === "card"
      ? [
          {
            name: "Plus 已接码",
            goods_key: "ITEM1",
            price: "12.50",
            category: { name: "PLUS" },
            extend: { stock_count: "2" },
            link: "https://pay.ldxp.cn/item/ITEM1",
          },
          {
            name: "Codex Free",
            goods_key: "ITEM2",
            price: "2.00",
            category: { name: "GPT Free" },
            extend: { stock_count: "0" },
            link: "https://pay.ldxp.cn/item/ITEM2",
          },
        ]
      : [];
    return Response.json({ code: 1, data: { list: rows, total: rows.length } });
  };

  const payload = await worker.collectInventory(fetchFixture, [shop]);

  assert.deepEqual(payload.summary, {
    total: 2,
    available: 1,
    out_of_stock: 1,
    groups: 2,
    shops_fresh: 1,
    shops_stale: 0,
    shops_total: 1,
  });
  assert.equal(payload.ok, true);
  assert.equal(payload.partial, false);
  assert.equal(payload.shops[0].nickname, "远端测试店");
  assert.equal(payload.items[0].group, "GPT Free");
  assert.equal(calls.length, 5);
});

test("sortItems keeps available products before unavailable products in a group", () => {
  assert.equal(typeof worker.sortItems, "function");
  const items = [
    { group_rank: 1, group: "GPT Plus", available: false, price: 1, shop: "甲" },
    { group_rank: 1, group: "GPT Plus", available: true, price: 2, shop: "乙" },
  ];

  worker.sortItems(items);

  assert.equal(items[0].available, true);
});

test("handleRequest exposes a production health endpoint", async () => {
  assert.equal(typeof worker.handleRequest, "function");

  const response = await worker.handleRequest(new Request("https://stock.example/api/health"), {}, {});

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, service: "stock-comparison", version: "2026-08-04.1" });
});

test("handleRequest reuses the shared inventory cache", async () => {
  const upstream = createUpstreamFixture();
  const cache = createMemoryCache();
  const shop = { name: "测试店", token: "SHOP1", url: "https://pay.ldxp.cn/shop/SHOP1" };
  const pending = [];
  const context = { waitUntil: (promise) => pending.push(promise) };
  const dependencies = { fetchImpl: upstream.fetch, cache, shopsConfig: [shop] };

  const first = await worker.handleRequest(new Request("https://stock.example/api/inventory"), {}, context, dependencies);
  await Promise.all(pending);
  const second = await worker.handleRequest(new Request("https://stock.example/api/inventory"), {}, context, dependencies);

  assert.equal(first.status, 200);
  assert.equal(first.headers.get("X-Inventory-Cache"), "MISS");
  assert.equal(second.headers.get("X-Inventory-Cache"), "HIT");
  assert.equal((await second.json()).summary.total, 1);
  assert.equal(upstream.count(), 5);
});

test("handleRequest keeps manual refreshes inside the shared cache window", async () => {
  const upstream = createUpstreamFixture();
  const cache = createMemoryCache();
  const shop = { name: "测试店", token: "SHOP1", url: "https://pay.ldxp.cn/shop/SHOP1" };
  const pending = [];
  const context = { waitUntil: (promise) => pending.push(promise) };
  const dependencies = { fetchImpl: upstream.fetch, cache, shopsConfig: [shop] };

  await worker.handleRequest(new Request("https://stock.example/api/inventory"), {}, context, dependencies);
  await Promise.all(pending);
  const response = await worker.handleRequest(new Request("https://stock.example/api/inventory?refresh=1"), {}, context, dependencies);

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Inventory-Cache"), "HIT");
  assert.equal(upstream.count(), 5);
});

test("handleRequest serves static assets with production security headers", async () => {
  const env = {
    ASSETS: {
      fetch: async () => new Response("<!doctype html><title>库存比价台</title>", {
        headers: { "Content-Type": "text/html; charset=utf-8" },
      }),
    },
  };

  const response = await worker.handleRequest(new Request("https://stock.example/"), env, {});

  assert.equal(response.status, 200);
  assert.match(await response.text(), /库存比价台/);
  assert.equal(response.headers.get("X-Content-Type-Options"), "nosniff");
  assert.match(response.headers.get("Content-Security-Policy"), /default-src 'self'/);
});
