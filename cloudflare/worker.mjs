const TYPE_LABELS = { card: "卡密", article: "文章", resource: "资源", equity: "权益" };
const API_ROOT = "https://pay.ldxp.cn";
const REFRESH_SECONDS = 300;
const MANUAL_REFRESH_COOLDOWN_MS = 30_000;
const PAGE_SIZE = 200;
const MAX_PAGES = 2;
const GOODS_TYPES = ["card", "article", "resource", "equity"];
const SHOPS = [
  { name: "硬核HENRY", token: "VAELFLP1", url: `${API_ROOT}/shop/VAELFLP1` },
  { name: "GPT2026", token: "GH2RA4MP", url: `${API_ROOT}/shop/GH2RA4MP` },
  { name: "昆仑081", token: "JNHUK2WC", url: `${API_ROOT}/shop/JNHUK2WC` },
  { name: "codex嘻嘻", token: "BH4F39F6", url: `${API_ROOT}/shop/BH4F39F6` },
];
const LAST_GOOD = new Map();
let inventoryRefreshPromise = null;
const GROUP_ORDER = [
  "GPT Free",
  "GPT Plus · 已接码",
  "GPT Plus · 未接码",
  "GPT Plus · 成品号",
  "GPT Plus · 代充",
  "Codex 接码",
  "OpenAI K12",
  "OpenAI Team",
  "GPT Pro",
  "Gemini",
  "Claude",
  "Grok",
  "iCloud 邮箱",
  "Outlook 邮箱",
  "Gmail 邮箱",
  "Telegram",
];

