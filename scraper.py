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
DB_PATH = Path("articles.db")

# 你選的類別
CATEGORIES = [
    "product",
    "business",
    "technology",
    "art",
    "graphic",
    "craft",
    "culture",
]

MAX_NEW_PER_CATEGORY = 3   # 每個類別每次最多抓幾篇新文章
MAX_PAGES_PER_CATEGORY = 5 # 每個類別每次最多翻幾頁


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
            # 記錄每個類別翻到第幾頁了
            conn.execute("""
                CREATE TABLE IF NOT EXISTS category_progress (
                    category TEXT PRIMARY KEY,
                    next_page INTEGER DEFAULT 1
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

    def _get_next_page(self, category):
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT next_page FROM category_progress WHERE category = ?",
                (category,)
            ).fetchone()
        return row[0] if row else 1

    def _save_next_page(self, category, page):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO category_progress (category, next_page)
                VALUES (?, ?)
                ON CONFLICT(category) DO UPDATE SET next_page = ?
            """, (category, page, page))
            conn.commit()

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

    def _fetch_links_from_page(self, category, page):
        if page == 1:
            url = BASE_URL + "/posts/" + category
        else:
            url = BASE_URL + "/posts/" + category + "?paged=" + str(page)

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
        except Exception as e:
            logger.error("列表頁失敗：" + str(e))
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

    def _fetch_content(self, url, category):
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
            "category":  category,
            "content":   "\n\n".join(paragraphs),
        }

    def run(self):
        all_new = []

        for category in CATEGORIES:
            logger.info("── 類別：" + category + " ──")
            start_page = self._get_next_page(category)
            new_count = 0
            current_page = start_page

            for page in range(start_page, start_page + MAX_PAGES_PER_CATEGORY):
                if new_count >= MAX_NEW_PER_CATEGORY:
                    break

                logger.info("  第 " + str(page) + " 頁...")
                links = self._fetch_links_from_page(category, page)

                if not links:
                    logger.info("  已到底，類別 " + category + " 全部掃完")
                    self._save_next_page(category, page)
                    break

                for url in links:
                    if new_count >= MAX_NEW_PER_CATEGORY:
                        break
                    if self._is_seen(url):
                        continue
                    time.sleep(REQUEST_DELAY)
                    article = self._fetch_content(url, category)
                    if article.get("title"):
                        self._save_article(article)
                        all_new.append(article)
                        new_count += 1

                current_page = page + 1
                time.sleep(REQUEST_DELAY)

            self._save_next_page(category, current_page)
            logger.info("  本次新增 " + str(new_count) + " 篇")

        logger.info("全部類別共新增 " + str(len(all_new)) + " 篇文章")
        return all_new

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
