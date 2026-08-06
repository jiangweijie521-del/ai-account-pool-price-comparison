"use strict";

const elements = {
  availabilityToggle: document.querySelector("#availabilityToggle"),
  availabilityState: document.querySelector("#availabilityState"),
  refreshButton: document.querySelector("#refreshButton"),
  refreshLabel: document.querySelector("#refreshLabel"),
  countdown: document.querySelector("#countdown"),
  searchForm: document.querySelector("#searchForm"),
  searchInput: document.querySelector("#searchInput"),
  clearSearch: document.querySelector("#clearSearch"),
  notice: document.querySelector("#notice"),
  updatedAt: document.querySelector("#updatedAt"),
  syncStamp: document.querySelector("#syncStamp"),
  cheapest: document.querySelector("#cheapest"),
  cheapestList: document.querySelector("#cheapestList"),
  comparisons: document.querySelector("#comparisons"),
  comparisonList: document.querySelector("#comparisonList"),
  inventoryList: document.querySelector("#inventoryList"),
  resultCount: document.querySelector("#resultCount"),
  shopList: document.querySelector("#shopList"),
};

const state = {
  data: null,
  onlyAvailable: true,
  query: "",
  loading: false,
  countdown: 60,
};

const priceFormatter = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const collator = new Intl.Collator("zh-CN", { numeric: true, sensitivity: "base" });

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function setNotice(message, type = "success") {
  elements.notice.textContent = message;
  elements.notice.dataset.state = type;
}

function formatPrice(value) {
  return priceFormatter.format(Number(value));
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function stockText(item) {
  if (!item.available) return "缺货";
  return item.stock === null ? "库存未限" : `库存 ${item.stock}`;
}

function safeLink(value, fallback) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "pay.ldxp.cn" ? url.href : fallback;
  } catch {
    return fallback;
  }
}

function sortedItems(items) {
  return [...items].sort((left, right) => {
    if (left.available !== right.available) return left.available ? -1 : 1;
    if (left.price !== right.price) return left.price - right.price;
    return collator.compare(left.shop, right.shop);
  });
}

function visibleItems() {
  if (!state.data) return [];
  const query = state.query.trim().toLocaleLowerCase("zh-CN");
  return state.data.items.filter((item) => {
    if (state.onlyAvailable && !item.available) return false;
    if (!query) return true;
    return [item.name, item.group, item.category, item.shop, ...item.tags]
      .join(" ")
      .toLocaleLowerCase("zh-CN")
      .includes(query);
  });
}

function makeRowHead() {
  const row = createElement("div", "row-head");
  for (const label of ["商品", "店铺", "商品说明", "库存", "价格"]) {
    row.append(createElement("span", "", label));
  }
  return row;
}

function makeProductRow(item, isCheapest = false) {
  const row = createElement("a", "product-row");
  row.href = safeLink(item.link, item.shop_url);
  row.target = "_blank";
  row.rel = "noopener noreferrer";
  row.setAttribute("aria-label", `${item.name}，${item.shop}，${stockText(item)}，${formatPrice(item.price)}，打开商品详情`);
  if (isCheapest) row.classList.add("is-cheapest");
  if (!item.available) row.classList.add("is-unavailable");

  const main = createElement("span", "product-main");
  const name = createElement("strong");
  if (isCheapest) name.append(createElement("span", "cheapest-badge", "最便宜"));
  name.append(document.createTextNode(item.name));
  main.append(name, createElement("small", "", `${item.category} · ${item.goods_type_label}`));

  const tags = createElement("span", "tags");
  const tagValues = [...item.tags];
  if (item.same_product_shops >= 2) tagValues.unshift(`同款 ${item.same_product_shops} 店`);
  if (tagValues.length === 0) tagValues.push("查看详情");
  for (const value of tagValues.slice(0, 4)) tags.append(createElement("span", "tag", value));

  row.append(
    main,
    createElement("span", "shop-name", item.shop),
    tags,
    createElement("span", "stock", stockText(item)),
    createElement("span", "price", formatPrice(item.price)),
  );
  return row;
}

