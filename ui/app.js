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
  tab: "signals", source: null, q: "",
  summary: null, feed: [], insights: null, spread: null, runs: [],
  trends: {}, resolution: "weekly", martinPosts: null, showTable: false,
  expanded: new Set(), brianToggled: new Set(),
  showLow: false, hidden: 0, hideBelow: 3, run: null, scrollTo: null,
  openInsight: null, askOpen: false,
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
const nice = (topic) => (state.summary && state.summary.topic_labels && state.summary.topic_labels[topic]) || (topic || "").replace(/_/g, " ");
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
const tableBox = (table, wide = false) => { const box = el("div", "table-scroll" + (wide ? " table-scroll--wide" : "")); box.append(table); return box; };

// ---------- tabs ----------
function setTab(name) {
  state.tab = name;
  for (const b of document.querySelectorAll(".tab")) b.classList.toggle("is-active", b.dataset.tab === name);
  for (const p of document.querySelectorAll(".panel")) p.hidden = p.id !== `panel-${name}`;
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  loadTab(name);
}
for (const b of document.querySelectorAll(".tab")) b.onclick = () => setTab(b.dataset.tab);
document.querySelector(".brand").onclick = (e) => { e.preventDefault(); setTab("signals"); };

// ---------- signals ----------
async function loadSignals() {
  const params = new URLSearchParams({ limit: "150" });
  if (state.source) params.set("source", state.source);
  if (state.q) params.set("q", state.q);
  if (!state.showLow) params.set("hide_low", "1");
  const [summary, feed, insights, spread] = await Promise.all([
    getJSON("/api/summary"), getJSON(`/api/feed?${params}`), getJSON("/api/insights"), getJSON("/api/spread"),
  ]);
  state.summary = summary; state.feed = feed.items; state.insights = insights; state.spread = spread;
  state.hidden = feed.hidden || 0; state.hideBelow = feed.hide_below ?? state.hideBelow;
  renderLive(); renderHighlights(); renderFilters(); renderFeed();
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
}

const count = (n, one, many = `${one}s`) => (n === null || n === undefined ? "" : `${num(n)} ${n === 1 ? one : many}`);
function metricsFor(item) {
  const m = item.metrics || {}, parts = [];
  if (m.like_count !== undefined) { parts.push(count(m.like_count, "like"), count(m.retweet_count, "repost"), count(m.reply_count, "reply", "replies")); if (m.impression_count) parts.push(count(m.impression_count, "view")); }
  if (item.source === "instagram") { if (m.likes != null) parts.push(count(m.likes, "like")); if (m.comments != null) parts.push(count(m.comments, "comment")); if (m.views) parts.push(count(m.views, "play")); }
  if (item.source === "mse_forum") parts.push(count(m.comments, "comment"), count(m.views, "view"), m.board);
  if (item.source === "reddit") parts.push(count(m.score, "point"), count(m.comments, "comment"), `r/${m.subreddit}`);
  if (item.source === "youtube") parts.push(count(m.views, "view"), count(m.likes, "like"), count(m.comments, "comment"));
  if (item.source === "press" && m.via) parts.push(m.via.replace("_", " "));
  return parts.filter(Boolean);
}

// Brian's actions arrive as {lever, text} (older stored views have plain strings; both render).
function actionList(actions) {
  const ul = el("ul", "brian-view__actions");
  for (const a of actions) {
    const li = el("li");
    if (a && typeof a === "object" && a.lever) { const tag = el("span", `lever lever--${a.lever}`, a.lever); tag.title = LEVERS[a.lever] || ""; li.append(tag); }
    li.append(document.createTextNode(typeof a === "string" ? a : a.text || JSON.stringify(a)));
    ul.append(li);
  }
  return ul;
}
const LEVERS = { bids: "Paid search bids or query coverage", budgets: "Move spend between product lines or channels", targeting: "Programmatic audiences, contextual placements, YouTube or connected TV targeting", creative: "Ad copy, display, video or social creative that echoes the advice", content: "Landing pages, guides, SEO", pr: "Get named, respond, partner", watch: "Monitor, no spend yet" };
function impactList(impact) {
  const wrap = el("div", "brian-view__impacts");
  for (const i of impact) wrap.append(el("span", "impact", [nice(i.product), i.direction === "up" ? "▲ up" : i.direction === "down" ? "▼ down" : i.direction, i.magnitude, i.timing].filter(Boolean).join(" · ")));
  return wrap;
}

