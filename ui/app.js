// Phase 0 feed. Everything is rendered with DOM nodes and textContent, never innerHTML, because the
// feed is other people's text (tweets, forum posts, headlines).
const state = { source: null, topic: null, labels: {}, topicNames: [] };

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
};

const ago = (iso) => {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
};

const nice = (topic) => topic.replace(/_/g, " ");
const num = (n) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));

async function loadSummary() {
  const data = await (await fetch("/api/summary")).json();
  state.topicNames = data.topic_names;
  const summary = document.getElementById("summary");
  summary.replaceChildren();
  let newest = null;
  for (const s of data.sources) {
    const card = el("div", "card" + (s.enabled ? "" : " is-off") + (s.last_run && !s.last_run.ok ? " is-error" : ""));
    card.append(el("div", "card__label", s.label));
    card.append(el("div", "card__num", s.enabled ? String(s.last_24h ?? 0) : "off"));
    let sub = s.enabled ? `${s.total ?? 0} stored · every ${s.every_minutes >= 60 ? s.every_minutes / 60 + " h" : s.every_minutes + " min"}` : "key not set";
    if (s.last_run) {
      sub += s.last_run.ok ? ` · ran ${ago(s.last_run.finished_at)}` : ` · failed: ${s.last_run.error}`;
      if (s.last_run.ok && (!newest || s.last_run.finished_at > newest)) newest = s.last_run.finished_at;
    }
    card.append(el("div", "card__sub", sub));
    summary.append(card);
  }
  const live = document.getElementById("live");
  live.classList.toggle("is-live", !!newest && Date.now() - new Date(newest).getTime() < 90 * 60000);
  live.classList.toggle("is-stale", !!newest && Date.now() - new Date(newest).getTime() >= 90 * 60000);
  document.getElementById("live-text").textContent = newest ? `Updated ${ago(newest)}` : "No runs yet";
  renderHealth(data.sources);
}

function renderFilters() {
  const sources = document.getElementById("source-filters");
  sources.replaceChildren();
  const all = el("button", "chip" + (state.source ? "" : " is-active"), "All sources");
  all.onclick = () => { state.source = null; refresh(); };
  sources.append(all);
  for (const [key, label] of Object.entries(state.labels)) {
    const chip = el("button", "chip" + (state.source === key ? " is-active" : ""), label);
    chip.onclick = () => { state.source = state.source === key ? null : key; refresh(); };
    sources.append(chip);
  }
  const topics = document.getElementById("topic-filters");
  topics.replaceChildren();
  for (const t of state.topicNames) {
    const chip = el("button", "chip" + (state.topic === t ? " is-active" : ""), nice(t));
    chip.onclick = () => { state.topic = state.topic === t ? null : t; refresh(); };
    topics.append(chip);
  }
}

function metricsLine(item) {
  const m = item.metrics || {};
  const parts = [];
  if (m.like_count !== undefined) parts.push(`${num(m.like_count)} likes`, `${num(m.retweet_count)} reposts`, `${num(m.reply_count)} replies`);
  if (m.impression_count) parts.push(`${num(m.impression_count)} views`);
  if (m.comments !== undefined && item.source === "mse_forum") parts.push(`${num(m.comments)} comments`, `${num(m.views)} views`);
  if (m.views !== undefined && item.source === "youtube") parts.push(`${num(m.views)} views`, `${num(m.likes)} likes`);
  if (m.board) parts.push(m.board);
  if (m.via) parts.push(m.via.replace("_", " "));
  return parts;
}

async function loadFeed() {
  const params = new URLSearchParams({ limit: "150" });
  if (state.source) params.set("source", state.source);
  if (state.topic) params.set("topic", state.topic);
  const data = await (await fetch(`/api/feed?${params}`)).json();
  state.labels = data.labels;
  const feed = document.getElementById("feed");
  feed.replaceChildren();
  if (!data.items.length) {
    feed.append(el("div", "empty", "Nothing here yet. The pollers fill this in as they run."));
    return;
  }
  for (const item of data.items) {
    const card = el("article", "card item");
    const main = el("div");
    const meta = el("div", "item__meta");
    meta.append(el("span", `pill pill--${item.source}`, state.labels[item.source] || item.source));
    if (item.author) meta.append(el("span", null, item.author));
    for (const t of item.topics || []) meta.append(el("span", "topic", nice(t)));
    main.append(meta);
    if (item.title) {
      const title = el("div", "item__title");
      const link = el("a", null, item.title);
      link.href = item.url || "#"; link.target = "_blank"; link.rel = "noopener";
      title.append(link);
      main.append(title);
    }
    if (item.text && item.kind !== "article" && item.kind !== "guide_change") {
      main.append(el("div", "item__text", item.text));
    } else if (item.text) {
      const text = el("div", "item__text is-clamped", item.kind === "guide_change" ? item.text : (item.metrics && item.metrics.description) || item.text);
      text.onclick = () => text.classList.toggle("is-clamped");
      main.append(text);
    }
    const side = el("div", "item__side");
    const bumped = item.metrics && item.metrics.last_comment_at && item.metrics.last_comment_at !== item.published_at;
    const when = el("a", null, (bumped ? "active " : "") + ago(item.activity_at || item.published_at || item.first_seen_at));
    when.href = item.url || "#"; when.target = "_blank"; when.rel = "noopener";
    when.title = item.activity_at || item.published_at || item.first_seen_at;
    side.append(when);
    const metrics = el("div", "item__metrics");
    for (const part of metricsLine(item)) metrics.append(el("span", null, part));
    side.append(metrics);
    card.append(main, side);
    feed.append(card);
  }
}

function renderHealth(sources) {
  const health = document.getElementById("health");
  health.replaceChildren();
  const table = el("table");
  const head = el("tr");
  for (const h of ["Source", "Cadence", "Last run", "Result"]) head.append(el("th", null, h));
  table.append(head);
  for (const s of sources) {
    const row = el("tr");
    row.append(el("td", null, s.label));
    row.append(el("td", null, s.enabled ? `every ${s.every_minutes} min` : "disabled (key not set)"));
    row.append(el("td", null, s.last_run ? new Date(s.last_run.finished_at).toLocaleString("en-GB") : "never"));
    row.append(el("td", s.last_run ? (s.last_run.ok ? "ok" : "bad") : null, s.last_run ? (s.last_run.ok ? `${s.last_run.items_new} new` : s.last_run.error) : ""));
    table.append(row);
  }
  health.append(table);
}

async function refresh() {
  try {
    await Promise.all([loadSummary(), loadFeed()]);
    renderFilters();
  } catch (err) {
    document.getElementById("live-text").textContent = "Cannot reach the API";
    console.error(err);
  }
}

refresh();
setInterval(refresh, 60000);