function renderCheapest(items) {
  const winners = new Map();
  for (const item of items.filter((entry) => entry.available)) {
    const shelfGroup = item.group.startsWith("GPT Plus") ? "GPT Plus" : item.group;
    const current = winners.get(shelfGroup);
    if (!current || item.price < current.price) winners.set(shelfGroup, { ...item, shelfGroup });
  }

  const picks = [...winners.values()]
    .sort((left, right) => left.group_rank - right.group_rank || left.price - right.price)
    .slice(0, 4);
  elements.cheapest.hidden = picks.length === 0;
  elements.cheapestList.replaceChildren();

  picks.forEach((item, index) => {
    const link = createElement("a", "cheap-pick");
    link.href = safeLink(item.link, item.shop_url);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.setAttribute("aria-label", `${item.group}最低价${formatPrice(item.price)}，${item.shop}，打开商品详情`);

    const heading = createElement("div");
    heading.append(createElement("span", "cheap-rank", String(index + 1)), createElement("span", "cheap-group", item.shelfGroup));
    link.append(
      heading,
      createElement("p", "cheap-price", formatPrice(item.price)),
      createElement("p", "cheap-meta", `${item.shop} · ${stockText(item)}`),
    );
    elements.cheapestList.append(link);
  });
}

function renderComparisons(items) {
  const groups = new Map();
  for (const item of items) {
    if (item.same_product_shops < 2 || item.canonical.length < 8) continue;
    if (!groups.has(item.canonical)) groups.set(item.canonical, []);
    groups.get(item.canonical).push(item);
  }

  const comparisons = [...groups.values()]
    .filter((entries) => new Set(entries.map((item) => item.shop_token)).size >= 2)
    .map(sortedItems)
    .sort((left, right) => left[0].price - right[0].price);

  elements.comparisons.hidden = comparisons.length === 0;
  elements.comparisonList.replaceChildren();
  for (const entries of comparisons) {
    const cluster = createElement("article", "comparison-cluster");
    const heading = createElement("div", "cluster-heading");
    const title = createElement("h3", "", entries[0].name);
    const meta = createElement("p", "", `${new Set(entries.map((item) => item.shop_token)).size} 家店 · 价格从低到高`);
    heading.append(title, meta);
    cluster.append(heading, makeRowHead());
    entries.forEach((item, index) => cluster.append(makeProductRow(item, index === 0 && item.available)));
    elements.comparisonList.append(cluster);
  }
}

function renderInventory(items) {
  const groups = new Map();
  for (const item of items) {
    if (!groups.has(item.group)) groups.set(item.group, []);
    groups.get(item.group).push(item);
  }

  const sortedGroups = [...groups.entries()].sort(([leftName, leftItems], [rightName, rightItems]) => {
    const rankDifference = leftItems[0].group_rank - rightItems[0].group_rank;
    return rankDifference || collator.compare(leftName, rightName);
  });

  elements.inventoryList.replaceChildren();
  elements.inventoryList.setAttribute("aria-busy", "false");
  elements.resultCount.textContent = `${items.length} 件商品 · ${sortedGroups.length} 类 · 价格从低到高`;

  if (items.length === 0) {
    const message = state.query
      ? `没有找到“${state.query}”相关商品。可清空搜索后再看。`
      : state.onlyAvailable
        ? "当前没有可展示的有货商品。可以点“只看有货”切换为显示全部。"
        : "店铺目前没有返回商品。";
    elements.inventoryList.append(createElement("p", "empty-state", message));
    return;
  }

  for (const [groupName, entries] of sortedGroups) {
    const sorted = sortedItems(entries);
    const firstAvailableIndex = sorted.findIndex((item) => item.available);
    const section = createElement("section", "inventory-group");
    const heading = createElement("div", "group-heading");
    const title = createElement("h3", "", groupName);
    const availableCount = sorted.filter((item) => item.available).length;
    const meta = createElement("p", "", `${availableCount} 件有货 / 共 ${sorted.length} 件`);
    heading.append(title, meta);
    section.append(heading, makeRowHead());
    sorted.forEach((item, index) => section.append(makeProductRow(item, index === firstAvailableIndex)));
    elements.inventoryList.append(section);
  }
}

