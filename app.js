"use strict";

const elements = {
  paper: document.querySelector(".paper"),
  skipLink: document.querySelector(".skip-link"),
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
  historyBackdrop: document.querySelector("#historyBackdrop"),
  historyPanel: document.querySelector("#historyPanel"),
  historyClose: document.querySelector("#historyClose"),
  historyTitle: document.querySelector("#historyTitle"),
  historyMeta: document.querySelector("#historyMeta"),
  historyBody: document.querySelector("#historyBody"),
  historyRangeButtons: [...document.querySelectorAll("[data-history-days]")],
};

const state = {
  data: null,
  onlyAvailable: true,
  query: "",
  loading: false,
  countdown: 60,
  expandedGroups: new Set(),
  historyItem: null,
  historyDays: 7,
  historyRequest: 0,
  historyReturnFocus: null,
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

function createSvgElement(tag, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, String(value));
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

function formatDay(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(date);
}

function formatAge(value) {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "时间未知";
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (seconds < 60) return `${seconds} 秒前`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} 小时前` : `${Math.round(hours / 24)} 天前`;
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
    if (Boolean(left.stale) !== Boolean(right.stale)) return left.stale ? 1 : -1;
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
  const row = createElement("div", "product-row");
  if (isCheapest) row.classList.add("is-cheapest");
  if (!item.available) row.classList.add("is-unavailable");
  if (item.stale) row.classList.add("is-stale");

  const link = createElement("a", "product-link");
  link.href = safeLink(item.link, item.shop_url);
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.setAttribute("aria-label", `${item.name}，${item.shop}，${stockText(item)}，${formatPrice(item.price)}，打开商品详情`);

  const main = createElement("span", "product-main");
  const name = createElement("strong");
  if (isCheapest) name.append(createElement("span", "cheapest-badge", "最便宜"));
  name.append(document.createTextNode(item.name));
  main.append(name, createElement("small", "", `${item.category} · ${item.goods_type_label}`));

  const tags = createElement("span", "tags");
  const tagValues = [...item.tags];
  if (item.stale) tagValues.unshift(`旧数据 · ${formatAge(item.fetched_at)}`);
  if (item.same_product_shops >= 2) tagValues.unshift(`同款 ${item.same_product_shops} 店`);
  if (tagValues.length === 0) tagValues.push("查看详情");
  for (const value of tagValues.slice(0, 4)) tags.append(createElement("span", "tag", value));

  link.append(
    main,
    createElement("span", "shop-name", item.shop),
    tags,
    createElement("span", "stock", stockText(item)),
    createElement("span", "price", formatPrice(item.price)),
  );
  const trendButton = createElement("button", "trend-button");
  trendButton.type = "button";
  trendButton.title = "查看价格与库存走势";
  trendButton.setAttribute("aria-label", `查看${item.name}的价格与库存走势`);
  const icon = createSvgElement("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
  icon.append(
    createSvgElement("path", { d: "M4 18V6M4 18h16" }),
    createSvgElement("path", { d: "m7 14 4-4 3 2 5-6" }),
  );
  trendButton.append(icon, createElement("span", "trend-label", "走势"));
  trendButton.addEventListener("click", () => openHistory(item, trendButton));
  row.append(link, trendButton);
  return row;
}

function renderCheapest(items) {
  const winners = new Map();
  for (const item of items.filter((entry) => entry.available && !entry.stale)) {
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
    const winner = entries.find((item) => item.available && !item.stale);
    entries.forEach((item) => cluster.append(makeProductRow(item, item === winner)));
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
    const winner = sorted.find((item) => item.available && !item.stale);
    const section = createElement("section", "inventory-group");
    const heading = createElement("div", "group-heading");
    const title = createElement("h3", "", groupName);
    const availableCount = sorted.filter((item) => item.available).length;
    const meta = createElement("p", "", `${availableCount} 件有货 / 共 ${sorted.length} 件`);
    heading.append(title, meta);
    section.append(heading, makeRowHead());
    const shouldCollapse = window.innerWidth <= 760 && !state.query && sorted.length > 6 && !state.expandedGroups.has(groupName);
    const shown = shouldCollapse ? sorted.slice(0, 6) : sorted;
    shown.forEach((item) => section.append(makeProductRow(item, item === winner)));
    if (shouldCollapse) {
      const button = createElement("button", "group-expand", `展开其余 ${sorted.length - shown.length} 件`);
      button.type = "button";
      button.setAttribute("aria-label", `展开${groupName}其余 ${sorted.length - shown.length} 件商品`);
      button.addEventListener("click", () => {
        state.expandedGroups.add(groupName);
        render();
      });
      section.append(button);
    }
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
      createElement(
        "small",
        "",
        `${shop.item_count} 件商品 · ${shop.message}${shop.fetched_at ? ` · 数据于 ${formatAge(shop.fetched_at)}` : ""}`,
      ),
    );
    elements.shopList.append(link);
  }
}

function historyPointX(observations, index) {
  const timestamps = observations.map((point) => new Date(point.at).getTime());
  const first = timestamps[0];
  const last = timestamps.at(-1);
  if (!Number.isFinite(first) || !Number.isFinite(last) || first === last) {
    return observations.length === 1 ? 285 : 42 + (index / Math.max(1, observations.length - 1)) * 486;
  }
  return 42 + ((timestamps[index] - first) / (last - first)) * 486;
}

function historyPointY(observations, accessor, index, top, height) {
  const values = observations.map(accessor).filter((value) => Number.isFinite(value));
  const value = accessor(observations[index]);
  if (values.length === 0 || !Number.isFinite(value)) return null;
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const spread = Math.max(maximum - minimum, 1);
  return top + height - ((value - minimum) / spread) * height;
}

function historyLinePath(observations, accessor, top, height) {
  let drawing = false;
  const commands = [];
  observations.forEach((point, index) => {
    const value = accessor(point);
    if (!Number.isFinite(value)) {
      drawing = false;
      return;
    }
    const x = historyPointX(observations, index);
    const y = historyPointY(observations, accessor, index, top, height);
    commands.push(`${drawing ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`);
    drawing = true;
  });
  return commands.join(" ");
}

function appendHistoryPoint(svg, observations, accessor, top, height, className) {
  const index = observations.findLastIndex((point) => Number.isFinite(accessor(point)));
  if (index < 0) return;
  svg.append(createSvgElement("circle", {
    class: `history-point ${className}`,
    cx: historyPointX(observations, index),
    cy: historyPointY(observations, accessor, index, top, height),
    r: 5,
  }));
}

function makeHistoryChart(payload) {
  const wrapper = createElement("section", "history-chart");
  wrapper.setAttribute("aria-label", `${payload.range_days}天价格与库存变化图`);
  const legend = createElement("div", "history-legend");
  const priceLegend = createElement("span", "history-legend-price", "价格");
  const stockLegend = createElement("span", "history-legend-stock", "库存");
  legend.append(priceLegend, stockLegend);
  if (payload.observations.some((point) => point.restock)) {
    legend.append(createElement("span", "history-legend-restock", "补货"));
  }

  const svg = createSvgElement("svg", {
    viewBox: "0 0 560 260",
    role: "img",
    "aria-label": `${payload.range_days}天内价格与库存走势；价格和库存分区绘制`,
  });
  svg.append(
    createSvgElement("line", { class: "history-axis", x1: 42, y1: 112, x2: 528, y2: 112 }),
    createSvgElement("line", { class: "history-axis", x1: 42, y1: 226, x2: 528, y2: 226 }),
  );
  const priceLabel = createSvgElement("text", { class: "history-axis-label", x: 42, y: 25 });
  priceLabel.textContent = "价格";
  const stockLabel = createSvgElement("text", { class: "history-axis-label", x: 42, y: 139 });
  stockLabel.textContent = "库存";
  svg.append(priceLabel, stockLabel);

  for (const [index, point] of payload.observations.entries()) {
    if (!point.restock) continue;
    const x = historyPointX(payload.observations, index);
    svg.append(createSvgElement("line", { class: "history-restock-line", x1: x, y1: 145, x2: x, y2: 226 }));
  }
  svg.append(
    createSvgElement("path", {
      class: "history-line history-line-price",
      d: historyLinePath(payload.observations, (point) => Number(point.price), 35, 66),
    }),
    createSvgElement("path", {
      class: "history-line history-line-stock",
      d: historyLinePath(payload.observations, (point) => point.stock, 149, 66),
    }),
  );
  appendHistoryPoint(svg, payload.observations, (point) => Number(point.price), 35, 66, "history-point-price");
  appendHistoryPoint(svg, payload.observations, (point) => point.stock, 149, 66, "history-point-stock");
  const firstTime = createSvgElement("text", {
    class: "history-date-label",
    x: payload.observations.length === 1 ? 285 : 42,
    y: 251,
    "text-anchor": payload.observations.length === 1 ? "middle" : "start",
  });
  firstTime.textContent = formatDay(payload.observations[0].at);
  svg.append(firstTime);
  if (payload.observations.length > 1) {
    const lastTime = createSvgElement("text", { class: "history-date-label", x: 528, y: 251, "text-anchor": "end" });
    lastTime.textContent = formatDay(payload.observations.at(-1).at);
    svg.append(lastTime);
  }
  wrapper.append(legend, svg);
  return wrapper;
}

function renderHistory(payload) {
  elements.historyMeta.textContent = `${payload.item.name} · ${payload.item.shop}`;
  const metrics = createElement("section", "history-metrics");
  for (const [label, value] of [
    ["当前价格", formatPrice(payload.item.current_price)],
    ["区间最低", formatPrice(payload.metrics.min_price)],
    ["区间最高", formatPrice(payload.metrics.max_price)],
  ]) {
    const metric = createElement("div");
    metric.append(createElement("span", "", label), createElement("strong", "", value));
    metrics.append(metric);
  }

  const forecast = createElement("section", `history-forecast is-${payload.forecast.status}`);
  forecast.append(createElement("p", "history-section-label", "预计库存"));
  let forecastValue = "暂不预测";
  if (payload.forecast.status === "ready") {
    forecastValue = `约 ${payload.forecast.min_days}–${payload.forecast.max_days} 天`;
  } else if (payload.forecast.status === "depleted") {
    forecastValue = "当前已无库存";
  }
  forecast.append(createElement("strong", "", forecastValue));
  const confidenceLabels = { high: "较高", medium: "中等", low: "较低", none: "未评级" };
  const forecastMeta = createElement("p", "", payload.forecast.reason);
  if (payload.forecast.status === "ready") {
    forecastMeta.append(document.createTextNode(` 置信度：${confidenceLabels[payload.forecast.confidence] || "较低"}。`));
  }
  forecast.append(forecastMeta);

  const evidence = createElement("section", "history-evidence");
  const stockValue = payload.item.current_stock === null ? "未提供" : `${payload.item.current_stock} 件`;
  for (const [label, value] of [
    ["当前库存", stockValue],
    ["有效记录", `${payload.metrics.sample_count} 个`],
    [
      "记录区间",
      payload.metrics.first_observed_at === payload.metrics.last_observed_at
        ? formatTime(payload.metrics.last_observed_at)
        : `${formatDay(payload.metrics.first_observed_at)}–${formatDay(payload.metrics.last_observed_at)}`,
    ],
  ]) {
    const cell = createElement("div");
    cell.append(createElement("span", "", label), createElement("strong", "", value));
    evidence.append(cell);
  }

  const note = createElement(
    "p",
    "history-note",
    "预计区间只依据公开库存的净下降速度；补货、下架、库存修正或上游异常都会影响结果。",
  );
  elements.historyBody.replaceChildren(metrics, makeHistoryChart(payload), forecast, evidence, note);
}

function renderHistoryState(message, type = "loading") {
  const stateMessage = createElement("div", `history-state is-${type}`);
  const titles = { loading: "读取记录中", empty: "暂无历史记录", error: "暂时无法显示" };
  stateMessage.append(createElement("strong", "", titles[type] || titles.error));
  stateMessage.append(createElement("p", "", message));
  if (type === "error") {
    const retry = createElement("button", "history-retry", "重新读取");
    retry.type = "button";
    retry.addEventListener("click", () => loadProductHistory(state.historyDays));
    stateMessage.append(retry);
  }
  elements.historyBody.replaceChildren(stateMessage);
}

async function loadProductHistory(days) {
  if (!state.historyItem) return;
  state.historyDays = days;
  elements.historyRangeButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(Number(button.dataset.historyDays) === days));
  });
  const requestId = ++state.historyRequest;
  renderHistoryState(`正在读取最近 ${days} 天的价格与库存…`);
  const item = state.historyItem;
  const query = new URLSearchParams({ shop_token: item.shop_token, key: item.key, days: String(days) });
  try {
    const response = await fetch(`/api/product-history?${query}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.message || "历史数据暂时不可用");
    if (payload.empty) {
      if (requestId === state.historyRequest) renderHistoryState(payload.message || "这个商品还没有历史记录。", "empty");
      return;
    }
    if (requestId === state.historyRequest) renderHistory(payload);
  } catch (error) {
    if (requestId !== state.historyRequest) return;
    const message = error instanceof Error ? error.message : "历史数据暂时不可用";
    renderHistoryState(message, "error");
  }
}

