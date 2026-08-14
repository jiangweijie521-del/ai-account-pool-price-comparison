"use strict";

const elements = {
  updatedAt: document.querySelector("#updatedAt"),
  todayUniqueIps: document.querySelector("#todayUniqueIps"),
  todayVisits: document.querySelector("#todayVisits"),
  todayAverage: document.querySelector("#todayAverage"),
  todayTotal: document.querySelector("#todayTotal"),
  refreshButton: document.querySelector("#refreshButton"),
  table: document.querySelector("#analyticsTable"),
  tableBody: document.querySelector("#analyticsTable tbody"),
  tableState: document.querySelector("#tableState"),
  retentionDays: document.querySelector("#retentionDays"),
};

function formatDuration(value) {
  const seconds = Math.max(0, Number(value) || 0);
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  if (minutes < 60) return remainder ? `${minutes} 分 ${remainder} 秒` : `${minutes} 分`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours} 小时 ${remainingMinutes} 分` : `${hours} 小时`;
}

function formatDate(value) {
  const date = new Date(`${value}T00:00:00+08:00`);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  }).format(date);
}

function setToday(day) {
  elements.todayUniqueIps.textContent = String(day?.unique_ips || 0);
  elements.todayVisits.textContent = String(day?.visits || 0);
  elements.todayAverage.textContent = formatDuration(day?.average_seconds || 0);
  elements.todayTotal.textContent = formatDuration(day?.total_seconds || 0);
}

function renderRows(days) {
  elements.tableBody.replaceChildren();
  for (const day of days) {
    const row = document.createElement("tr");
    const values = [
      ["日期", formatDate(day.date)],
      ["估算独立 IP", day.unique_ips],
      ["估算访问次数", day.visits],
      ["平均停留", formatDuration(day.average_seconds)],
      ["总停留", formatDuration(day.total_seconds)],
    ];
    for (const [label, value] of values) {
      const cell = document.createElement("td");
      cell.dataset.label = label;
      cell.textContent = String(value);
      row.append(cell);
    }
    elements.tableBody.append(row);
  }
}

async function loadAnalytics() {
  elements.refreshButton.disabled = true;
  elements.tableState.hidden = false;
  elements.tableState.dataset.state = "loading";
  elements.tableState.textContent = "正在加载统计数据…";
  try {
    const response = await fetch("/api/admin/analytics?days=30", {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "读取失败");

    const currentDate = payload.generated_at.slice(0, 10);
    setToday(payload.days.find((day) => day.date === currentDate));
    renderRows(payload.days);
    elements.retentionDays.textContent = String(payload.retention_days);
    elements.updatedAt.textContent = `更新于 ${new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date(payload.generated_at))}`;
    elements.table.hidden = payload.days.length === 0;
    elements.tableState.hidden = payload.days.length > 0;
    elements.tableState.textContent = payload.days.length ? "" : "近 30 天还没有访问数据。";
    elements.tableState.dataset.state = payload.days.length ? "ready" : "empty";
  } catch (error) {
    setToday(null);
    elements.table.hidden = true;
    elements.tableState.hidden = false;
    elements.tableState.dataset.state = "error";
    elements.tableState.textContent = `统计数据读取失败：${error instanceof Error ? error.message : "未知错误"}`;
    elements.updatedAt.textContent = "读取失败";
  } finally {
    elements.refreshButton.disabled = false;
  }
}

elements.refreshButton.addEventListener("click", loadAnalytics);
loadAnalytics();
window.setInterval(loadAnalytics, 60_000);