// The Martometer: a speedometer dial, relevance to CTM out of 10. Martin's face sits in the middle, the scale runs
// 0 to 10 around the outside and the needle points at the score. Scored on the server (app/relevance.py).
const DIAL = { w: 120, h: 106, cx: 60, cy: 66, r: 44, face: 19, start: 210, sweep: 240 };  // degrees, anticlockwise from east
function dialPoint(value, radius) {
  const deg = DIAL.start - (DIAL.sweep / 10) * value, rad = (deg * Math.PI) / 180;
  return [DIAL.cx + radius * Math.cos(rad), DIAL.cy - radius * Math.sin(rad)];
}
function dialArc(from, to, radius) {
  const [x0, y0] = dialPoint(from, radius), [x1, y1] = dialPoint(to, radius);
  const large = (to - from) * (DIAL.sweep / 10) > 180 ? 1 : 0;
  return `M${x0.toFixed(2)},${y0.toFixed(2)} A${radius},${radius} 0 ${large} 1 ${x1.toFixed(2)},${y1.toFixed(2)}`;
}
function martometer(item) {
  const m = item.martometer;
  if (!m) return null;
  const score = Math.max(0, Math.min(10, m.score));
  const box = el("div", "martometer" + (m.low ? " is-low" : ""));
  box.setAttribute("role", "meter"); box.setAttribute("aria-valuemin", "0"); box.setAttribute("aria-valuemax", "10"); box.setAttribute("aria-valuenow", String(m.score));
  box.setAttribute("aria-label", `Martometer ${m.score.toFixed(1)} out of 10`);
  box.title = `Martometer ${m.score.toFixed(1)} = 10 × Martin ${m.martin} (${m.who}${m.reach != null ? `, ${m.seen}` : ""}) × CTM ${m.ctm} (${m.why}). Click for how it works.`;
  box.onclick = (e) => { e.stopPropagation(); state.scrollTo = "martometer-explainer"; setTab("sources"); };
  const svg = svgEl("svg", { viewBox: `0 0 ${DIAL.w} ${DIAL.h}`, class: "speedo", "aria-hidden": "true" });
  const clipId = `mm-face-${item.id}`;
  const defs = svgEl("defs"); const clip = svgEl("clipPath", { id: clipId });
  clip.append(svgEl("circle", { cx: DIAL.cx, cy: DIAL.cy, r: DIAL.face })); defs.append(clip); svg.append(defs);
  // the scale: track, the low band, the filled arc up to the score
  svg.append(svgEl("path", { d: dialArc(0, 10, DIAL.r), class: "speedo__track" }));
  svg.append(svgEl("path", { d: dialArc(0, state.hideBelow || 3, DIAL.r), class: "speedo__lowband" }));
  if (score > 0.05) svg.append(svgEl("path", { d: dialArc(0, score, DIAL.r), class: "speedo__fill" }));
  // ticks and the numbers 0 to 10 around the outside
  for (let i = 0; i <= 10; i++) {
    const [x0, y0] = dialPoint(i, DIAL.r - 4.5), [x1, y1] = dialPoint(i, DIAL.r + 3.5);
    svg.append(svgEl("line", { x1: x0, y1: y0, x2: x1, y2: y1, class: "speedo__tick" }));
    const [lx, ly] = dialPoint(i, DIAL.r + 10);
    svg.append(svgText(lx.toFixed(1), (ly + 2.4).toFixed(1), String(i), "speedo__label", "middle"));
    if (i < 10) { const [a, b] = dialPoint(i + 0.5, DIAL.r - 2), [c, d] = dialPoint(i + 0.5, DIAL.r + 2.5); svg.append(svgEl("line", { x1: a, y1: b, x2: c, y2: d, class: "speedo__tick speedo__tick--minor" })); }
  }
  // Martin in the middle, on a white disc
  svg.append(svgEl("circle", { cx: DIAL.cx, cy: DIAL.cy, r: DIAL.face + 1.5, class: "speedo__disc" }));
  const fit = DIAL.face * 2 - 3;  // the drawing is taller than it is wide; "meet" keeps all of it inside the disc
  svg.append(svgEl("image", { href: "logo.png", x: DIAL.cx - fit / 2, y: DIAL.cy - fit / 2, width: fit, height: fit, preserveAspectRatio: "xMidYMid meet", "clip-path": `url(#${clipId})`, class: "speedo__face" }));
  // the needle: from the edge of the face out towards the scale, pivoting on him
  const deg = DIAL.start - (DIAL.sweep / 10) * score, rad = (deg * Math.PI) / 180;
  const ux = Math.cos(rad), uy = -Math.sin(rad), px = -uy, py = ux;
  const base = [DIAL.cx + ux * (DIAL.face + 2.5), DIAL.cy + uy * (DIAL.face + 2.5)], tip = [DIAL.cx + ux * (DIAL.r - 7), DIAL.cy + uy * (DIAL.r - 7)];
  const pts = [tip, [base[0] + px * 2.2, base[1] + py * 2.2], [base[0] - px * 2.2, base[1] - py * 2.2]].map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  svg.append(svgEl("polygon", { points: pts, class: "speedo__needle" }));
  svg.append(svgText(DIAL.cx, 6.5, "MARTOMETER", "speedo__name", "middle"));
  svg.append(svgText(DIAL.cx, DIAL.h - 3, m.score.toFixed(1), "speedo__num", "middle"));
  box.append(svg);
  return box;
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
  if (Array.isArray(b.impact) && b.impact.length) box.append(el("div", "brian-view__section", "Impact on CTM"), impactList(b.impact));
  if (Array.isArray(b.actions) && b.actions.length) box.append(el("div", "brian-view__section", "What CTM could do"), actionList(b.actions));
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
    state.brianToggled.delete(item.id);  // a fresh view opens by default
    card.replaceWith(renderItem(item));
  } catch (err) {
    if (btn) { btn.disabled = false; btn.replaceChildren(document.createTextNode(`Brian couldn't read it: ${err.message}`)); }
  }
}

