const form = document.querySelector("#eventForm");
const timeline = document.querySelector("#timeline");
const analysisPanel = document.querySelector("#analysisPanel");
const statsStrip = document.querySelector("#statsStrip");
const refreshButton = document.querySelector("#refreshButton");
const analysisProvider = document.querySelector("#analysisProvider");
const enrichProvider = document.querySelector("#enrichProvider");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  button.textContent = "处理中...";
  const content = form.content.value.trim();
  try {
    const result = await api("/api/events", {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    analysisProvider.textContent = `分析: ${result.event.analysis?.provider || "unknown"}`;
    enrichProvider.textContent = `抽取: ${result.enrichment_provider || "unknown"}`;
    renderAnalysis(result.event);
    form.reset();
    await loadDashboard();
  } catch (error) {
    analysisPanel.innerHTML = `<h2>提交失败</h2><p>${escapeHtml(error.message)}</p>`;
  } finally {
    button.disabled = false;
    button.textContent = "记录并分析";
  }
});

refreshButton.addEventListener("click", loadDashboard);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "请求失败");
  return payload;
}

async function loadDashboard() {
  const [eventData, stats] = await Promise.all([api("/api/events"), api("/api/stats")]);
  renderStats(stats);
  renderTimeline(eventData.events, eventData.edges);
  if (eventData.events[0]?.analysis) {
    renderAnalysis(eventData.events[0]);
  }
}

function renderStats(stats) {
  const totalAmount = stats.totals.reduce((sum, item) => sum + item.amount, 0);
  statsStrip.innerHTML = [
    statCard("事件总数", String(stats.event_count)),
    statCard("自动关联", String(stats.edge_count)),
    statCard("金额合计", `¥${totalAmount.toFixed(2)}`),
  ].join("");
}

function statCard(label, value) {
  return `<div class="stat"><span>${label}</span><strong>${value}</strong></div>`;
}

function renderAnalysis(event) {
  const analysis = event.analysis;
  if (!analysis) return;
  const score = Number(analysis.fairness_score || 50);
  const marker = `calc(${score}% - 2px)`;
  analysisPanel.innerHTML = `
    <h2>${escapeHtml(event.title)}</h2>
    <p class="meta">${event.occurred_on} | ${event.narrator_label} | ¥${Number(event.amount || 0).toFixed(2)}</p>
    <p>${escapeHtml(analysis.core_issue)}</p>
    <div class="score">
      <p class="meta">公平倾向分: ${score}/100</p>
      <div class="score-track"><div class="score-pin" style="--score:${marker}"></div></div>
    </div>
    <div class="grid">
      ${chip("事实", analysis.facts)}
      ${chip("主张", analysis.claims)}
      ${chip("需求", analysis.needs)}
      ${chip("风险", analysis.risk_flags)}
      ${chip("追问", analysis.suggested_questions)}
      ${chip("下一步", [analysis.next_action, analysis.narrator_bias_note])}
    </div>
  `;
}

function chip(title, items = []) {
  const list = items?.length ? items : ["暂无"];
  return `<section class="chip-card"><h3>${title}</h3><ul>${list
    .map((x) => `<li>${escapeHtml(String(x))}</li>`)
    .join("")}</ul></section>`;
}

function renderTimeline(events, edges) {
  if (!events.length) {
    timeline.innerHTML = `<article class="event-card"><p class="meta">还没有记录，先写第一条。</p></article>`;
    return;
  }
  const linkedCount = new Map();
  edges.forEach((edge) => {
    linkedCount.set(edge.source_event_id, (linkedCount.get(edge.source_event_id) || 0) + 1);
    linkedCount.set(edge.target_event_id, (linkedCount.get(edge.target_event_id) || 0) + 1);
  });
  timeline.innerHTML = events
    .map((event) => {
      const tags = (event.tags || []).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
      return `
        <article class="event-card">
          <h3 class="event-title">#${event.id} ${escapeHtml(event.title)}</h3>
          <p class="meta">${event.occurred_on} | ${event.narrator_label} | 关联 ${linkedCount.get(event.id) || 0}</p>
          <p>${escapeHtml(event.content)}</p>
          <div class="tag-row">${tags}</div>
        </article>
      `;
    })
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

loadDashboard();

