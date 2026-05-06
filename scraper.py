import requests
import sqlite3
import hashlib
import time
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path("articles.db")
PROGRESS_FILE = Path("last_page.txt")
REQUEST_DELAY = 2.0

# WordPress REST API
API_URL = "https://www.axismag.jp/wp-json/wp/v2/posts"

# 你選的類別 ID（從 API 取得）
# product=4, business=8, technology=10, art=6, graphic=11, craft=16, culture=15
TARGET_CATEGORY_IDS = [4, 8, 10, 6, 11, 16, 15]
CATEGORY_MAP = {
    4:  "product",
    8:  "business",
    10: "technology",
    6:  "art",
    11: "graphic",
    16: "craft",
    15: "culture",
}

ARTICLES_PER_PAGE = 10
MAX_PAGES_PER_RUN = 3


class AxisScraper:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    url        TEXT UNIQUE NOT NULL,
                    url_hash   TEXT UNIQUE NOT NULL,
                    title      TEXT,
                    author     TEXT,
                    published  TEXT,
                    category   TEXT,
                    content    TEXT,
                    summary    TEXT,
                    commentary TEXT,
                    fetched_at TEXT NOT NULL,
                    sent       INTEGER DEFAULT 0
                )
            """)
            conn.commit()

    def _url_hash(self, url):
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _is_seen(self, url):
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT 1 FROM articles WHERE url_hash = ?",
                (self._url_hash(url),)
            ).fetchone()
        return row is not None

    def _get_last_page(self):
        if PROGRESS_FILE.exists():
            return int(PROGRESS_FILE.read_text().strip())
        return 1

    def _save_last_page(self, page):
        PROGRESS_FILE.write_text(str(page))

    def _save_article(self, article):
        with sqlite3.connect(DB_PATH) as conn:
            try:
                conn.execute("""
                    INSERT INTO articles
                        (url, url_hash, title, author, published, category, content, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    article["url"],
                    self._url_hash(article["url"]),
                    article.get("title", ""),
                    article.get("author", ""),
                    article.get("published", ""),
                    article.get("category", ""),
                    article.get("content", ""),
                    datetime.utcnow().isoformat(),
                ))
                conn.commit()
                logger.info("已儲存：" + article["title"][:50])
            except sqlite3.IntegrityError:
                pass

    def _strip_html(self, html):
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _fetch_page(self, page):
        params = {
            "per_page": ARTICLES_PER_PAGE,
            "page":     page,
            "orderby":  "date",
            "order":    "desc",
            "_fields":  "id,link,title,content,date,categories",
        }
        try:
            resp = requests.get(API_URL, params=params,
                                headers={"User-Agent": "AxisDigestBot/1.0"},
                                timeout=20)
            if resp.status_code == 400:
                return []  # 超過最大頁數
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("API 請求失敗：" + str(e))
            return []

    def run(self):
        start_page = self._get_last_page()
        logger.info("從第 " + str(start_page) + " 頁開始抓取（每頁 " + str(ARTICLES_PER_PAGE) + " 篇）")

        new_articles = []
        current_page = start_page

        for _ in range(MAX_PAGES_PER_RUN):
            logger.info("抓取第 " + str(current_page) + " 頁...")
            posts = self._fetch_page(current_page)

            if not posts:
                logger.info("沒有更多文章了，已到底")
                break

            for post in posts:
                url = post.get("link", "")
                if not url or self._is_seen(url):
                    continue

                # 確認類別
                cat_ids = post.get("categories", [])
                category = ""
                for cid in cat_ids:
                    if cid in CATEGORY_MAP:
                        category = CATEGORY_MAP[cid]
                        break
                if not category:
                    continue  # 不在目標類別

                title = self._strip_html(post.get("title", {}).get("rendered", ""))
                content_html = post.get("content", {}).get("rendered", "")
                content = self._strip_html(content_html)

                if len(content) < 50:
                    continue

                article = {
                    "url":       url,
                    "title":     title,
                    "author":    "",
                    "published": post.get("date", "")[:10],
                    "category":  category,
                    "content":   content[:4000],
                }
                self._save_article(article)
                new_articles.append(article)

            current_page += 1
            time.sleep(REQUEST_DELAY)

        self._save_last_page(current_page)
        logger.info("共新增 " + str(len(new_articles)) + " 篇文章")
        return new_articles

    def get_unsent(self, limit=15):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM articles
                WHERE sent = 0 AND summary IS NOT NULL
                ORDER BY fetched_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def mark_sent(self, ids):
        with sqlite3.connect(DB_PATH) as conn:
            conn.executemany(
                "UPDATE articles SET sent = 1 WHERE id = ?",
                [(i,) for i in ids]
            )
            conn.commit()