function renderItem(item) {
  const meta = SOURCE_META[item.source] || { glyph: "press", open: "Open the source" };
  const card = el("article", "card item" + (item.martometer && item.martometer.low ? " is-low" : ""));
  card.dataset.id = item.id;
  const gauge = martometer(item);
  if (gauge) card.append(gauge);

  const head = el("div", "item__head");
  const badge = meta.home ? el("a", "badge") : el("span", "badge");
  if (meta.home) { badge.href = meta.home; badge.target = "_blank"; badge.rel = "noopener"; badge.title = `Open ${label(item.source)}`; }
  badge.append(icon(meta.glyph), document.createTextNode(label(item.source)));
  head.append(badge);
  if (item.author) head.append(el("span", null, item.author));
  for (const t of item.topics || []) { const tag = el("span", "topic", nice(t)); tag.title = "CTM category"; head.append(tag); }
  const bumped = item.metrics && item.metrics.last_comment_at && item.metrics.last_comment_at !== item.published_at;
  const when = item.url ? el("a", "item__time") : el("span", "item__time");
  when.textContent = (bumped ? "active " : "") + ago(item.activity_at || item.published_at || item.first_seen_at);
  when.title = fmtWhen(item.activity_at || item.published_at || item.first_seen_at);
  if (item.url) { when.href = item.url; when.target = "_blank"; when.rel = "noopener"; }
  head.append(when);
  card.append(head);

  if (item.title) {
    const h = el("h3", "item__title");
    if (item.url) { const a = el("a", null, item.title); a.href = item.url; a.target = "_blank"; a.rel = "noopener"; h.append(a); }
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
    const b = el("button", "btn btn--quiet" + (isOpen ? " is-on" : ""));
    b.append(document.createTextNode(isOpen ? "Show less" : item.kind === "article" ? "Read the full article" : item.kind === "guide_change" ? "Show the full change" : "Show the full post"));
    b.append(icon("chevron", "ico ico--sm ico--chev"));
    b.onclick = () => { if (isOpen) state.expanded.delete(item.id); else state.expanded.add(item.id); card.replaceWith(renderItem(item)); };
    foot.append(b);
  }
  const brianOn = state.insights?.brian_enabled;
  const brianOpen = !!item.brian !== state.brianToggled.has(item.id);  // default open when a view exists; a click flips it
  const toggleBrian = () => { if (state.brianToggled.has(item.id)) state.brianToggled.delete(item.id); else state.brianToggled.add(item.id); card.replaceWith(renderItem(item)); };
  const bb = el("button", "btn btn--brian" + (brianOpen ? " is-on" : ""));
  const bimg = el("img"); bimg.src = "brian.png"; bimg.alt = "";
  if (item.brian) {
    bb.append(bimg, document.createTextNode(item.brian.relevance === "none" ? "Brian: not one for CTM" : "Brian's view"), icon("chevron", "ico ico--sm ico--chev"));
    bb.onclick = toggleBrian;
  } else if (brianOn) {
    bb.append(bimg, document.createTextNode("Ask Brian about this"));
    bb.onclick = () => askBrianAbout(item, card);
  } else {
    bb.append(bimg, document.createTextNode("Brian's view (not yet)"), icon("chevron", "ico ico--sm ico--chev"));
    bb.onclick = toggleBrian;
  }
  foot.append(bb);
  const metrics = el("div", "item__metrics");
  for (const part of metricsFor(item)) metrics.append(el("span", null, part));
  foot.append(metrics);
  card.append(foot);
  if (brianOpen) card.append(brianView(item));
  return card;
}

function renderFeed() {
  const feed = document.getElementById("feed");
  feed.replaceChildren();
  const hidden = state.hidden, lowShown = state.feed.filter((i) => i.martometer && i.martometer.low).length;
  if ((!state.showLow && hidden) || (state.showLow && lowShown)) {
    const note = el("div", "feed-note");
    note.append(document.createTextNode(state.showLow
      ? `Showing everything, including ${lowShown} low-relevance ${lowShown === 1 ? "item" : "items"} (Martometer under ${state.hideBelow}).`
      : `${hidden} low-relevance ${hidden === 1 ? "item" : "items"} hidden (Martometer under ${state.hideBelow}).`));
    const link = el("button", "link", state.showLow ? "Hide them" : "Show them");
    link.onclick = () => setShowLow(!state.showLow);
    note.append(link);
    feed.append(note);
  }
  if (!state.feed.length) { feed.append(el("div", "empty", hidden ? "Nothing above the relevance line here. Switch on \"Show low relevance\" to see the rest." : "Nothing matches. Try another source, category or search.")); return; }
  for (const item of state.feed) feed.append(renderItem(item));
}
function setShowLow(on) { state.showLow = on; document.getElementById("show-low").checked = on; loadSignals(); }
document.getElementById("show-low").onchange = (e) => setShowLow(e.target.checked);

// Brian's Highlights: one section at the top of the page. The header carries Brian's read of the last 24 hours and
// the day's counts; beneath it, one headline per channel (Search, Programmatic, SEO), newest per channel, then anything
// else worth a line, five at most. Click a headline for the detail; one open at a time. Ask Brian sits at the foot.
const MAX_HEADLINES = 5;
const CHANNELS = { search: "Search", programmatic: "Programmatic", seo: "SEO" };
function pickHighlights(all) {
  const byChannel = {}, others = [], seen = new Set();
  for (const ins of all) {  // newest first from the API
    const key = (ins.headline || "").trim().toLowerCase();
    if (!key || seen.has(key)) continue;  // the digest can restate a headline across runs; show it once
    seen.add(key);
    if (CHANNELS[ins.channel]) { if (!byChannel[ins.channel]) byChannel[ins.channel] = ins; }
    else others.push(ins);
  }
  return [...Object.keys(CHANNELS).map((c) => byChannel[c]).filter(Boolean), ...others].slice(0, MAX_HEADLINES);
}

