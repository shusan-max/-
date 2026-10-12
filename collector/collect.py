"""子供服関連ニュースを Google ニュースの RSS から集め、
ブラウザで見られる 3 つのページを docs/ に作るスクリプト。

  docs/index.html   … ニュース一覧
  docs/market.html  … 子供服の市場環境（market.json の統計＋市場ニュース）
  docs/brands.html  … SNS ブランド分析（brands.json の分析＋ブランドニュース）

使い方:  python collector/collect.py
         python collector/collect.py --offline   （ニュースを取りに行かず、ページだけ作り直す）
外部ライブラリ不要（Python 3.9 以上の標準機能のみ）。
"""

import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
BRANDS_PATH = ROOT / "brands.json"
MARKET_PATH = ROOT / "market.json"
DOCS = ROOT / "docs"
DATA_PATH = DOCS / "data.json"
TEMPLATES = Path(__file__).resolve().parent / "templates"

JST = timezone(timedelta(hours=9))
FEED_URL = "https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"
PAGES = [("index.html", "ニュース"), ("market.html", "市場環境"), ("brands.html", "SNSブランド分析")]


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------- 収集 ----------

def fetch_feed(query):
    url = FEED_URL.format(q=urllib.parse.quote(f"{query} when:7d"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (info-collector)"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def parse_feed(xml_bytes, limit):
    items = []
    for item in list(ET.fromstring(xml_bytes).iter("item"))[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "").strip()
        # Google ニュースのタイトル末尾の「 - 媒体名」を取り除く
        if source and title.endswith(f" - {source}"):
            title = title[: -len(f" - {source}")]
        try:
            published = parsedate_to_datetime(item.findtext("pubDate")).astimezone(JST)
        except (TypeError, ValueError):
            published = datetime.now(JST)
        if title and link:
            items.append({"title": title, "link": link, "source": source, "published": published.isoformat()})
    return items


def build_queries(config, brands):
    """(カテゴリ名, 検索語) の一覧。ブランドは別名ごとに「"名前" 子供服」で検索する。"""
    queries = [(c["name"], kw) for c in config["categories"] for kw in c["keywords"]]
    for b in brands:
        queries += [(config["brand_category"], f'"{alias}" 子供服') for alias in b["aliases"]]
    return queries


# ---------- 絞り込み ----------

def contains_any(text, words):
    low = text.lower()
    return any(w.lower() in low for w in words)


def find_brand(title, brands, kids_terms):
    for b in brands:
        if contains_any(title, b["aliases"]):
            # 「ウルル」のように一般的な言葉と紛らわしいブランドは、子供服関連の言葉も必須にする
            if not b.get("match_with_kids_term") or contains_any(title, kids_terms):
                return b["name"]
    return None


def classify(article, config, brands):
    """関係ない記事なら None、関係ある記事ならカテゴリ等を付けて返す。"""
    rel = config["relevance"]
    title = article["title"]
    if contains_any(title, rel["exclude_any"]):
        return None
    brand = find_brand(title, brands, rel["include_any"])
    if brand:
        return {**article, "category": config["brand_category"], "brand": brand}
    if article.get("category") == config["brand_category"]:
        return None  # ブランド検索で拾ったがブランド名がタイトルにない記事は不採用
    if article.get("category") not in [c["name"] for c in config["categories"]]:
        return None  # 設定から消えたカテゴリの古い記事
    if not contains_any(title, rel["include_any"]):
        return None
    return {**article, "brand": None}


def normalize(title):
    # 【中国】（NNA）［繊維］などの括弧書きや記号を除いて比較しやすくする
    title = re.sub(r"[【\[［(（〈《].*?[】\]］)）〉》]", "", title)
    return re.sub(r"[\s　・、。,.!！?？「」『』|｜:：…\-−–—~〜]", "", title).lower()


def is_duplicate(a, b):
    if not a or not b:
        return a == b
    if a in b or b in a:
        return min(len(a), len(b)) >= 12
    return SequenceMatcher(None, a, b).ratio() >= 0.75


def dedupe(articles):
    kept, keys = [], []
    for a in articles:  # 新しい順に並んでいる前提。先に来たもの（新しい方）を残す
        key = normalize(a["title"])
        if any(is_duplicate(key, k) for k in keys):
            continue
        kept.append(a)
        keys.append(key)
    return kept


def merge(old, new, config, brands):
    cutoff = datetime.now(JST) - timedelta(days=config.get("keep_days", 30))
    by_link = {a["link"]: a for a in old + new}  # 新しく取得したものを優先
    articles = []
    for a in by_link.values():
        if datetime.fromisoformat(a["published"]) < cutoff:
            continue
        # 過去分も含めて毎回判定し直す（設定を変えたら過去の記事にも反映される）
        a = classify(a, config, brands)
        if a:
            articles.append(a)
    articles.sort(key=lambda a: a["published"], reverse=True)
    return dedupe(articles)


# ---------- ページ生成 ----------

def nav_html(current):
    links = []
    for file, label in PAGES:
        attr = ' aria-current="page"' if file == current else ""
        links.append(f'<a href="{file}"{attr}>{label}</a>')
    return '<nav class="nav">' + "".join(links) + "</nav>"


def trend_counts(articles, terms):
    counts = [(t, sum(1 for a in articles if t.lower() in a["title"].lower())) for t in terms]
    return sorted([c for c in counts if c[1] > 0], key=lambda c: -c[1])


def render_page(file, title, payload):
    css = (TEMPLATES / "style.css").read_text(encoding="utf-8")
    js = (TEMPLATES / "common.js").read_text(encoding="utf-8")
    page = (TEMPLATES / file).read_text(encoding="utf-8")
    # </script> で HTML が壊れないようにエスケープしてから埋め込む
    data_js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    page = (page.replace("{{STYLE}}", css)
                .replace("{{NAV}}", nav_html(file))
                .replace("{{COMMON_JS}}", js)
                .replace("{{TITLE}}", html.escape(title))
                .replace("{{DATA}}", data_js))
    (DOCS / file).write_text(page, encoding="utf-8")


def render_all(config, brands_doc, market, articles, updated):
    brands = brands_doc["brands"]
    title = config["title"]
    categories = [c["name"] for c in config["categories"]] + [config["brand_category"]]
    render_page("index.html", title, {
        "updated": updated, "categories": categories, "articles": articles,
    })
    market_cat = "市場・消費動向"
    render_page("market.html", title, {
        "updated": updated, "market": market,
        "articles": [a for a in articles if a["category"] == market_cat][:15],
        "trends": trend_counts(articles, config.get("trend_terms", [])),
        "total": len(articles),
    })
    render_page("brands.html", title, {
        "updated": updated, "brands": brands, "common_trends": brands_doc.get("common_trends", []),
        "articles": [a for a in articles if a.get("brand")],
    })


def main():
    offline = "--offline" in sys.argv
    config, brands_doc, market = load_json(CONFIG_PATH), load_json(BRANDS_PATH), load_json(MARKET_PATH)
    brands = brands_doc["brands"]

    new_items, errors = [], 0
    if not offline:
        for category, query in build_queries(config, brands):
            try:
                items = parse_feed(fetch_feed(query), config.get("max_per_keyword", 20))
                for it in items:
                    it.update(category=category, keyword=query)
                new_items += items
                print(f"[OK] {category} / {query}: {len(items)} 件")
            except Exception as e:  # 1 つの検索が失敗しても他は続ける
                errors += 1
                print(f"[NG] {category} / {query}: {e}", file=sys.stderr)

    old = load_json(DATA_PATH).get("articles", []) if DATA_PATH.exists() else []
    articles = merge(old, new_items, config, brands)
    updated = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    DOCS.mkdir(exist_ok=True)
    DATA_PATH.write_text(
        json.dumps({"updated": updated, "articles": articles}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    render_all(config, brands_doc, market, articles, updated)
    print(f"取得 {len(new_items)} 件 → 関連記事として保存 {len(articles)} 件（エラー {errors} 件）")
    if not offline and not new_items and errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
