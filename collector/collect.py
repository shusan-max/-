"""子供服・アパレル関連ニュースを Google ニュースの RSS から集め、
ブラウザで見られる docs/index.html を作るスクリプト。

使い方:  python collector/collect.py
外部ライブラリ不要（Python 3.9 以上の標準機能のみ）。
"""

import html
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "docs" / "data.json"
HTML_PATH = ROOT / "docs" / "index.html"
TEMPLATE_PATH = Path(__file__).resolve().parent / "template.html"

JST = timezone(timedelta(hours=9))
FEED_URL = "https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"


def fetch_feed(keyword):
    url = FEED_URL.format(q=urllib.parse.quote(f"{keyword} when:7d"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (info-collector)"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def parse_feed(xml_bytes, keyword, category, limit):
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
            items.append({
                "title": title,
                "link": link,
                "source": source,
                "published": published.isoformat(),
                "category": category,
                "keyword": keyword,
            })
    return items


def load_existing():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8")).get("articles", [])
    return []


def merge(old, new, keep_days):
    cutoff = datetime.now(JST) - timedelta(days=keep_days)
    merged = {}
    # 同じタイトルの記事は 1 件にまとめる（新しく取得したものを優先）
    for a in old + new:
        merged[a["title"]] = a
    articles = [a for a in merged.values() if datetime.fromisoformat(a["published"]) >= cutoff]
    return sorted(articles, key=lambda a: a["published"], reverse=True)


def render(config, articles, updated):
    payload = {
        "title": config["title"],
        "updated": updated,
        "categories": [c["name"] for c in config["categories"]],
        "articles": articles,
    }
    # </script> で HTML が壊れないようにエスケープしてから埋め込む
    data_js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE_PATH.read_text(encoding="utf-8")
    page = page.replace("{{TITLE}}", html.escape(config["title"]))
    page = page.replace("{{DATA}}", data_js)
    HTML_PATH.write_text(page, encoding="utf-8")


def main():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    new_items, errors = [], 0
    for cat in config["categories"]:
        for kw in cat["keywords"]:
            try:
                items = parse_feed(fetch_feed(kw), kw, cat["name"], config.get("max_per_keyword", 20))
                new_items += items
                print(f"[OK] {cat['name']} / {kw}: {len(items)} 件")
            except Exception as e:  # 1 つのキーワードが失敗しても他は続ける
                errors += 1
                print(f"[NG] {cat['name']} / {kw}: {e}", file=sys.stderr)

    articles = merge(load_existing(), new_items, config.get("keep_days", 30))
    updated = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    DATA_PATH.parent.mkdir(exist_ok=True)
    DATA_PATH.write_text(
        json.dumps({"updated": updated, "articles": articles}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    render(config, articles, updated)
    print(f"保存しました: {len(articles)} 件（エラー {errors} 件）")
    if new_items == [] and errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