function renderShops() {
  elements.shopList.replaceChildren();
  if (!state.data) return;
  for (const shop of state.data.shops) {
    const link = createElement("a", "shop-status");
    link.href = safeLink(shop.url, "https://pay.ldxp.cn");
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const status = shop.ok ? "正常" : shop.stale ? "旧数据" : "读取失败";
    link.dataset.state = shop.ok ? "ok" : shop.stale ? "stale" : "error";
    link.append(
      createElement("strong", "", `${shop.name} · ${status}`),
      createElement("small", "", `${shop.item_count} 件商品 · ${shop.message}`),
    );
    elements.shopList.append(link);
  }
}

function render() {
  const items = visibleItems();
  renderCheapest(items);
  renderComparisons(items);
  renderInventory(items);
  renderShops();
}

function updateAvailabilityControl() {
  elements.availabilityToggle.setAttribute("aria-pressed", String(state.onlyAvailable));
  elements.availabilityState.textContent = state.onlyAvailable ? "已开启" : "显示全部";
}

async function loadInventory(force = false) {
  if (state.loading) return;
  state.loading = true;
  elements.refreshButton.disabled = true;
  elements.refreshLabel.textContent = "正在刷新";
  elements.syncStamp.textContent = "读取中";
  elements.syncStamp.dataset.state = "loading";
  setNotice("正在读取四家店铺，请稍候…", "success");

  try {
    const suffix = force ? "?refresh=1" : "";
    const response = await fetch(`/api/inventory${suffix}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const payload = await response.json();
    if (!response.ok || (!payload.ok && payload.items?.length === 0)) {
      throw new Error(payload.message || "库存数据暂时不可用");
    }

    state.data = payload;
    state.countdown = Number(payload.refresh_seconds) || 60;
    elements.updatedAt.textContent = `最后更新 ${formatTime(payload.generated_at)}`;
    elements.updatedAt.dateTime = payload.generated_at;
    elements.syncStamp.textContent = payload.partial ? "部分同步" : "数据已同步";
    elements.syncStamp.dataset.state = payload.partial ? "warning" : "success";
    const summary = payload.summary;
    const message = payload.partial
      ? `已显示 ${summary.available} 件有货商品；部分店铺读取异常，旧数据会标出。`
      : `已同步 ${summary.shops_fresh} 家店铺：${summary.available} 件有货，${summary.out_of_stock} 件缺货。`;
    setNotice(message, payload.partial ? "warning" : "success");
    render();
  } catch (error) {
    elements.syncStamp.textContent = "刷新失败";
    elements.syncStamp.dataset.state = "error";
    const detail = error instanceof Error ? error.message : "未知错误";
    setNotice(`这次刷新没有成功：${detail}。保留已有数据，可稍后点“立即刷新”。`, "error");
    if (!state.data) {
      elements.inventoryList.setAttribute("aria-busy", "false");
      elements.inventoryList.replaceChildren(createElement("p", "empty-state", "还没有库存数据，请稍后点“立即刷新”。"));
      elements.resultCount.textContent = "暂时无数据";
    }
  } finally {
    state.loading = false;
    elements.refreshButton.disabled = false;
    elements.refreshLabel.textContent = "立即刷新";
  }
}

elements.availabilityToggle.addEventListener("click", () => {
  state.onlyAvailable = !state.onlyAvailable;
  updateAvailabilityControl();
  render();
});

elements.refreshButton.addEventListener("click", () => loadInventory(true));

elements.searchForm.addEventListener("submit", (event) => event.preventDefault());

elements.searchInput.addEventListener("input", (event) => {
  state.query = event.currentTarget.value.trim();
  elements.clearSearch.hidden = state.query.length === 0;
  render();
});

elements.clearSearch.addEventListener("click", () => {
  state.query = "";
  elements.searchInput.value = "";
  elements.clearSearch.hidden = true;
  render();
  elements.searchInput.focus();
});

window.setInterval(() => {
  if (state.loading) return;
  state.countdown -= 1;
  if (state.countdown <= 0) {
    state.countdown = state.data?.refresh_seconds || 60;
    loadInventory(true);
  }
  elements.countdown.textContent = `${Math.max(0, state.countdown)} 秒后`;
}, 1000);

updateAvailabilityControl();
loadInventory(false);
