import requests
from bs4 import BeautifulSoup
import sqlite3
import hashlib
import time
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://www.axisweb.org"
LIST_URL = "https://www.axisweb.org/articles"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AxisDigestBot/1.0)"}
REQUEST_DELAY = 2.0
MAX_ARTICLES = 10
DB_PATH = Path("articles.db")

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
                logger.info(f"已儲存：{article['title'][:60]}")
            except sqlite3.IntegrityError:
                pass

    def _fetch_links(self):
        try:
            resp = requests.get(LIST_URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"列表頁失敗：{e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.select("a[href]"):
            href = a["href"]
            if not href.startswith("http"):
                href = BASE_URL.rstrip("/") + "/" + href.lstrip("/")
            if "/article/" in href or "/news/" in href:
                links.append(href)
        return list(dict.fromkeys(links))

    def _fetch_content(self, url):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"文章頁失敗 {url}：{e}")
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")
        title     = soup.find("h1")
        author_el = soup.select_one(".author-name, .byline, [rel='author']")
        date_el   = soup.select_one("time, .published-date")
        body_el   = soup.select_one("article, .article-body, .entry-content, main")

        paragraphs = []
        if body_el:
            for p in body_el.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) > 40:
                    paragraphs.append(text)

        return {
            "url":       url,
            "title":     title.get_text(strip=True) if title else "",
            "author":    author_el.get_text(strip=True) if author_el else "",
            "published": date_el.get_text(strip=True) if date_el else "",
            "content":   "\n\n".join(paragraphs),
        }

    def run(self):
        links = self._fetch_links()
        new_articles = []
        for url in links:
            if len(new_articles) >= MAX_ARTICLES:
                break
            if self._is_seen(url):
                continue
            time.sleep(REQUEST_DELAY)
            article = self._fetch_content(url)
            if article.get("content"):
                self._save_article(article)
                new_articles.append(article)
        logger.info(f"新增 {len(new_articles)} 篇文章")
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