function renderHighlights() {
  const root = document.getElementById("highlights");
  const s = state.summary, by = s.by_item_source || {};
  const enabled = !!state.insights?.brian_enabled;
  const list = pickHighlights(state.insights?.insights || []);
  const onX = by.x_martinslewis?.last_24h || 0, onInsta = by.instagram?.last_24h || 0, martin = onX + onInsta;
  const press = by.press?.last_24h || 0;
  const forum = (state.spread?.boards || []).reduce((a, b) => a + (b.active_24h || 0), 0);
  // Rebuild everything except the Ask Brian box, which keeps its question and answer across the minute refresh.
  for (const c of Array.from(root.children)) if (c !== askNode) c.remove();

  const head = el("div", "highlights__head");
  const img = el("img", "highlights__avatar"); img.src = "brian.png"; img.alt = "Brian";
  const titles = el("div", "highlights__titles");
  titles.append(el("div", "highlights__title", "Brian's Highlights"));
  const readAt = state.insights?.read_at;
  titles.append(el("div", "highlights__sub", !enabled ? "Waiting for the Anthropic key" : readAt ? `Last 24 hours · updated ${ago(readAt)}` : "Last 24 hours · first read lands within the hour"));
  head.append(img, titles);

  const stats = el("div", "highlights__stats");
  const stat = (n, text, title) => { const d = el("div", "hl-stat"); d.append(el("b", null, String(n)), el("span", null, text)); d.title = title; return d; };
  stats.append(stat(martin, martin === 1 ? "Martin post" : "Martin posts", `${onX} on X and ${onInsta} on Instagram in the last 24 hours`));
  stats.append(stat(press, press === 1 ? "press story" : "press stories", "Stories mentioning Martin Lewis in the last 24 hours (Google News and Bing, GB edition)"));
  stats.append(stat(forum, forum === 1 ? "forum thread" : "forum threads", "MSE forum threads with a new comment in the last 24 hours"));
  head.append(stats);
  if (enabled) {
    const ask = el("button", "btn btn--brian" + (state.askOpen ? " is-on" : ""));
    const bimg = el("img"); bimg.src = "brian.png"; bimg.alt = "";
    ask.append(bimg, document.createTextNode("Ask Brian"), icon("chevron", "ico ico--sm ico--chev"));
    ask.setAttribute("aria-expanded", String(state.askOpen));
    ask.onclick = () => { state.askOpen = !state.askOpen; renderHighlights(); if (state.askOpen) askBox().querySelector("textarea").focus(); };
    head.append(ask);
  }
  // Brian's read of the window, or the counted sentence until he has written one.
  const brianRead = s.brian && s.brian.read;
  const counted = [
    martin ? `Martin posted ${martin} ${martin === 1 ? "time" : "times"} on X and Instagram.` : "Martin has not posted on X or Instagram in the last 24 hours.",
    `${press} press ${press === 1 ? "story" : "stories"} mentioned him and ${forum} forum ${forum === 1 ? "thread was" : "threads were"} active.`,
  ].join(" ");
  const long = !!brianRead && brianRead.length > 300;  // reads written before the 45-word cap
  const readEl = el("p", "highlights__read" + (long ? " is-clamped" : ""), brianRead || counted);
  if (long) { readEl.title = "Click to read all of it"; readEl.onclick = () => readEl.classList.toggle("is-clamped"); }
  head.append(readEl);
  if (!brianRead) head.append(el("p", "highlights__note", enabled ? "Counted from the feed. Brian's first read lands within the hour." : "Counted from the feed. Brian's own read arrives once the Anthropic key is connected."));
  root.append(head);

  if (!list.length) {
    const wait = el("div", "highlights__waiting");
    wait.append(el("p", null, enabled ? "No highlights written yet. The first pass runs within the hour." : "Once the key is in, Brian reads the new signals every hour and writes here what they mean for Compare the Market:"));
    const ul = el("ul");
    for (const t of ["Which product line is affected, and which way demand moves", "One recommendation each for Search, Programmatic and SEO", "The evidence behind each, linked"]) ul.append(el("li", null, t));
    wait.append(ul);
    root.append(wait);
  } else {
    const ol = el("ol", "headlines");
    for (const ins of list) ol.append(headlineRow(ins));
    root.append(ol);
  }
  if (enabled) { const box = askBox(); box.hidden = !state.askOpen; if (box.parentNode !== root) root.append(box); }
  else if (askNode && askNode.parentNode === root) askNode.remove();
}

