// Martin Monitor UI. Vanilla JS. Everything is built with DOM nodes and textContent, never innerHTML,
// because the feed is other people's text (tweets, forum posts, headlines).
const SVG = "http://www.w3.org/2000/svg";

const SOURCE_META = {
  x_martinslewis: { glyph: "x", home: "https://x.com/MartinSLewis", open: "Open on X" },
  x_moneysavingexp: { glyph: "x", home: "https://x.com/MoneySavingExp", open: "Open on X" },
  instagram: { glyph: "instagram", home: "https://www.instagram.com/martinlewismse/", open: "Open on Instagram" },
  mse_news: { glyph: "mse", home: "https://www.moneysavingexpert.com/news/", open: "Read on MSE" },
  mse_guides: { glyph: "guide", home: "https://www.moneysavingexpert.com/", open: "Open the guide" },
  mse_forum: { glyph: "forum", home: "https://forums.moneysavingexpert.com/", open: "Open the thread" },
  press: { glyph: "press", home: null, open: "Read the story" },
  reddit: { glyph: "reddit", home: "https://www.reddit.com/r/UKPersonalFinance/", open: "Open on Reddit" },
  youtube: { glyph: "youtube", home: "https://www.youtube.com/channel/UC5CDoveqvEuQsW3x-DnYtww", open: "Watch on YouTube" },
  trends: { glyph: "trends", home: "https://trends.google.com/", open: "Open Google Trends" },
  x: { glyph: "x", home: "https://x.com/MartinSLewis", open: "Open on X" },
};

const state = {
  tab: "signals", source: null, topic: null, q: "",
  summary: null, feed: [], insights: null, spread: null, runs: [],
  trends: {}, resolution: "weekly", martinPosts: null, showTable: false,
  expanded: new Set(), brianOpen: new Set(),
};

