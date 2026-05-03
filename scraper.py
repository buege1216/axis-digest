import requests
from bs4 import BeautifulSoup
import sqlite3
import hashlib
import time
import logging
import re
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://www.axismag.jp"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AxisDigestBot/1.0)"}
REQUEST_DELAY = 2.0
MAX_ARTICLES = 10
DB_PATH = Path("articles.db")

# 歷史文章翻頁設定
# axismag.jp 的文章列表網址格式：
# 第1頁：https://www.axismag.jp/posts
# 第2頁：https://www.axismag.jp/posts?paged=2
# 第3頁：https://www.axismag.jp/posts?paged=3
LIST_BASE = "https://www.axismag.jp/posts"
MAX_PAGES = 50  # 最多翻幾頁（每頁約10篇，50頁約500篇歷史文章）


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

    def _save_article(self, article):
        with sqlite3.connect(DB_PATH) as conn:
            try:
                conn.execute("""
                    INSERT INTO articles
                        (url, url_hash, title, author, published, content, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    article["url"],
                    self._url_hash(article["url"]),
                    article.get("title", ""),
                    article.get("author", ""),
                    article.get("published", ""),
                    article.get("content", ""),
                    datetime.utcnow().isoformat(),
                ))
                conn.commit()
                logger.info("已儲存：" + article["title"][:60])
            except sqlite3.IntegrityError:
                pass

    def _fetch_links_from_page(self, page_num):
        if page_num == 1:
            url = LIST_BASE
        else:
            url = LIST_BASE + "?paged=" + str(page_num)

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
        except Exception as e:
            logger.error("列表頁失敗（第" + str(page_num) + "頁）：" + str(e))
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                href = BASE_URL + href
            if re.search(r"/posts/\d{4}/\d{2}/\d+\.html", href):
                links.append(href)
        return list(dict.fromkeys(links))

    def _fetch_content(self, url):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.error("文章頁失敗：" + str(e))
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.find("h1")
        date_el = soup.find("time")
        author_el = soup.select_one(".author, .writer, .name")
        body = soup.select_one(".post-content, .entry-content, .article-body, article")

        paragraphs = []
        if body:
            for p in body.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) > 30:
                    paragraphs.append(text)

        return {
            "url":       url,
            "title":     title.get_text(strip=True) if title else "",
            "author":    author_el.get_text(strip=True) if author_el else "",
            "published": date_el.get_text(strip=True) if date_el else "",
            "content":   "\n\n".join(paragraphs),
        }

    def run(self):
        new_articles = []

        for page in range(1, MAX_PAGES + 1):
            if len(new_articles) >= MAX_ARTICLES:
                break

            logger.info("掃描第 " + str(page) + " 頁...")
            links = self._fetch_links_from_page(page)

            if not links:
                logger.info("第 " + str(page) + " 頁沒有文章，停止翻頁")
                break

            # 如果這頁的文章全都看過了，繼續翻下一頁找新的
            all_seen = all(self._is_seen(url) for url in links)
            if all_seen:
                logger.info("第 " + str(page) + " 頁全部看過，繼續往下翻...")
                time.sleep(REQUEST_DELAY)
                continue

            for url in links:
                if len(new_articles) >= MAX_ARTICLES:
                    break
                if self._is_seen(url):
                    continue
                time.sleep(REQUEST_DELAY)
                article = self._fetch_content(url)
                if article.get("title"):
                    self._save_article(article)
                    new_articles.append(article)

            time.sleep(REQUEST_DELAY)

        logger.info("本次新增 " + str(len(new_articles)) + " 篇文章")
        return new_articles

    def get_unsent(self, limit=8):
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