function headlineRow(ins) {
  const open = state.openInsight === ins.id;
  const li = el("li", "headline" + (open ? " is-open" : ""));
  const btn = el("button", "headline__btn");
  btn.setAttribute("aria-expanded", String(open));
  btn.setAttribute("aria-controls", `insight-${ins.id}`);
  const channel = CHANNELS[ins.channel];
  btn.append(el("span", "channel " + (channel ? `channel--${ins.channel}` : "channel--other"), channel || "Also"), el("span", "headline__text", ins.headline || ""));
  const meta = el("span", "headline__meta");
  const levers = [...new Set((ins.actions || []).map((a) => a && typeof a === "object" && a.lever).filter(Boolean))];
  for (const l of levers.slice(0, 3)) { const tag = el("span", `lever lever--${l}`, l); tag.title = LEVERS[l] || ""; meta.append(tag); }
  meta.append(el("span", "headline__when", ago(ins.created_at)));
  btn.append(meta, icon("chevron", "ico ico--sm headline__chev"));
  btn.onclick = () => { state.openInsight = open ? null : ins.id; renderHighlights(); };
  li.append(btn);

  const detail = el("div", "headline__detail"); detail.id = `insight-${ins.id}`; detail.hidden = !open;
  if (ins.body) detail.append(el("p", "headline__body", ins.body));
  if (Array.isArray(ins.impact) && ins.impact.length) detail.append(el("div", "brian-view__section", "Impact on CTM"), impactList(ins.impact));
  if (Array.isArray(ins.actions) && ins.actions.length) detail.append(el("div", "brian-view__section", "What CTM could do"), actionList(ins.actions));
  const foot = el("div", "insight__evidence");
  const evidence = Array.isArray(ins.evidence) ? ins.evidence.slice(0, 5) : [];
  if (ins.confidence) foot.append(document.createTextNode(`Confidence ${ins.confidence}${evidence.length ? " · " : ""}`));
  if (evidence.length) {
    foot.append(document.createTextNode("Evidence: "));
    evidence.forEach((id, i) => { if (i) foot.append(document.createTextNode(", ")); const a = el("a", null, `#${id}`); a.href = `/api/items/${id}`; a.target = "_blank"; a.rel = "noopener"; a.title = "Open the stored item"; foot.append(a); });
  }
  if (foot.childNodes.length) detail.append(foot);
  li.append(detail);
  return li;
}

