const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

function fmtDate(iso) {
  const d = new Date(iso);
  return (d.getMonth() + 1) + "/" + d.getDate() + " " +
    String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}

// 記事の一覧を描く。showCategory=false ならカテゴリの札を出さない
function renderNews(listEl, articles, showCategory = true) {
  const dayAgo = Date.now() - 24 * 3600 * 1000;
  listEl.replaceChildren(...articles.map((a) => {
    const li = el("li", "item");
    const link = el("a", null, a.title);
    link.href = a.link; link.target = "_blank"; link.rel = "noopener noreferrer";
    const meta = el("div", "meta");
    if (new Date(a.published).getTime() > dayAgo) meta.append(el("span", "new", "NEW"));
    if (a.brand) meta.append(el("span", "chip", a.brand));
    else if (showCategory) meta.append(el("span", "chip", a.category));
    meta.append(el("span", null, a.source || ""), el("span", null, fmtDate(a.published)));
    li.append(link, meta);
    return li;
  }));
}

// 1 系列の縦棒グラフ（SVG）。data = [[ラベル, 値], ...]
function barChart(box, data, unit) {
  const W = 640, H = 260, L = 8, R = 8, T = 24, B = 26;
  const max = Math.max(...data.map((d) => d[1])) * 1.1;
  const slot = (W - L - R) / data.length, bw = Math.min(44, slot * 0.6);
  const y = (v) => T + (H - T - B) * (1 - v / max);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  const mk = (name, attrs, text) => {
    const n = document.createElementNS(ns, name);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    svg.append(n);
    return n;
  };
  mk("line", { class: "gridline", x1: L, x2: W - R, y1: H - B, y2: H - B });
  const tip = document.querySelector(".tooltip") || document.body.appendChild(el("div", "tooltip"));
  const fmt = (v) => v.toLocaleString("ja-JP") + unit;
  data.forEach(([label, v], i) => {
    const cx = L + slot * i + slot / 2;
    const top = y(v), h = H - B - top;
    // 上側だけ角を丸めた棒（下端は基準線に接する）
    const r = Math.min(4, h);
    const x0 = cx - bw / 2, x1 = cx + bw / 2;
    const bar = mk("path", {
      class: "bar",
      d: `M${x0},${H - B} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x1 - r} Q${x1},${top} ${x1},${top + r} V${H - B} Z`,
    });
    mk("text", { class: "axis", x: cx, y: H - 8, "text-anchor": "middle" }, label);
    // 最初と最後の値だけ直接表示（全部に数字を付けない）
    if (i === 0 || i === data.length - 1) {
      mk("text", { class: "val", x: cx, y: top - 6, "text-anchor": "middle" }, v.toLocaleString("ja-JP"));
    }
    // 棒より広い当たり判定
    const hit = mk("rect", { x: L + slot * i, y: T, width: slot, height: H - T - B, fill: "transparent" });
    hit.addEventListener("mousemove", (e) => {
      bar.classList.add("active");
      tip.textContent = `${label}年：${fmt(v)}`;
      tip.style.display = "block";
      tip.style.left = e.clientX + 12 + "px";
      tip.style.top = e.clientY - 28 + "px";
    });
    hit.addEventListener("mouseleave", () => { bar.classList.remove("active"); tip.style.display = "none"; });
  });
  box.append(svg);
}
