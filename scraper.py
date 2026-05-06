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
REQUEST_DELAY = 1.5
DB_PATH = Path("articles.db")
PROGRESS_FILE = Path("last_id.txt")

# 你選的類別（日文對照）
TARGET_CATEGORIES = {
    "プロダクト": "product",
    "ビジネス":   "business",
    "テクノロジー": "technology",
    "アート":     "art",
    "グラフィック": "graphic",
    "工芸":       "craft",
    "カルチャー":  "culture",
}

LATEST_ID   = 709800  # 目前最新的流水號（之後會自動往下找）
MAX_FETCH   = 20      # 每次最多嘗試幾篇新文章
MAX_SKIP    = 50      # 連續幾篇找不到就停止


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

    def _get_last_id(self):
        if PROGRESS_FILE.exists():
            return int(PROGRESS_FILE.read_text().strip())
        return LATEST_ID

    def _save_last_id(self, article_id):
        PROGRESS_FILE.write_text(str(article_id))

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

    def _build_url(self, article_id):
        # 先試今年今月，不行再讓 requests 跟著 redirect
        now = datetime.now()
        return BASE_URL + "/posts/" + str(now.year) + "/" + f"{now.month:02d}" + "/" + str(article_id) + ".html"

    def _fetch_article(self, article_id):
        # 直接用 ID 組出網址，讓伺服器 redirect 到正確的年/月
        url = BASE_URL + "/posts/2026/05/" + str(article_id) + ".html"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
            if resp.status_code == 404:
                # 試試其他月份
                for ym in ["2026/04", "2026/03", "2026/02", "2026/01",
                           "2025/12", "2025/11", "2025/10", "2025/09"]:
                    url2 = BASE_URL + "/posts/" + ym + "/" + str(article_id) + ".html"
                    resp2 = requests.get(url2, headers=HEADERS, timeout=10)
                    if resp2.status_code == 200:
                        resp = resp2
                        url = url2
                        break
                else:
                    return None
            elif resp.status_code != 200:
                return None
        except Exception as e:
            logger.debug("請求失敗：" + str(e))
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # 確認是文章頁（有 h1）
        title_el = soup.find("h1")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        if not title or len(title) < 5:
            return None

        # 判斷分類
        category = ""
        for jp_name, en_name in TARGET_CATEGORIES.items():
            if jp_name in resp.text:
                category = en_name
                break
        if not category:
            return None  # 不在目標類別裡，跳過

        # 抓內文
        date_el = soup.find("time")
        author_el = soup.select_one(".author, .writer, .name, .editor")
        body = soup.select_one(".post-content, .entry-content, .article-body, article")

        paragraphs = []
        if body:
            for p in body.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) > 30:
                    paragraphs.append(text)

        content = "\n\n".join(paragraphs)
        if len(content) < 50:
            return None  # 內容太短，可能是會員限定或錯誤頁

        return {
            "url":       url,
            "title":     title,
            "author":    author_el.get_text(strip=True) if author_el else "",
            "published": date_el.get_text(strip=True) if date_el else "",
            "category":  category,
            "content":   content,
        }

    def run(self):
        start_id = self._get_last_id()
        logger.info("從流水號 " + str(start_id) + " 開始往下找...")

        new_articles = []
        skip_count = 0
        current_id = start_id

        while len(new_articles) < MAX_FETCH and skip_count < MAX_SKIP:
            url = BASE_URL + "/posts/2026/05/" + str(current_id) + ".html"
            if self._is_seen(url):
                current_id -= 1
                continue

            article = self._fetch_article(current_id)

            if article:
                self._save_article(article)
                new_articles.append(article)
                skip_count = 0
                logger.info("  ✓ " + str(current_id) + "：" + article["title"][:40])
            else:
                skip_count += 1
                logger.debug("  - " + str(current_id) + " 跳過")

            current_id -= 1
            time.sleep(REQUEST_DELAY)

        self._save_last_id(current_id)
        logger.info("共新增 " + str(len(new_articles)) + " 篇文章，目前到 ID " + str(current_id))
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