let askNode = null;
function askBox() {
  if (askNode) return askNode;
  const box = askNode = el("div", "ask");
  box.append(el("div", "section-title", "Ask Brian"));
  const ta = el("textarea", "ask__input"); ta.placeholder = "e.g. Should we raise car insurance bids this week?"; ta.rows = 2; ta.maxLength = 500;
  const row = el("div", "ask__row");
  const send = el("button", "btn btn--primary", "Ask");
  const out = el("div", "ask__answer"); out.hidden = true;
  const suggestions = el("div", "filters");
  for (const q of ["What should CTM do about energy this week?", "What should the programmatic team run this week?", "Which product line is most exposed right now?"]) {
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
  // One post in the period: the dot opens it. Several: the dot lists them in a popover, each a link.
  const pop = el("div", "chart__pop"); pop.hidden = true;
  const showPosts = (i, items) => {
    pop.replaceChildren();
    const head = el("div", "chart__pop-head");
    head.append(el("span", null, `${items.length} Martin posts, ${series[i].label}`));
    const close = el("button", "chart__pop-close", "×"); close.title = "Close"; close.onclick = (e) => { e.stopPropagation(); pop.hidden = true; };
    head.append(close); pop.append(head);
    for (const p of items) {
      const a = el("a", "chart__pop-link"); a.href = p.url; a.target = "_blank"; a.rel = "noopener";
      a.append(icon((SOURCE_META[p.source] || {}).glyph || "x", "ico ico--sm"), el("span", null, (p.text || p.title || "Open the post").replace(/\s+/g, " ").slice(0, 110)), icon("external", "ico ico--sm ico--out"));
      pop.append(a);
    }
    // keep the popover inside the card: it is 280px wide and centred on the dot
    const cardW = container.clientWidth || 340, half = 150;
    pop.style.left = `${Math.max(half, Math.min(cardW - half, (x(i) / W) * cardW))}px`;
    pop.hidden = false;
  };
  container.onclick = (e) => { if (!pop.hidden && !pop.contains(e.target)) pop.hidden = true; };
  for (const [i, items] of groups) {
    const g = svgEl("g", { class: "chart__marker" });
    g.append(svgEl("circle", { cx: x(i), cy: y(series[i].value), r: 6, class: "chart__marker-ring" }));
    const dot = svgEl("circle", { cx: x(i), cy: y(series[i].value), r: 4.5, class: "chart__marker-dot", role: "link", tabindex: "0" });
    const title = svgEl("title"); title.textContent = items.map((p) => (p.text || "").slice(0, 120)).join("\n\n"); dot.append(title);
    const open = (e) => { e.stopPropagation(); if (items.length === 1) window.open(items[0].url, "_blank", "noopener"); else showPosts(i, items); };
    dot.onclick = open;
    dot.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(e); } };
    g.append(dot);
    if (items.length > 1) g.append(svgText(x(i), y(series[i].value) - 10, String(items.length), "chart__marker-label", "middle"));
    svg.append(g);
  }
  const cross = svgEl("line", { class: "chart__cross", y1: padT, y2: H - padB, x1: 0, x2: 0, style: "display:none" });
  const hdot = svgEl("circle", { class: "chart__hover-dot", r: 4, style: "display:none" });
  svg.append(cross, hdot);
  const tip = el("div", "chart__tip"); tip.style.display = "none";
  container.append(svg, tip, pop);
  svg.addEventListener("mousemove", (e) => {
    const rect = svg.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0, dist = Infinity;
    for (let i = 0; i < n; i++) { const d = Math.abs(x(i) - px); if (d < dist) { dist = d; best = i; } }
    cross.setAttribute("x1", x(best)); cross.setAttribute("x2", x(best)); cross.style.display = "";
    hdot.setAttribute("cx", x(best)); hdot.setAttribute("cy", y(series[best].value)); hdot.style.display = "";
    tip.replaceChildren(document.createTextNode(`${series[best].label}: ${series[best].value ?? "n/a"}`));
    const here = groups.get(best);
    if (here) tip.append(el("small", null, here.length === 1 ? "1 Martin post · click the dot to open it" : `${here.length} Martin posts · click the dot to list them`));
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
    if (t.topic) left.append(el("span", "topic", nice(t.topic)));
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
  const holder = document.getElementById("demand-table");
  holder.replaceChildren();
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
    holder.append(tableBox(table, true));
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

const whenCell = (iso, text) => { const td = el("td", null, text); if (iso) td.title = fmtWhen(iso); return td; };
// Error text stays on one line; the full message is on hover.
const errCell = (text) => { const td = el("td", "err", text || ""); if (text) td.title = text; return td; };
function renderSources() {
  const root = document.getElementById("sources");
  root.replaceChildren();
  const table = el("table", "data");
  const head = el("tr");
  for (const h of ["Source", "Cadence", "Last run", "Result", "Next run", "Stored", "Notes", "Run"]) head.append(el("th", null, h));
  table.append(head);
  const running = state.run && state.run.running;
  for (const s of state.summary.sources) {
    const row = el("tr");
    const src = el("td"); const wrap = el("span", "src"); wrap.append(icon((SOURCE_META[s.source] || {}).glyph || "press", "ico ico--lg"), document.createTextNode(s.label)); src.append(wrap); row.append(src);
    row.append(el("td", null, s.enabled ? cadence(s.every_minutes) : "off"));
    row.append(whenCell(s.last_run && s.last_run.finished_at, s.last_run ? ago(s.last_run.finished_at) : "never"));
    const res = el("td");
    if (!s.enabled) res.append(el("span", "pill pill--off", "disabled"));
    else if (!s.last_run) res.append(el("span", "pill pill--off", "pending"));
    else { res.append(el("span", `pill ${s.last_run.ok ? "pill--ok" : "pill--bad"}`, s.last_run.ok ? "ok" : "failed")); if (s.last_run.ok) res.append(document.createTextNode(` ${s.last_run.items_new} new`)); }
    row.append(res);
    row.append(whenCell(s.next_run, s.next_run ? until(s.next_run) : s.enabled ? "scheduler off" : ""));
    row.append(el("td", "num", s.total != null ? num(s.total) : ""));
    row.append(errCell(!s.enabled ? s.reason : s.last_run && !s.last_run.ok ? s.last_run.error : ""));
    const runCell = el("td");
    if (s.enabled) {
      const b = el("button", "btn btn--row-run", running && state.run.current === s.source ? "Running…" : "Run");
      b.disabled = !!running; b.title = `Run ${s.label} now (admin token)`;
      b.onclick = () => runNow([s.source]);
      runCell.append(b);
    }
    row.append(runCell);
    table.append(row);
  }
  root.append(tableBox(table, true));

  if (state.summary.brian) {
    const b = state.summary.brian, usage = b.usage_today || {};
    const line = el("p", "lede", b.enabled
      ? `Brian: ${usage.calls || 0} calls today (${usage.by_kind ? Object.entries(usage.by_kind).map(([k, v]) => `${v} ${k}`).join(", ") : "none"}), about $${(usage.cost_usd || 0).toFixed(2)}. Model ${b.model}. Views are written once per item; the digest runs hourly when there is something new.`
      : "Brian is off: ANTHROPIC_API_KEY is not set.");
    root.append(line);
  }
  const topics = el("details", "explainer");
  topics.append(el("summary", null, "How items get a CTM category"));
  topics.append(el("p", "lede", "One category per Compare the Market sub-brand, named as in the CTM dashboard. An item is tagged when its title or text contains one of these phrases as a whole word (case-insensitive, plurals allowed). Brian's View gives his own corrected categories. Edit the lists in sources.yaml."));
  const tt = el("table", "data");
  const th = el("tr"); th.append(el("th", null, "Sub-brand"), el("th", null, "Phrases")); tt.append(th);
  for (const [t, phrases] of Object.entries(state.summary.topic_defs)) { const r = el("tr"); r.append(el("td", null, nice(t)), el("td", null, phrases.join(", "))); tt.append(r); }
  topics.append(tableBox(tt));
  root.append(topics);
  renderMartometerExplainer(root);

  const runs = el("div", "section");
  runs.append(el("h3", "section-title", "Recent runs"));
  const rt = el("table", "data");
  const rh = el("tr"); for (const h of ["When", "Source", "Result", "New items", "Error"]) rh.append(el("th", null, h)); rt.append(rh);
  for (const r of state.runs) {
    const row = el("tr");
    row.append(el("td", null, fmtWhen(r.finished_at || r.started_at)), el("td", null, label(r.source)));
    const res = el("td"); res.append(el("span", `pill ${r.ok ? "pill--ok" : "pill--bad"}`, r.ok ? "ok" : "failed")); row.append(res);
    row.append(el("td", "num", String(r.items_new ?? "")), errCell(r.error || ""));
    rt.append(row);
  }
  runs.append(tableBox(rt, true));
  root.append(runs);
}

function renderMartometerExplainer(root) {
  const x = state.summary.martometer;
  if (!x) return;
  const voice = x.voice || {}, refs = x.reach_refs || {}, floor = x.reach_floor ?? 0.7, brian = x.ctm_brian || {}, kw = x.ctm_keywords || {};
  const sec = el("details", "explainer"); sec.id = "martometer-explainer";
  sec.append(el("summary", null, "How the Martometer works"));
  sec.append(el("p", "lede", `Every card carries a Martometer: how relevant that item is to Compare the Market's business, out of 10. It is a multiple of two factors, how much the item has to do with Martin and how much it has to do with CTM, so a Martin post about pensions and a forum thread about broadband that never mentions him both score low: each is missing one half. The feed hides anything under ${x.hide_below} unless "Show low relevance" is switched on.`));
  sec.append(el("pre", "formula", `Martometer = 10 × Martin × CTM\nMartin     = voice × (${floor} + ${(1 - floor).toFixed(1)} × reach)        who is speaking, nudged by how far it travelled\nCTM        = Brian's call if he has read it, else keywords   is it CTM's business?`));

  const grid = el("div", "spread-grid");
  const mcard = el("div", "card");
  mcard.append(el("h3", "section-title", "Martin factor: who is speaking (voice, 0 to 1)"));
  const vt = el("table", "data"); const vh = el("tr"); vh.append(el("th", null, "Who"), el("th", "num", "Voice")); vt.append(vh);
  for (const [text, v] of [
    ["Martin's own channels: X, Instagram, YouTube", voice.martin], ["MSE's official output: MSE on X, MSE news, guide changes", voice.mse],
    ["A national press story about him", voice.press], ["A forum or Reddit thread that names Martin or MSE", voice.names_martin],
    ["Any other MSE forum thread", voice.forum], ["Any other Reddit post", voice.reddit],
  ]) { const r = el("tr"); r.append(el("td", null, text), el("td", "num", String(v))); vt.append(r); }
  mcard.append(tableBox(vt));
  const ref = (k) => refs[k] || {};
  mcard.append(el("p", "lede small", `Reach is relative to what is normal for each source, on a log scale: a typical post scores 0.5, a big day scores 1, and a post as far below typical as a big day is above it scores 0. Typical and big day: X ${num(ref("x").typical)} and ${num(ref("x").big)} impressions, Instagram ${num(ref("instagram").typical)} and ${num(ref("instagram").big)} plays, YouTube ${num(ref("youtube").typical)} and ${num(ref("youtube").big)} views, MSE forum ${num(ref("mse_forum").typical)} and ${num(ref("mse_forum").big)} comments, Reddit ${num(ref("reddit").typical)} and ${num(ref("reddit").big)} points and comments. A post nobody has seen keeps ${Math.round(floor * 100)}% of its voice score and reach decides the rest, so Martin's loud moments float up and his quiet ones sit near the line. Press, MSE news and guide changes carry no engagement numbers and take the midpoint. X engagement is re-read at 1, 6 and 24 hours, so a post's score climbs through the day.`));
  grid.append(mcard);

  const ccard = el("div", "card");
  ccard.append(el("h3", "section-title", "CTM factor: is it CTM's business? (0 to 1)"));
  const ct = el("table", "data"); const ch = el("tr"); ch.append(el("th", null, "Evidence"), el("th", "num", "CTM")); ct.append(ch);
  for (const [text, v] of [
    ["Brian has read it and says relevance high", brian.high], ["Brian says medium", brian.medium], ["Brian says low", brian.low], ["Brian says none: not one for CTM", brian.none],
    ["Not read yet: two or more CTM categories matched by keyword", kw["2"]], ["Not read yet: one category matched", kw["1"]], ["Not read yet: no category matched", kw["0"]],
  ]) { const r = el("tr"); r.append(el("td", null, text), el("td", "num", String(v))); ct.append(r); }
  ccard.append(tableBox(ct));
  ccard.append(el("p", "lede small", "Brian's call wins once he has read the item, because the keyword tags are only a first pass: a Reddit thread about a utility on someone's credit file matches Credit cards, and Brian will say it is not one for CTM. Asking Brian about an item therefore re-scores it."));
  grid.append(ccard);
  sec.append(grid);

  // Worked examples, computed here with the same formula and constants so they can never drift from the real scores.
  const reach = (n, r) => (!r || !n ? 0 : Math.max(0, Math.min(1, 0.5 + 0.5 * Math.log(n / r.typical) / Math.log(r.big / r.typical))));
  const martin = (v, r) => v * (floor + (1 - floor) * (r == null ? 0.5 : r));
  const ex = el("div", "card");
  ex.append(el("h3", "section-title", "Worked examples (made with the numbers above)"));
  const et = el("table", "data"); const eh = el("tr");
  for (const h of ["Item", "Martin", "CTM", "Martometer", "In the feed by default?"]) eh.append(el("th", h === "Item" || h.startsWith("In") ? null : "num", h)); et.append(eh);
  for (const [text, m, c] of [
    ["Martin's Instagram video on the January energy cap forecast, 200k plays, Brian: high", martin(voice.martin, reach(200000, refs.instagram)), brian.high],
    ["Martin on X about mortgage deals ending, 170k impressions, not read yet, keyword Mortgages", martin(voice.martin, reach(170000, refs.x)), kw["1"]],
    ["The same mortgage post if it had only reached 3k impressions", martin(voice.martin, reach(3000, refs.x)), kw["1"]],
    ["A Martin post that hits a million impressions on a CTM topic, Brian: high", martin(voice.martin, reach(1000000, refs.x)), brian.high],
    ["Martin on X about the State Pension triple lock, 300k impressions, Brian: none", martin(voice.martin, reach(300000, refs.x)), brian.none],
    ["A regional paper on Martin's six-month mortgage rule, keyword Mortgages", martin(voice.press, null), kw["1"]],
    ["An MSE forum thread on the Energy board quoting Martin, 6 comments, keyword Energy", martin(voice.names_martin, reach(6, refs.mse_forum)), kw["1"]],
    ["An MSE forum thread about moving from BT to Sky, 4 comments, Martin not named, keyword Broadband", martin(voice.forum, reach(4, refs.mse_forum)), kw["1"]],
    ["A Reddit post about a utility on a credit file, 27 points and comments, Martin not named, Brian: none", martin(voice.reddit, reach(27, refs.reddit)), brian.none],
  ]) {
    const s = Math.round(10 * m * c * 10) / 10;
    const r = el("tr");
    r.append(el("td", null, text), el("td", "num", m.toFixed(2)), el("td", "num", String(c)), el("td", "num", s.toFixed(1)), el("td", s >= x.hide_below ? "shown-yes" : "shown-no", s >= x.hide_below ? "Yes" : "Hidden"));
    et.append(r);
  }
  ex.append(tableBox(et, true));
  sec.append(ex);
  sec.append(el("p", "lede small", "The numbers live in sources.yaml under martometer; this page reads them from there, and scores are worked out when items are read, so a change shows at once."));
  root.append(sec);
  if (state.scrollTo === "martometer-explainer") { state.scrollTo = null; sec.open = true; requestAnimationFrame(() => sec.scrollIntoView({ behavior: "smooth", block: "start" })); }
}

// ---------- run now ----------
// The button posts to /api/run/all with the admin token (typed once, kept for this tab only) and follows
// /api/run/status until the queue is done. The token check is on the server; the page never spends on its own.
const TOKEN_KEY = "mm_admin_token";
function adminToken() {
  let t = sessionStorage.getItem(TOKEN_KEY);
  if (!t) {
    t = window.prompt("Admin token (the server's ADMIN_TOKEN). Kept in this tab only.");
    if (!t || !t.trim()) return null;
    sessionStorage.setItem(TOKEN_KEY, t.trim());
  }
  return sessionStorage.getItem(TOKEN_KEY);
}
async function runNow(sources) {
  const token = adminToken();
  if (!token) return;
  const query = sources && sources.length ? `?sources=${encodeURIComponent(sources.join(","))}` : "";
  let r;
  try { r = await fetch(`/api/run/all${query}`, { method: "POST", headers: { "X-Admin-Token": token } }); }
  catch (err) { alert(`Could not reach the API: ${err.message}`); return; }
  if (r.status === 401) { sessionStorage.removeItem(TOKEN_KEY); alert("That admin token was not accepted. Click Run now to try again."); return; }
  if (r.status === 409) { pollRun(); return; }  // already running: just follow it
  if (!r.ok) { let detail = r.statusText; try { detail = (await r.json()).detail || detail; } catch (_) {} alert(`Could not start the run: ${detail}`); return; }
  state.run = await r.json();
  renderRun();
  pollRun();
}
let runTimer = null;
async function pollRun() {
  clearTimeout(runTimer);
  let status;
  try { status = await getJSON("/api/run/status"); } catch (_) { return; }
  const wasRunning = state.run && state.run.running;
  state.run = status;
  renderRun();
  if (status.running) runTimer = setTimeout(pollRun, 2000);
  else if (wasRunning) {
    await loadTab(state.tab);
    const fresh = status.done.reduce((a, d) => a + (d.new || 0), 0), failed = status.done.filter((d) => !d.ok).length;
    document.getElementById("live-text").textContent = `Ran ${status.done.length} ${status.done.length === 1 ? "source" : "sources"}: ${fresh} new${failed ? `, ${failed} failed (see Sources)` : ""}`;
  }
}
function renderRun() {
  const btn = document.getElementById("run-now"), r = state.run, running = !!(r && r.running);
  const name = (s) => ((state.summary && state.summary.sources) || []).find((x) => x.source === s)?.label || s;
  btn.classList.toggle("is-running", running);
  btn.disabled = running;
  btn.replaceChildren(icon("play", "ico"), el("span", "btn__label", running ? `Running ${name(r.current)}… (${r.done.length + 1} of ${r.done.length + 1 + r.queue.length})` : "Run now"));
  if (state.tab === "sources" && state.summary) renderSources();
}
document.getElementById("run-now").onclick = () => runNow();

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
pollRun();  // pick up a run started from another tab
setInterval(() => { if (state.tab === "signals") loadTab("signals"); }, 60000);  // loadTab catches a dead API and says so in the top bar