function openHistory(item, trigger) {
  state.historyItem = item;
  state.historyReturnFocus = trigger;
  state.historyDays = 7;
  elements.historyTitle.textContent = "价格与库存走势";
  elements.historyMeta.textContent = `${item.name} · ${item.shop}`;
  elements.historyPanel.hidden = false;
  elements.historyBackdrop.hidden = false;
  elements.paper.inert = true;
  elements.paper.setAttribute("aria-hidden", "true");
  elements.skipLink.inert = true;
  elements.skipLink.setAttribute("aria-hidden", "true");
  document.body.classList.add("history-open");
  window.requestAnimationFrame(() => {
    elements.historyPanel.classList.add("is-open");
    elements.historyBackdrop.classList.add("is-open");
    elements.historyClose.focus();
  });
  loadProductHistory(7);
}

function closeHistory() {
  if (elements.historyPanel.hidden) return;
  state.historyRequest += 1;
  elements.historyPanel.classList.remove("is-open");
  elements.historyBackdrop.classList.remove("is-open");
  document.body.classList.remove("history-open");
  const returnFocus = state.historyReturnFocus;
  const delay = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 240;
  window.setTimeout(() => {
    elements.historyPanel.hidden = true;
    elements.historyBackdrop.hidden = true;
    elements.paper.inert = false;
    elements.paper.removeAttribute("aria-hidden");
    elements.skipLink.inert = false;
    elements.skipLink.removeAttribute("aria-hidden");
    if (returnFocus?.isConnected) returnFocus.focus();
  }, delay);
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
    elements.updatedAt.textContent = `检查时间 ${formatTime(payload.generated_at)}`;
    elements.updatedAt.dateTime = payload.generated_at;
    elements.syncStamp.textContent = payload.partial ? "部分同步" : "数据已同步";
    elements.syncStamp.dataset.state = payload.partial ? "warning" : "success";
    const summary = payload.summary;
    const delivery = payload.delivery || {};
    const staleShops = payload.shops.filter((shop) => shop.stale && shop.fetched_at);
    const oldestStale = staleShops.sort((left, right) => new Date(left.fetched_at) - new Date(right.fetched_at))[0];
    let message = payload.partial
      ? `已显示 ${summary.available} 件有货商品；旧数据已标出且不参与最低价${oldestStale ? `，最早来自 ${formatAge(oldestStale.fetched_at)}` : ""}。`
      : `已同步 ${summary.shops_fresh} 家店铺：${summary.available} 件有货，${summary.out_of_stock} 件缺货。`;
    if (force && delivery.refresh_status === "cooldown") {
      message = `刚刚已有刷新结果，正在使用共享数据；${delivery.retry_after_seconds || 1} 秒后可再次读取店铺。`;
    } else if (force && delivery.refresh_status === "refreshed" && !payload.partial) {
      message = `已重新读取 ${summary.shops_fresh} 家店铺：${summary.available} 件有货，${summary.out_of_stock} 件缺货。`;
    }
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

elements.historyClose.addEventListener("click", closeHistory);
elements.historyBackdrop.addEventListener("click", closeHistory);
elements.historyRangeButtons.forEach((button) => {
  button.addEventListener("click", () => loadProductHistory(Number(button.dataset.historyDays)));
});

document.addEventListener("keydown", (event) => {
  if (elements.historyPanel.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeHistory();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = [...elements.historyPanel.querySelectorAll("button:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])")]
    .filter((element) => !element.hidden);
  if (focusable.length === 0) {
    event.preventDefault();
    elements.historyPanel.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});

window.setInterval(() => {
  if (state.loading) return;
  state.countdown -= 1;
  if (state.countdown <= 0) {
    state.countdown = state.data?.refresh_seconds || 60;
    loadInventory(false);
  }
  elements.countdown.textContent = `${Math.max(0, state.countdown)} 秒后`;
}, 1000);

updateAvailabilityControl();
loadInventory(false);

window.addEventListener("resize", () => {
  if (state.data) render();
});