// ---------- helpers ----------
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
};
const svgEl = (tag, attrs = {}) => {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
};
const svgText = (x, y, text, cls, anchor = "start") => {
  const t = svgEl("text", { x, y, class: cls, "text-anchor": anchor });
  t.textContent = text;
  return t;
};
const icon = (name, cls = "ico") => {
  const svg = svgEl("svg", { class: cls, "aria-hidden": "true" });
  svg.append(svgEl("use", { href: `#i-${name}` }));
  return svg;
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
const until = (iso) => {
  if (!iso) return "";
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  if (mins <= 0) return "due now";
  if (mins < 60) return `in ${mins} min`;
  const hours = Math.round(mins / 60);
  return hours < 48 ? `in ${hours} h` : `in ${Math.round(hours / 24)} d`;
};
const fmtWhen = (iso) => (iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const shortDate = (ymd) => (ymd ? new Date(ymd + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");
const nice = (topic) => (topic || "").replace(/_/g, " ");
const num = (n) => (n === null || n === undefined ? "" : n >= 1000000 ? `${(n / 1000000).toFixed(1)}m` : n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));
const cadence = (m) => (m % 1440 === 0 ? (m === 1440 ? "daily" : `every ${m / 1440} d`) : m >= 60 ? `every ${m / 60} h` : `every ${m} min`);
const getJSON = async (url) => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
};
const outLink = (href, text, cls = "btn") => {
  const a = el("a", cls, text);
  a.href = href; a.target = "_blank"; a.rel = "noopener";
  a.append(icon("external", "ico ico--sm"));
  return a;
};
const label = (source) => (state.summary && state.summary.labels[source]) || source;

// ---------- tabs ----------
function setTab(name) {
  state.tab = name;
  for (const b of document.querySelectorAll(".tab")) b.classList.toggle("is-active", b.dataset.tab === name);
  for (const p of document.querySelectorAll(".panel")) p.hidden = p.id !== `panel-${name}`;
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  loadTab(name);
}
for (const b of document.querySelectorAll(".tab")) b.onclick = () => setTab(b.dataset.tab);

// ---------- signals ----------
async function loadSignals() {
  const params = new URLSearchParams({ limit: "150" });
  if (state.source) params.set("source", state.source);
  if (state.topic) params.set("topic", state.topic);
  if (state.q) params.set("q", state.q);
  const [summary, feed, insights, spread] = await Promise.all([
    getJSON("/api/summary"), getJSON(`/api/feed?${params}`), getJSON("/api/insights"), getJSON("/api/spread"),
  ]);
  state.summary = summary; state.feed = feed.items; state.insights = insights; state.spread = spread;
  renderLive(); renderHero(); renderFilters(); renderFeed(); renderBrianPanel();
}

function renderLive() {
  let newest = null;
  for (const s of state.summary.sources) if (s.last_run && s.last_run.ok && (!newest || s.last_run.finished_at > newest)) newest = s.last_run.finished_at;
  const live = document.getElementById("live");
  const fresh = newest && Date.now() - new Date(newest).getTime() < 90 * 60000;
  live.classList.toggle("is-live", !!fresh);
  live.classList.toggle("is-stale", !!newest && !fresh);
  document.getElementById("live-text").textContent = newest ? `Updated ${ago(newest)}` : "No runs yet";
}

function renderHero() {
  const s = state.summary, by = s.by_item_source || {};
  const martin = (by.x_martinslewis?.last_24h || 0) + (by.instagram?.last_24h || 0);
  const press = by.press?.last_24h || 0;
  const forum = (state.spread?.boards || []).reduce((a, b) => a + (b.active_24h || 0), 0);
  const topics = Object.entries(s.topics_24h || {}).sort((a, b) => b[1] - a[1]);
  const hero = document.getElementById("hero");
  hero.replaceChildren();

  const read = el("div", "hero__read");
  const avatar = el("img", "hero__avatar"); avatar.src = "brian.png"; avatar.alt = "Brian";
  const body = el("div");
  const brianRead = s.brian && s.brian.read;
  body.append(el("div", "hero__eyebrow", brianRead ? "Brian's read of the last 24 hours" : "The last 24 hours"));
  const sentence = [
    martin ? `Martin posted ${martin} ${martin === 1 ? "time" : "times"} on X and Instagram.` : "Martin has not posted on X or Instagram in the last 24 hours.",
    topics.length ? `In play: ${topics.slice(0, 3).map(([t]) => nice(t)).join(", ")}.` : "",
    `${press} press ${press === 1 ? "story" : "stories"} mentioned him and ${forum} forum ${forum === 1 ? "thread was" : "threads were"} active.`,
  ].filter(Boolean).join(" ");
  body.append(el("p", "hero__text", brianRead || sentence));
  body.append(el("p", "hero__note", brianRead ? `${sentence} Written ${ago(s.brian.read_at)} by Brian (${s.brian.model}).` : state.insights?.brian_enabled ? "Counted from the feed. Brian's first read lands within the hour." : "Counted from the feed. Brian's own read of what it means for Compare the Market arrives once the Anthropic key is connected."));
  read.append(avatar, body);
  hero.append(read);

  const tile = (labelText, value, sub) => {
    const t = el("div", "tile");
    t.append(el("div", "tile__label", labelText), el("div", "tile__num", String(value)));
    if (sub) t.append(el("div", "tile__sub", sub));
    return t;
  };
  hero.append(tile("Martin posts, 24h", martin, `${by.x_martinslewis?.last_24h || 0} on X · ${by.instagram?.last_24h || 0} on Instagram`));
  const cats = el("div", "tile");
  cats.append(el("div", "tile__label", "Categories in play"), el("div", "tile__num", String(topics.length)));
  const chips = el("div", "tile__chips");
  for (const [t, n] of topics.slice(0, 4)) {
    const c = el("button", "chip", `${nice(t)} ${n}`);
    c.onclick = () => { state.topic = t; loadSignals(); };
    chips.append(c);
  }
  cats.append(chips);
  hero.append(cats);
  hero.append(tile("Press stories, 24h", press, "Google News and Bing, GB edition"));
  hero.append(tile("Forum threads active, 24h", forum, (state.spread?.boards || []).slice(0, 2).map((b) => `${b.board} ${b.active_24h}`).join(" · ")));
}

function renderFilters() {
  const sources = document.getElementById("source-filters");
  sources.replaceChildren();
  const all = el("button", "chip" + (state.source ? "" : " is-active"), "All sources");
  all.onclick = () => { state.source = null; loadSignals(); };
  sources.append(all);
  for (const [key, text] of Object.entries(state.summary.labels)) {
    if (key === "trends") continue;
    const chip = el("button", "chip" + (state.source === key ? " is-active" : ""));
    chip.append(icon((SOURCE_META[key] || {}).glyph || "press"), document.createTextNode(text));
    chip.onclick = () => { state.source = state.source === key ? null : key; loadSignals(); };
    sources.append(chip);
  }
  const topics = document.getElementById("topic-filters");
  topics.replaceChildren();
  for (const t of state.summary.topic_names) {
    const chip = el("button", "chip" + (state.topic === t ? " is-active" : ""), nice(t));
    chip.title = `Items whose text contains: ${(state.summary.topic_defs[t] || []).join(", ")}`;
    chip.onclick = () => { state.topic = state.topic === t ? null : t; loadSignals(); };
    topics.append(chip);
  }
}

function metricsFor(item) {
  const m = item.metrics || {}, parts = [];
  if (m.like_count !== undefined) { parts.push(`${num(m.like_count)} likes`, `${num(m.retweet_count)} reposts`, `${num(m.reply_count)} replies`); if (m.impression_count) parts.push(`${num(m.impression_count)} views`); }
  if (item.source === "instagram") { if (m.likes != null) parts.push(`${num(m.likes)} likes`); if (m.comments != null) parts.push(`${num(m.comments)} comments`); if (m.views) parts.push(`${num(m.views)} plays`); }
  if (item.source === "mse_forum") parts.push(`${num(m.comments)} comments`, `${num(m.views)} views`, m.board);
  if (item.source === "reddit") parts.push(`${num(m.score)} points`, `${num(m.comments)} comments`, `r/${m.subreddit}`);
  if (item.source === "youtube") parts.push(`${num(m.views)} views`, `${num(m.likes)} likes`, `${num(m.comments)} comments`);
  if (item.source === "press" && m.via) parts.push(m.via.replace("_", " "));
  return parts.filter(Boolean);
}

function brianView(item) {
  const box = el("div", "brian-view" + (item.brian ? " has-view" : ""));
  const head = el("div", "brian-view__head");
  const img = el("img"); img.src = "brian.png"; img.alt = "";
  head.append(img, el("span", "brian-view__label", "Brian's view"));
  box.append(head);
  const b = item.brian;
  if (!b) {
    box.append(el("p", "brian-view__empty", "Brian hasn't read this one yet. Once the Anthropic key is connected he will say here what it means for Compare the Market: which product lines, which direction, how soon, and what to do about bids and budgets."));
    return box;
  }
  if (b.relevance === "none") { box.classList.remove("has-view"); box.classList.add("is-none"); box.append(el("p", "brian-view__text", `Not one for CTM. ${b.summary || ""}`)); return box; }
  box.append(el("p", "brian-view__text", b.summary || b.headline || ""));
  if (Array.isArray(b.impact) && b.impact.length) {
    const wrap = el("div", "brian-view__impacts");
    for (const i of b.impact) wrap.append(el("span", "impact", [nice(i.product), i.direction, i.magnitude, i.timing].filter(Boolean).join(" · ")));
    box.append(wrap);
  }
  if (Array.isArray(b.actions) && b.actions.length) {
    const ul = el("ul", "brian-view__actions");
    for (const a of b.actions) ul.append(el("li", null, typeof a === "string" ? a : a.text || JSON.stringify(a)));
    box.append(ul);
  }
  if (b.confidence) box.append(el("div", "brian-view__conf", `Confidence ${b.confidence}${b.relevance ? ` · relevance ${b.relevance}` : ""}${b.created_at ? ` · ${ago(b.created_at)}` : ""}`));
  return box;
}

async function askBrianAbout(item, card) {
  const btn = card.querySelector(".btn--brian");
  if (btn) { btn.disabled = true; btn.replaceChildren(document.createTextNode("Brian is reading…")); }
  try {
    const r = await fetch(`/api/brian/view/${item.id}`, { method: "POST" });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    item.brian = await r.json();
    state.brianOpen.add(item.id);
    card.replaceWith(renderItem(item));
  } catch (err) {
    if (btn) { btn.disabled = false; btn.replaceChildren(document.createTextNode(`Brian couldn't read it: ${err.message}`)); }
  }
}

function renderItem(item) {
  const meta = SOURCE_META[item.source] || { glyph: "press", open: "Open the source" };
  const card = el("article", "card item");
  card.dataset.id = item.id;

  const head = el("div", "item__head");
  const badge = meta.home ? el("a", "badge") : el("span", "badge");
  if (meta.home) { badge.href = meta.home; badge.target = "_blank"; badge.rel = "noopener"; badge.title = `Open ${label(item.source)}`; }
  badge.append(icon(meta.glyph), document.createTextNode(label(item.source)));
  head.append(badge);
  if (item.author) head.append(el("span", null, item.author));
  for (const t of item.topics || []) {
    const chip = el("button", "topic", nice(t));
    chip.title = `Filter by ${nice(t)}`;
    chip.onclick = () => { state.topic = t; loadSignals(); };
    head.append(chip);
  }
  const bumped = item.metrics && item.metrics.last_comment_at && item.metrics.last_comment_at !== item.published_at;
  const when = item.url ? el("a", "item__time") : el("span", "item__time");
  when.textContent = (bumped ? "active " : "") + ago(item.activity_at || item.published_at || item.first_seen_at);
  when.title = fmtWhen(item.activity_at || item.published_at || item.first_seen_at);
  if (item.url) { when.href = item.url; when.target = "_blank"; when.rel = "noopener"; }
  head.append(when);
  card.append(head);

  if (item.title) {
    const h = el("h3", "item__title");
    if (item.url) { const a = el("a", null, item.title); a.href = item.url; a.target = "_blank"; a.rel = "noopener"; a.append(icon("external")); h.append(a); }
    else h.textContent = item.title;
    card.append(h);
  }

  const isOpen = state.expanded.has(item.id);
  let body = null, expandable = false;
  if (item.kind === "guide_change" && item.text) {
    body = el("div", "item__body item__body--diff" + (isOpen ? "" : " is-clamped"), item.text); expandable = true;
  } else if (item.kind === "article") {
    const desc = item.metrics && item.metrics.description;
    const full = item.text && !item.text.startsWith("(article fetch failed");
    body = el("div", "item__body" + (isOpen ? "" : " is-clamped") + (isOpen || !desc ? "" : " item__body--desc"), isOpen && full ? item.text : (desc || (full ? item.text : "Article text not fetched yet.")));
    expandable = !!full;
  } else if (item.text) {
    body = el("div", "item__body" + (isOpen ? "" : " is-clamped"), item.text);
    expandable = item.text.length > 320 || item.text.split("\n").length > 5;
  }
  if (body) card.append(body);

  if (item.chain && (item.chain.mse.length || item.chain.press.length)) {
    const row = el("div", "item__chain");
    row.append(el("span", null, "Picked up:"));
    if (item.chain.mse.length) {
      const c = el("span", "chain"); c.append(icon("mse", "ico ico--sm"));
      const a = el("a", null, `MSE went official (${item.chain.mse.length})`); a.href = item.chain.mse[0].url; a.target = "_blank"; a.rel = "noopener"; c.append(a);
      row.append(c);
    }
    if (item.chain.press.length) {
      const c = el("span", "chain"); c.append(icon("press", "ico ico--sm"));
      c.append(document.createTextNode(`In the press ×${item.chain.press.length}: `));
      item.chain.press.slice(0, 3).forEach((p, i) => {
        if (i) c.append(document.createTextNode(", "));
        const a = el("a", null, p.publisher || "story"); a.href = p.url; a.target = "_blank"; a.rel = "noopener"; a.title = p.title || ""; c.append(a);
      });
      row.append(c);
    }
    card.append(row);
  }

  const foot = el("div", "item__foot");
  if (item.url) foot.append(outLink(item.url, meta.open, "btn btn--primary"));
  if (expandable) {
    const b = el("button", "btn" + (isOpen ? " is-on" : ""));
    b.append(document.createTextNode(isOpen ? "Show less" : item.kind === "article" ? `Read the full article (${num(item.text.length)} chars)` : item.kind === "guide_change" ? "Show the full change" : "Show the full post"));
    b.append(icon("chevron", "ico ico--sm ico--chev"));
    b.onclick = () => { if (isOpen) state.expanded.delete(item.id); else state.expanded.add(item.id); card.replaceWith(renderItem(item)); };
    foot.append(b);
  }
  const brianOn = state.insights?.brian_enabled;
  const brianOpen = state.brianOpen.has(item.id) || !!item.brian;
  const bb = el("button", "btn btn--brian" + (brianOpen ? " is-on" : ""));
  const bimg = el("img"); bimg.src = "brian.png"; bimg.alt = "";
  if (item.brian) {
    bb.append(bimg, document.createTextNode(item.brian.relevance === "none" ? "Brian: not one for CTM" : "Brian's view"), icon("chevron", "ico ico--sm ico--chev"));
    bb.onclick = () => { if (state.brianOpen.has(item.id)) state.brianOpen.delete(item.id); else state.brianOpen.add(item.id); card.replaceWith(renderItem(item)); };
  } else if (brianOn) {
    bb.append(bimg, document.createTextNode("Ask Brian about this"));
    bb.onclick = () => askBrianAbout(item, card);
  } else {
    bb.append(bimg, document.createTextNode("Brian's view (not yet)"), icon("chevron", "ico ico--sm ico--chev"));
    bb.onclick = () => { if (state.brianOpen.has(item.id)) state.brianOpen.delete(item.id); else state.brianOpen.add(item.id); card.replaceWith(renderItem(item)); };
  }
  foot.append(bb);
  const metrics = el("div", "item__metrics");
  for (const part of metricsFor(item)) metrics.append(el("span", null, part));
  foot.append(metrics);
  card.append(foot);
  if (item.brian ? brianOpen : state.brianOpen.has(item.id)) card.append(brianView(item));
  return card;
}

function renderFeed() {
  const feed = document.getElementById("feed");
  feed.replaceChildren();
  if (!state.feed.length) { feed.append(el("div", "empty", "Nothing matches. Try another source, category or search.")); return; }
  for (const item of state.feed) feed.append(renderItem(item));
}

function renderBrianPanel() {
  const panel = document.getElementById("brian-panel");
  panel.replaceChildren();
  const head = el("div", "brian-panel__head");
  const img = el("img"); img.src = "brian.png"; img.alt = "Brian";
  const t = el("div");
  t.append(el("div", "brian-panel__title", "Brian's Insights"), el("div", "brian-panel__sub", state.insights?.brian_enabled ? "Reads every new signal each hour" : "Waiting for the Anthropic key"));
  head.append(img, t);
  panel.append(head);
  const list = state.insights?.insights || [];
  if (!list.length) {
    const card = el("div", "card waiting");
    card.append(el("p", null, state.insights?.brian_enabled ? "No insights written yet. The first pass runs within the hour." : "Once the key is in, Brian reads the new signals every hour and writes here what they mean for Compare the Market:"));
    const ul = el("ul");
    for (const s of ["Which product line is affected, and which way demand moves", "How soon, and how big, with the evidence linked", "What to do about bids, budgets and creative"]) ul.append(el("li", null, s));
    card.append(ul);
    panel.append(card);
    if (state.insights?.brian_enabled) panel.append(askBox());
    return;
  }
  const latest = list[0].created_at;
  for (const ins of list.filter((i) => i.created_at === latest)) {
    const card = el("div", "card insight");
    card.append(el("div", "insight__head", ins.headline || ""), el("div", "insight__meta", `${ago(ins.created_at)}${ins.confidence ? ` · confidence ${ins.confidence}` : ""}`));
    if (ins.body) card.append(el("p", null, ins.body));
    if (Array.isArray(ins.impact) && ins.impact.length) {
      const wrap = el("div", "brian-view__impacts");
      for (const i of ins.impact) wrap.append(el("span", "impact", [nice(i.product), i.direction === "up" ? "▲" : i.direction === "down" ? "▼" : i.direction, i.magnitude, i.timing].filter(Boolean).join(" · ")));
      card.append(wrap);
    }
    if (Array.isArray(ins.actions) && ins.actions.length) { const ul = el("ul", "brian-view__actions"); for (const a of ins.actions) ul.append(el("li", null, a)); card.append(ul); }
    if (Array.isArray(ins.evidence) && ins.evidence.length) {
      const ev = el("div", "insight__evidence"); ev.append(document.createTextNode("Evidence: "));
      ins.evidence.slice(0, 5).forEach((id, i) => { if (i) ev.append(document.createTextNode(", ")); const a = el("a", null, `#${id}`); a.href = `/api/items/${id}`; a.target = "_blank"; a.rel = "noopener"; a.title = "Open the stored item"; ev.append(a); });
      card.append(ev);
    }
    panel.append(card);
  }
  panel.append(askBox());
}

function askBox() {
  const box = el("div", "card ask");
  box.append(el("div", "section-title", "Ask Brian"));
  const ta = el("textarea", "ask__input"); ta.placeholder = "e.g. Should we raise car insurance bids this week?"; ta.rows = 2; ta.maxLength = 500;
  const row = el("div", "ask__row");
  const send = el("button", "btn btn--primary", "Ask");
  const out = el("div", "ask__answer"); out.hidden = true;
  const suggestions = el("div", "filters");
  for (const q of ["What should CTM do about energy this week?", "Which product line is most exposed right now?", "Has anything Martin said been picked up by the press?"]) {
    const c = el("button", "chip", q); c.onclick = () => { ta.value = q; send.click(); }; suggestions.append(c);
  }
  send.onclick = async () => {
    const question = ta.value.trim();
    if (!question) return;
    send.disabled = true; out.hidden = false; out.replaceChildren(el("div", "ask__q", question), el("div", "ask__a", "…"));
    const a = out.querySelector(".ask__a");
    try {
      const r = await fetch("/api/brian/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "", text = "";
      for (;;) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n"); buf = parts.pop();
        for (const p of parts) if (p.startsWith("data: ")) { text += JSON.parse(p.slice(6)); a.textContent = text; }
      }
    } catch (err) { a.textContent = `Brian couldn't answer: ${err.message}`; }
    send.disabled = false;
  };
  row.append(send);
  box.append(ta, row, suggestions, out);
  return box;
}

// ---------- demand ----------
async function loadDemand() {
  const res = state.resolution;
  const [trends, martin, insta] = await Promise.all([
    getJSON(`/api/trends?resolution=${res}`),
    state.martinPosts ? null : getJSON("/api/feed?limit=500&source=x_martinslewis"),
    state.martinPosts ? null : getJSON("/api/feed?limit=500&source=instagram"),
  ]);
  state.trends[res] = trends;
  if (!state.martinPosts) state.martinPosts = [...martin.items, ...insta.items].filter((p) => p.published_at);
  renderDemand();
}

function indexFor(series, ymd, res) {
  let idx = -1;
  for (let i = 0; i < series.length; i++) if (series[i].period_start <= ymd) idx = i;
  if (idx === series.length - 1) {
    const end = new Date(series[idx].period_start + "T00:00:00Z").getTime() + (res === "weekly" ? 7 : 1) * 86400000;
    if (new Date(ymd + "T00:00:00Z").getTime() >= end) return -1;
  }
  return idx;
}

function lineChart(container, series, posts, res) {
  const W = 340, H = 150, padL = 26, padR = 8, padT = 12, padB = 22, n = series.length;
  if (!n) { container.append(el("div", "empty", "No data yet")); return; }
  const x = (i) => padL + (i * (W - padL - padR)) / Math.max(1, n - 1);
  const y = (v) => padT + ((100 - (v ?? 0)) / 100) * (H - padT - padB);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart__svg", role: "img" });
  for (const v of [0, 50, 100]) { svg.append(svgEl("line", { x1: padL, x2: W - padR, y1: y(v), y2: y(v), class: "chart__grid" })); svg.append(svgText(padL - 4, y(v) + 3, String(v), "chart__ylabel", "end")); }
  for (const i of [0, Math.floor((n - 1) / 2), n - 1]) svg.append(svgText(x(i), H - 6, shortDate(series[i].period_start), "chart__xlabel", i === 0 ? "start" : i === n - 1 ? "end" : "middle"));
  svg.append(svgEl("path", { d: series.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" "), class: "chart__line" }));
  const groups = new Map();
  for (const p of posts) { const i = indexFor(series, p.published_at.slice(0, 10), res); if (i >= 0) groups.set(i, [...(groups.get(i) || []), p]); }
  for (const [i, items] of groups) {
    const g = svgEl("g", { class: "chart__marker" });
    g.append(svgEl("circle", { cx: x(i), cy: y(series[i].value), r: 6, class: "chart__marker-ring" }));
    const dot = svgEl("circle", { cx: x(i), cy: y(series[i].value), r: 4.5, class: "chart__marker-dot" });
    const title = svgEl("title"); title.textContent = items.map((p) => (p.text || "").slice(0, 120)).join("\n\n"); dot.append(title);
    dot.onclick = () => window.open(items[0].url, "_blank", "noopener");
    g.append(dot);
    if (items.length > 1) g.append(svgText(x(i), y(series[i].value) - 10, String(items.length), "chart__marker-label", "middle"));
    svg.append(g);
  }
  const cross = svgEl("line", { class: "chart__cross", y1: padT, y2: H - padB, x1: 0, x2: 0, style: "display:none" });
  const hdot = svgEl("circle", { class: "chart__hover-dot", r: 4, style: "display:none" });
  svg.append(cross, hdot);
  const tip = el("div", "chart__tip"); tip.style.display = "none";
  container.append(svg, tip);
  svg.addEventListener("mousemove", (e) => {
    const rect = svg.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0, dist = Infinity;
    for (let i = 0; i < n; i++) { const d = Math.abs(x(i) - px); if (d < dist) { dist = d; best = i; } }
    cross.setAttribute("x1", x(best)); cross.setAttribute("x2", x(best)); cross.style.display = "";
    hdot.setAttribute("cx", x(best)); hdot.setAttribute("cy", y(series[best].value)); hdot.style.display = "";
    tip.replaceChildren(document.createTextNode(`${series[best].label}: ${series[best].value ?? "n/a"}`));
    const here = groups.get(best);
    if (here) tip.append(el("small", null, `${here.length} Martin ${here.length === 1 ? "post" : "posts"} · click the dot to open`));
    tip.style.left = `${(x(best) / W) * 100}%`; tip.style.display = "";
  });
  svg.addEventListener("mouseleave", () => { cross.style.display = "none"; hdot.style.display = "none"; tip.style.display = "none"; });
}

function renderDemand() {
  const data = state.trends[state.resolution];
  if (!data) return;
  for (const b of document.querySelectorAll(".seg")) b.classList.toggle("is-active", b.dataset.res === state.resolution);
  const legend = document.getElementById("demand-legend");
  legend.replaceChildren();
  const l1 = el("span", "legend__item"); l1.append(el("span", "legend__line"), document.createTextNode("Search interest (worldwide, 0 to 100)"));
  const l2 = el("span", "legend__item"); l2.append(el("span", "legend__dot"), document.createTextNode("Martin posted on this topic (X or Instagram)"));
  legend.append(l1, l2);
  const charts = document.getElementById("charts");
  charts.replaceChildren();
  for (const t of data.terms) {
    const series = data.series[t.term] || [];
    const card = el("div", "card chart");
    const head = el("div", "chart__head");
    const left = el("div"); left.append(el("div", "chart__term", t.term));
    if (t.topic) { const chip = el("button", "topic", nice(t.topic)); chip.onclick = () => { state.topic = t.topic; setTab("signals"); }; left.append(chip); }
    head.append(left);
    if (series.length >= 2) {
      const last = series[series.length - 1], prev = series[series.length - 2];
      const delta = (last.value ?? 0) - (prev.value ?? 0);
      const latest = el("div", "chart__latest");
      latest.append(el("b", null, String(last.value ?? "n/a")), document.createTextNode(` ${delta > 0 ? "▲" : delta < 0 ? "▼" : "·"} ${Math.abs(delta)} vs previous ${state.resolution === "weekly" ? "week" : "day"}`));
      head.append(latest);
    }
    card.append(head);
    const posts = (state.martinPosts || []).filter((p) => t.topic && (p.topics || []).includes(t.topic));
    lineChart(card, series, posts, state.resolution);
    charts.append(card);
  }
  const tableBox = document.getElementById("demand-table");
  tableBox.replaceChildren();
  document.getElementById("table-toggle").textContent = state.showTable ? "Hide the table" : "Show the numbers as a table";
  if (state.showTable) {
    const table = el("table", "data");
    const head = el("tr"); head.append(el("th", null, "Period"));
    for (const t of data.terms) head.append(el("th", "num", t.term));
    table.append(head);
    const periods = [...new Set(Object.values(data.series).flat().map((p) => p.period_start))].sort();
    const byTerm = Object.fromEntries(data.terms.map((t) => [t.term, Object.fromEntries((data.series[t.term] || []).map((p) => [p.period_start, p]))]));
    for (const p of periods) {
      const row = el("tr");
      const any = data.terms.map((t) => byTerm[t.term][p]).find(Boolean);
      row.append(el("td", null, any ? any.label : p));
      for (const t of data.terms) row.append(el("td", "num", byTerm[t.term][p] ? String(byTerm[t.term][p].value ?? "") : ""));
      table.append(row);
    }
    tableBox.append(table);
  }
}
for (const b of document.querySelectorAll(".seg")) b.onclick = () => { state.resolution = b.dataset.res; loadDemand(); };
document.getElementById("table-toggle").onclick = () => { state.showTable = !state.showTable; renderDemand(); };

// ---------- spread ----------
async function loadSpread() { state.spread = await getJSON("/api/spread"); renderSpread(); }

function barRow(text, value, max, href) {
  const row = el("div", "bar");
  const lab = href ? el("a", "bar__label", text) : el("span", "bar__label", text);
  if (href) { lab.href = href; lab.target = "_blank"; lab.rel = "noopener"; }
  lab.title = text;
  const track = el("div", "bar__track"); const fill = el("div", "bar__fill"); fill.style.width = `${max ? (value / max) * 100 : 0}%`; track.append(fill);
  row.append(lab, track, el("span", "bar__val", num(value)));
  return row;
}

function renderSpread() {
  const sp = state.spread, root = document.getElementById("spread");
  root.replaceChildren();
  const grid = el("div", "spread-grid");

  const press = el("div", "card");
  press.append(el("h3", "section-title", "Press pickup by publisher, 7 days"));
  const maxP = Math.max(1, ...sp.press_by_publisher.map((p) => p.stories));
  if (!sp.press_by_publisher.length) press.append(el("div", "empty", "No press stories in the last week"));
  for (const p of sp.press_by_publisher) press.append(barRow(p.publisher, p.stories, maxP));
  grid.append(press);

  const daily = el("div", "card");
  daily.append(el("h3", "section-title", "Press stories per day, 14 days"));
  const maxD = Math.max(1, ...sp.press_by_day.map((d) => d.stories));
  const cols = el("div", "cols");
  for (const d of sp.press_by_day) { const c = el("div", "col"); c.style.height = `${(d.stories / maxD) * 100}%`; c.title = `${shortDate(d.day)}: ${d.stories} ${d.stories === 1 ? "story" : "stories"}`; cols.append(c); }
  daily.append(cols);
  if (sp.press_by_day.length) { const labels = el("div", "cols__labels"); labels.append(el("span", null, shortDate(sp.press_by_day[0].day)), el("span", null, shortDate(sp.press_by_day[sp.press_by_day.length - 1].day))); daily.append(labels); }
  grid.append(daily);

  const reddit = el("div", "card");
  reddit.append(el("h3", "section-title", "Reddit, 7 days"));
  const stats = el("div", "stats");
  for (const [n, l] of [[sp.reddit.posts_7d, "posts on CTM topics"], [sp.reddit.mentions_7d, "mention Martin or MSE"]]) { const s = el("div", "stat"); s.append(el("div", "stat__num", String(n)), el("div", "stat__label", l)); stats.append(s); }
  reddit.append(stats);
  const rl = el("ul", "list");
  for (const p of sp.reddit.top) { const li = el("li"); const a = el("a", null, p.title); a.href = p.url; a.target = "_blank"; a.rel = "noopener"; li.append(a, el("span", "meta", `r/${p.subreddit} · ${num(p.score)} pts · ${num(p.comments)} comments`)); rl.append(li); }
  if (!sp.reddit.top.length) rl.append(el("li", "meta", "Nothing yet"));
  reddit.append(rl);
  grid.append(reddit);

  const yt = el("div", "card");
  yt.append(el("h3", "section-title", "YouTube, latest uploads"));
  const yl = el("ul", "list");
  for (const v of sp.youtube) { const li = el("li"); const a = el("a", null, v.title); a.href = v.url; a.target = "_blank"; a.rel = "noopener"; li.append(a, el("span", "meta", `${num(v.views)} views · ${ago(v.published_at)}`)); yl.append(li); }
  yt.append(yl);
  grid.append(yt);
  root.append(grid);

  const boards = el("div", "section");
  boards.append(el("h3", "section-title", "MSE forum boards: threads with a new comment"));
  const bgrid = el("div", "spread-grid");
  for (const b of sp.boards) {
    const card = el("div", "card");
    card.append(el("h3", null, b.board || "Unknown board"));
    const st = el("div", "stats");
    for (const [n, l] of [[b.active_24h, "active in 24h"], [b.active_7d, "active in 7 days"], [b.threads, "tracked"]]) { const s = el("div", "stat"); s.append(el("div", "stat__num", String(n)), el("div", "stat__label", l)); st.append(s); }
    card.append(st);
    const ul = el("ul", "list");
    for (const t of b.top) { const li = el("li"); const a = el("a", null, t.title); a.href = t.url; a.target = "_blank"; a.rel = "noopener"; li.append(a, el("span", "meta", `${num(t.comments)} comments · ${num(t.views)} views`)); ul.append(li); }
    card.append(ul);
    bgrid.append(card);
  }
  boards.append(bgrid);
  root.append(boards);
}

// ---------- sources ----------
async function loadSources() {
  const [summary, runs] = await Promise.all([getJSON("/api/summary"), getJSON("/api/runs?limit=25")]);
  state.summary = summary; state.runs = runs;
  renderLive(); renderSources();
}

function renderSources() {
  const root = document.getElementById("sources");
  root.replaceChildren();
  const table = el("table", "data");
  const head = el("tr");
  for (const h of ["Source", "Cadence", "Last run", "Result", "Next run", "Stored", "Notes"]) head.append(el("th", null, h));
  table.append(head);
  for (const s of state.summary.sources) {
    const row = el("tr");
    const src = el("td"); const wrap = el("span", "src"); wrap.append(icon((SOURCE_META[s.source] || {}).glyph || "press", "ico ico--lg"), document.createTextNode(s.label)); src.append(wrap); row.append(src);
    row.append(el("td", null, s.enabled ? cadence(s.every_minutes) : "off"));
    row.append(el("td", null, s.last_run ? `${fmtWhen(s.last_run.finished_at)} (${ago(s.last_run.finished_at)})` : "never"));
    const res = el("td");
    if (!s.enabled) res.append(el("span", "pill pill--off", "disabled"));
    else if (!s.last_run) res.append(el("span", "pill pill--off", "pending"));
    else { res.append(el("span", `pill ${s.last_run.ok ? "pill--ok" : "pill--bad"}`, s.last_run.ok ? "ok" : "failed")); if (s.last_run.ok) res.append(document.createTextNode(` ${s.last_run.items_new} new`)); }
    row.append(res);
    row.append(el("td", null, s.next_run ? `${fmtWhen(s.next_run)} (${until(s.next_run)})` : s.enabled ? "scheduler off" : ""));
    row.append(el("td", "num", s.total != null ? num(s.total) : ""));
    row.append(el("td", "err", !s.enabled ? s.reason : s.last_run && !s.last_run.ok ? s.last_run.error : ""));
    table.append(row);
  }
  root.append(table);

  if (state.summary.brian) {
    const b = state.summary.brian, usage = b.usage_today || {};
    const line = el("p", "lede", b.enabled
      ? `Brian: ${usage.calls || 0} calls today (${usage.by_kind ? Object.entries(usage.by_kind).map(([k, v]) => `${v} ${k}`).join(", ") : "none"}), about $${(usage.cost_usd || 0).toFixed(2)}. Model ${b.model}. Views are written once per item; the digest runs hourly when there is something new.`
      : "Brian is off: ANTHROPIC_API_KEY is not set.");
    root.append(line);
  }
  const topics = el("div", "section");
  topics.append(el("h3", "section-title", "How items get a CTM category"));
  topics.append(el("p", "lede", "An item is tagged with a category when its title or text contains one of these phrases as a whole word (case-insensitive). Brian will refine the tags once connected. Edit the lists in sources.yaml."));
  const tt = el("table", "data");
  const th = el("tr"); th.append(el("th", null, "Category"), el("th", null, "Phrases")); tt.append(th);
  for (const [t, phrases] of Object.entries(state.summary.topic_defs)) { const r = el("tr"); r.append(el("td", null, nice(t)), el("td", null, phrases.join(", "))); tt.append(r); }
  topics.append(tt);
  root.append(topics);

  const runs = el("div", "section");
  runs.append(el("h3", "section-title", "Recent runs"));
  const rt = el("table", "data");
  const rh = el("tr"); for (const h of ["When", "Source", "Result", "New items", "Error"]) rh.append(el("th", null, h)); rt.append(rh);
  for (const r of state.runs) {
    const row = el("tr");
    row.append(el("td", null, fmtWhen(r.finished_at || r.started_at)), el("td", null, label(r.source)));
    const res = el("td"); res.append(el("span", `pill ${r.ok ? "pill--ok" : "pill--bad"}`, r.ok ? "ok" : "failed")); row.append(res);
    row.append(el("td", "num", String(r.items_new ?? "")), el("td", "err", r.error || ""));
    rt.append(row);
  }
  runs.append(rt);
  root.append(runs);
}

// ---------- boot ----------
async function loadTab(name) {
  try {
    if (name !== "signals" && name !== "sources") { state.summary = await getJSON("/api/summary"); renderLive(); }
    if (name === "signals") await loadSignals();
    else if (name === "demand") await loadDemand();
    else if (name === "spread") await loadSpread();
    else if (name === "sources") await loadSources();
  } catch (err) {
    document.getElementById("live-text").textContent = "Cannot reach the API";
    console.error(err);
  }
}
let searchTimer = null;
document.getElementById("search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = e.target.value.trim(); loadSignals(); }, 300);
});
setTab(["signals", "demand", "spread", "sources"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "signals");
setInterval(() => { if (state.tab === "signals") loadSignals(); }, 60000);