function decodeEntities(value) {
  return value
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#(?:39|x27);/gi, "'")
    .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
    .replace(/&#x([\da-f]+);/gi, (_, code) => String.fromCodePoint(Number.parseInt(code, 16)));
}

export function cleanText(value) {
  return decodeEntities(String(value ?? ""))
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizedText(...parts) {
  let text = parts.map(cleanText).join(" ").toLocaleLowerCase("zh-CN");
  for (const [source, target] of [
    ["chat gp-t", "chatgpt"],
    ["chat gpt", "chatgpt"],
    ["open ai", "openai"],
    ["gptplus", "gpt plus"],
    ["icloud", "icloud"],
    ["cloude", "cloud"],
  ]) {
    text = text.replaceAll(source, target);
  }
  return text.replace(/\s+/g, " ").trim();
}

export function classify(name, category, goodsType = "card") {
  const nameText = normalizedText(name);
  const categoryText = normalizedText(category);
  const text = normalizedText(name, category);

  if (goodsType !== "card") {
    return `${TYPE_LABELS[goodsType] || "资料"} · ${cleanText(category) || "未分类"}`.slice(0, 28);
  }
  if (["教程", "使用指南", "部署说明"].some((term) => nameText.includes(term))) {
    return `教程 · ${cleanText(category) || "未分类"}`.slice(0, 28);
  }
  if ((text.includes("gpt") || text.includes("openai")) && /\bpro\b|pro\s*(?:5|20)x/.test(text)) return "GPT Pro";
  if (nameText.includes("gemini") || nameText.includes("反重力")) return "Gemini";
  if (nameText.includes("claude")) return "Claude";
  if (nameText.includes("grok")) return "Grok";
  if (text.includes("free") && ["gpt", "openai", "codex"].some((term) => text.includes(term))) return "GPT Free";

  const codexService = nameText.includes("codex") && ["接码", "手机验证", "实体卡"].some((term) => nameText.includes(term));
  const accountProduct = ["成品号", "账号", "会员", "月卡", "周额度"].some((term) => nameText.includes(term));
  if (codexService && !accountProduct) return "Codex 接码";

  const nameHasPlus = nameText.includes("plus") || nameText.includes("gpt+");
  if (!nameHasPlus) {
    if (nameText.includes("icloud")) return "iCloud 邮箱";
    if (["outlook", "微软邮箱", "hotmail"].some((term) => nameText.includes(term))) return "Outlook 邮箱";
    if (["gmail", "谷歌邮箱"].some((term) => nameText.includes(term))) return "Gmail 邮箱";
  }

  if (nameHasPlus || categoryText.includes("plus") || categoryText.includes("gpt+")) {
    if (["代充", "充值", "开通", "自助充"].some((term) => nameText.includes(term))) return "GPT Plus · 代充";
    if (["未接码", "没有接码", "没绑定手机", "未绑手机", "要接码", "需要接码", "只能登录网页版", "只能用网页", "半成品"].some((term) => text.includes(term))) {
      return "GPT Plus · 未接码";
    }
    if (["已接码", "已绑手机", "已绑定手机"].some((term) => text.includes(term))) return "GPT Plus · 已接码";
    return "GPT Plus · 成品号";
  }

  if (text.includes("openai普通账号") || (text.includes("白号") && ["gpt", "openai", "codex"].some((term) => text.includes(term)))) return "GPT Free";
  if (text.includes("codex") && ["接码", "手机验证", "实体卡"].some((term) => text.includes(term))) return "Codex 接码";
  if (nameText.includes("team") || nameText.includes("团队") || categoryText.includes("team")) return "OpenAI Team";
  if (nameText.includes("k12") || categoryText.includes("k12")) return "OpenAI K12";
  if (categoryText.includes("gemini") || categoryText.includes("反重力")) return "Gemini";
  if (categoryText.includes("claude")) return "Claude";
  if (categoryText.includes("grok")) return "Grok";
  if (["telegram", "电报", "飞机", "gram 账号", "tg/"].some((term) => text.includes(term))) return "Telegram";
  if (text.includes("icloud")) return "iCloud 邮箱";
  if (["outlook", "微软邮箱", "hotmail"].some((term) => text.includes(term))) return "Outlook 邮箱";
  if (["gmail", "谷歌邮箱"].some((term) => text.includes(term))) return "Gmail 邮箱";
  if (text.includes("接码")) return "其他接码服务";
  return (cleanText(category) || TYPE_LABELS[goodsType] || "其他商品").slice(0, 28);
}

function canonicalName(name) {
  return normalizedText(name).replace(/[^\p{L}\p{N}]+/gu, "");
}

function groupRank(group) {
  const rank = GROUP_ORDER.indexOf(group);
  return rank === -1 ? GROUP_ORDER.length : rank;
}

function extractTags(name, goodsType) {
  const text = normalizedText(name);
  const tags = [];
  if (["未接码", "要接码", "需要接码", "没绑定手机", "未绑手机"].some((term) => text.includes(term))) {
    tags.push("未接码");
  } else if (["已接码", "已绑手机", "已绑定手机"].some((term) => text.includes(term))) {
    tags.push("已接码");
  }

  if (text.includes("质保")) {
    const match = text.match(/质保\s*(\d+\s*(?:天|小时|分钟)|首登|首次登录|首次登陆)/);
    tags.push(match ? `质保${match[1].replace(/\s+/g, "")}` : "含质保");
  }
  if (["只能登录网页版", "只能用网页", "网页版本"].some((term) => text.includes(term))) {
    tags.push("仅网页");
  } else if (text.includes("反代")) {
    tags.push("含反代说明");
  }
  if (goodsType !== "card") tags.push(TYPE_LABELS[goodsType] || goodsType);
  return tags.slice(0, 3);
}

function safeProductLink(value, goodsKey) {
  const link = cleanText(value);
  const prefix = `${API_ROOT}/item/`;
  if (link.startsWith(prefix) && /^[A-Za-z0-9]+$/.test(link.slice(prefix.length))) return link;
  if (/^[A-Za-z0-9]+$/.test(goodsKey)) return `${prefix}${goodsKey}`;
  return API_ROOT;
}

export function transformItem(raw, shop, goodsType) {
  const name = cleanText(raw?.name);
  const goodsKey = cleanText(raw?.goods_key);
  const price = Number(raw?.price);
  if (!name || !goodsKey || !Number.isFinite(price) || price < 0) return null;

  const category = cleanText(raw?.category?.name) || "未分类";
  const stockValue = raw?.extend?.stock_count;
  const parsedStock = stockValue == null ? null : Number.parseInt(stockValue, 10);
  const stock = Number.isFinite(parsedStock) ? Math.max(0, parsedStock) : null;
  const available = stock === null ? goodsType !== "card" : stock > 0;
  const group = classify(name, category, goodsType);

  return {
    key: goodsKey,
    name,
    price,
    stock,
    available,
    category,
    group,
    group_rank: groupRank(group),
    goods_type: goodsType,
    goods_type_label: TYPE_LABELS[goodsType] || goodsType,
    shop: shop.name,
    shop_token: shop.token,
    shop_url: shop.url,
    link: safeProductLink(raw?.link, goodsKey),
    tags: extractTags(name, goodsType),
    canonical: canonicalName(name),
  };
}

async function apiPost(fetchImpl, path, payload, token) {
  const response = await fetchImpl(`${API_ROOT}${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json; charset=utf-8",
      Referer: `${API_ROOT}/shop/${token}`,
      "User-Agent": "InventoryComparator/2.0 (+cloudflare worker)",
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const result = await response.json();
  if (!result || typeof result !== "object" || result.code !== 1) throw new Error("远端接口返回失败");
  return result;
}

async function fetchGoodsType(fetchImpl, shop, goodsType) {
  const items = [];
  let received = 0;
  // ponytail: two 200-item pages keep the Worker below the free-plan subrequest ceiling.
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const result = await apiPost(fetchImpl, "/shopApi/Shop/goodsList", {
      token: shop.token,
      keywords: "",
      category_id: 0,
      goods_type: goodsType,
      current: page,
      pageSize: PAGE_SIZE,
    }, shop.token);
    const data = result.data && typeof result.data === "object" ? result.data : {};
    const rows = Array.isArray(data.list) ? data.list : [];
    received += rows.length;
    for (const row of rows) {
      const item = row && typeof row === "object" ? transformItem(row, shop, goodsType) : null;
      if (item) items.push(item);
    }
    const total = Number.isFinite(Number(data.total)) ? Number(data.total) : received;
    if (!rows.length || rows.length < PAGE_SIZE || received >= total) break;
  }
  return items;
}

async function fetchShop(fetchImpl, shop) {
  const infoReply = await apiPost(fetchImpl, "/shopApi/Shop/info", { token: shop.token }, shop.token);
  const info = infoReply.data && typeof infoReply.data === "object" ? infoReply.data : {};
  const items = [];
  const seen = new Set();
  for (const goodsType of GOODS_TYPES) {
    for (const item of await fetchGoodsType(fetchImpl, shop, goodsType)) {
      const identity = `${item.shop_token}:${item.key}`;
      if (!seen.has(identity)) {
        seen.add(identity);
        items.push(item);
      }
    }
  }
  const fetchedAt = new Date().toISOString();
  for (const item of items) Object.assign(item, { stale: false, fetched_at: fetchedAt });
  return {
    name: shop.name,
    nickname: cleanText(info.nickname) || shop.name,
    token: shop.token,
    url: shop.url,
    ok: true,
    stale: false,
    message: "读取成功",
    fetched_at: fetchedAt,
    declared_count: Number(info.goods_count) || 0,
    item_count: items.length,
    items,
  };
}

function failureMessage(error) {
  if (error instanceof DOMException && error.name === "TimeoutError") return "网络连接超时或中断";
  if (String(error?.message || "").startsWith("HTTP ")) return `远端返回 ${error.message}`;
  return "读取失败";
}

export function sortItems(items) {
  return items.sort((left, right) => left.group_rank - right.group_rank
    || left.group.localeCompare(right.group, "zh-CN")
    || Number(Boolean(left.stale)) - Number(Boolean(right.stale))
    || Number(right.available) - Number(left.available)
    || left.price - right.price
    || left.shop.localeCompare(right.shop, "zh-CN"));
}

export async function collectInventory(fetchImpl = fetch, shopsConfig = SHOPS) {
  const errors = new Map();
  const results = await Promise.all(shopsConfig.map(async (shop) => {
    try {
      const result = await fetchShop(fetchImpl, shop);
      LAST_GOOD.set(shop.token, structuredClone(result));
      return result;
    } catch (error) {
      const message = failureMessage(error);
      errors.set(shop.token, message);
      if (LAST_GOOD.has(shop.token)) {
        const stale = { ...structuredClone(LAST_GOOD.get(shop.token)), ok: false, stale: true, message: `${message}，显示上次数据` };
        for (const item of stale.items) Object.assign(item, { stale: true, fetched_at: item.fetched_at || stale.fetched_at });
        return stale;
      }
      return {
        name: shop.name,
        nickname: shop.name,
        token: shop.token,
        url: shop.url,
        ok: false,
        stale: false,
        message,
        fetched_at: null,
        declared_count: 0,
        item_count: 0,
        items: [],
      };
    }
  }));

  const items = results.flatMap((shop) => shop.items);
  for (const shop of results) {
    for (const item of shop.items) Object.assign(item, { stale: Boolean(shop.stale), fetched_at: item.fetched_at || shop.fetched_at });
  }
  const duplicateShops = new Map();
  for (const item of items) {
    if (item.canonical.length < 8) continue;
    if (!duplicateShops.has(item.canonical)) duplicateShops.set(item.canonical, new Set());
    duplicateShops.get(item.canonical).add(item.shop_token);
  }
  for (const item of items) item.same_product_shops = duplicateShops.get(item.canonical)?.size || 0;
  sortItems(items);

  const availableCount = items.filter((item) => item.available).length;
  const freshShopCount = results.filter((shop) => shop.ok).length;
  const staleShopCount = results.filter((shop) => shop.stale).length;
  return {
    ok: freshShopCount > 0 || staleShopCount > 0,
    partial: errors.size > 0,
    generated_at: new Date().toISOString(),
    refresh_seconds: REFRESH_SECONDS,
    summary: {
      total: items.length,
      available: availableCount,
      out_of_stock: items.length - availableCount,
      groups: new Set(items.map((item) => item.group)).size,
      shops_fresh: freshShopCount,
      shops_stale: staleShopCount,
      shops_total: results.length,
    },
    shops: results.map(({ items: _items, ...shop }) => shop),
    items,
  };
}

function jsonResponse(payload, status = 200) {
  return Response.json(payload, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    },
  });
}

function inventoryResponse(payload, marker, refreshStatus, now, retryAfterSeconds = 0) {
  const delivered = structuredClone(payload);
  delivered.delivery = {
    refresh_status: refreshStatus,
    cache_age_seconds: Math.max(0, Math.round((now - Date.parse(payload.generated_at)) / 1000)),
    retry_after_seconds: Math.max(0, Math.ceil(retryAfterSeconds)),
  };
  return new Response(JSON.stringify(delivered), {
    status: payload.ok ? 200 : 502,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "X-Inventory-Cache": marker,
    },
  });
}

export async function handleRequest(request, env, ctx, dependencies = {}) {
  const url = new URL(request.url);
  if (url.pathname === "/api/health") {
    return jsonResponse({
      ok: true,
      service: "stock-comparison",
      version: "2026-08-17.2-worker",
      revision: env?.SERVICE_REVISION || "worker-fallback",
    });
  }
  if (url.pathname === "/api/analytics/session" && request.method === "POST") {
    return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
  }
  if (url.pathname === "/api/product-history") {
    return jsonResponse({ ok: false, message: "Cloudflare 回退版本不保存商品历史记录。" }, 503);
  }
  if (url.pathname === "/admin" || url.pathname === "/admin/" || url.pathname === "/admin.html") {
    return new Response("Cloudflare 回退版本不提供访问分析后台。", {
      status: 404,
      headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
    });
  }
  if (url.pathname === "/api/inventory") {
    const force = url.searchParams.get("refresh") === "1";
    const now = dependencies.now?.() ?? Date.now();
    const cache = dependencies.cache ?? globalThis.caches?.default;
    const cacheKey = new Request("https://stock-comparison-cache.local/api/inventory");
    if (cache) {
      const cached = await cache.match(cacheKey);
      if (cached) {
        const cachedPayload = await cached.json();
        const cacheAge = Math.max(0, now - Date.parse(cachedPayload.generated_at));
        if (!force) return inventoryResponse(cachedPayload, "HIT", "hit", now);
        if (cacheAge < MANUAL_REFRESH_COOLDOWN_MS) {
          return inventoryResponse(
            cachedPayload,
            "HIT",
            "cooldown",
            now,
            (MANUAL_REFRESH_COOLDOWN_MS - cacheAge) / 1000,
          );
        }
      }
    }

    if (!inventoryRefreshPromise) {
      inventoryRefreshPromise = collectInventory(dependencies.fetchImpl ?? fetch, dependencies.shopsConfig ?? SHOPS)
        .finally(() => { inventoryRefreshPromise = null; });
    }
    const payload = await inventoryRefreshPromise;
    if (payload.ok && cache) {
      const cachedResponse = new Response(JSON.stringify(payload), {
        headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "s-maxage=290" },
      });
      const cacheWrite = cache.put(cacheKey, cachedResponse);
      if (ctx?.waitUntil) ctx.waitUntil(cacheWrite);
      else await cacheWrite;
    }
    return inventoryResponse(payload, force ? "BYPASS" : "MISS", "refreshed", now);
  }
  if (env?.ASSETS?.fetch) {
    const asset = await env.ASSETS.fetch(request);
    const headers = new Headers(asset.headers);
    const immutable = Boolean(url.search)
      && (url.pathname.endsWith(".css") || url.pathname.endsWith(".js") || url.pathname.startsWith("/assets/"));
    headers.set("Cache-Control", immutable ? "public, max-age=31536000, immutable" : "no-store");
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set("Referrer-Policy", "no-referrer");
    headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
    headers.set("Permissions-Policy", "camera=(), geolocation=(), microphone=()");
    headers.set("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
    return new Response(asset.body, { status: asset.status, statusText: asset.statusText, headers });
  }
  return new Response("未找到页面", { status: 404 });
}

export default {
  fetch(request, env, ctx) {
    return handleRequest(request, env, ctx);
  },
};
