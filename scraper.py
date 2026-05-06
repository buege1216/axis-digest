import requests
from bs4 import BeautifulSoup
import sqlite3
import hashlib
import time
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path("articles.db")
PROGRESS_FILE = Path("sitemap_progress.txt")
REQUEST_DELAY = 2.0

BASE_URL = "https://www.axismag.jp"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AxisDigestBot/1.0)"}

# sitemap 從15往1讀（新到舊）
SITEMAP_URLS = [
    "https://www.axismag.jp/post_list-sitemap" + str(i) + ".xml"
    for i in range(15, 0, -1)
]

MAX_ARTICLES_PER_RUN = 15  # 每次最多抓幾篇


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

    def _get_progress(self):
        """回傳 (sitemap_index, url_index)，代表上次讀到哪裡"""
        if PROGRESS_FILE.exists():
            parts = PROGRESS_FILE.read_text().strip().split(",")
            return int(parts[0]), int(parts[1])
        return 0, 0  # 從 sitemap15 第0筆開始

    def _save_progress(self, sitemap_idx, url_idx):
        PROGRESS_FILE.write_text(str(sitemap_idx) + "," + str(url_idx))

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

    def _fetch_sitemap_urls(self, sitemap_url):
        """從 sitemap XML 取得所有文章網址"""
        try:
            resp = requests.get(sitemap_url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            logger.error("Sitemap 讀取失敗：" + str(e))
            return []

        urls = []
        try:
            root = ET.fromstring(resp.content)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for loc in root.findall(".//sm:loc", ns):
                url = loc.text.strip()
                if re.search(r"/posts/\d{4}/\d{2}/\d+\.html", url):
                    urls.append(url)
        except Exception as e:
            logger.error("Sitemap 解析失敗：" + str(e))
        return urls

    def _fetch_article(self, url):
        """抓取單篇文章內容"""
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except Exception as e:
            logger.debug("文章抓取失敗：" + str(e))
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        title_el = soup.find("h1")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        if len(title) < 5:
            return None

        date_el = soup.find("time")

        # 從 meta og:description 取得摘要當作備用內文
        meta_desc = soup.find("meta", {"name": "description"}) or \
                    soup.find("meta", {"property": "og:description"})
        meta_content = meta_desc.get("content", "") if meta_desc else ""

        # 嘗試抓內文
        body = soup.select_one(".post-content, .entry-content, .article-body, "
                               ".article__body, .article-text, #article-body, article")
        paragraphs = []
        if body:
            for p in body.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) > 30:
                    paragraphs.append(text)

        content = "\n\n".join(paragraphs)

        # 如果內文太短，用 meta description 補充
        if len(content) < 100 and meta_content:
            content = meta_content

        if len(content) < 30:
            return None

        # 從網址抓年月當作發布日期備用
        published = ""
        if date_el:
            published = date_el.get_text(strip=True)
        else:
            m = re.search(r"/posts/(\d{4})/(\d{2})/", url)
            if m:
                published = m.group(1) + "-" + m.group(2)

        return {
            "url":       url,
            "title":     title,
            "author":    "",
            "published": published,
            "category":  "",
            "content":   content[:4000],
        }

    def run(self):
        sitemap_idx, url_idx = self._get_progress()
        logger.info("從 sitemap " + str(sitemap_idx + 1) + "/15，第 " + str(url_idx) + " 筆開始")

        new_articles = []

        while len(new_articles) < MAX_ARTICLES_PER_RUN:
            if sitemap_idx >= len(SITEMAP_URLS):
                logger.info("所有 sitemap 已讀完！")
                break

            sitemap_url = SITEMAP_URLS[sitemap_idx]
            logger.info("讀取：" + sitemap_url)
            urls = self._fetch_sitemap_urls(sitemap_url)

            if not urls:
                sitemap_idx += 1
                url_idx = 0
                continue

            logger.info("  共 " + str(len(urls)) + " 篇，從第 " + str(url_idx) + " 筆繼續")

            while url_idx < len(urls):
                if len(new_articles) >= MAX_ARTICLES_PER_RUN:
                    break

                url = urls[url_idx]
                url_idx += 1

                if self._is_seen(url):
                    continue

                time.sleep(REQUEST_DELAY)
                article = self._fetch_article(url)
                if article:
                    self._save_article(article)
                    new_articles.append(article)
                    logger.info("  ✓ " + article["title"][:40])

            # 這個 sitemap 讀完了，進下一個
            if url_idx >= len(urls):
                sitemap_idx += 1
                url_idx = 0

            self._save_progress(sitemap_idx, url_idx)

        self._save_progress(sitemap_idx, url_idx)
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
