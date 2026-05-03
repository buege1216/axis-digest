import logging
import sqlite3
from pathlib import Path
from scraper import AxisScraper
from commentator import Commentator
from mailer import build_email, send_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

VOL_FILE = Path("vol_number.txt")

def get_vol():
    return int(VOL_FILE.read_text()) if VOL_FILE.exists() else 1

def next_vol():
    VOL_FILE.write_text(str(get_vol() + 1))

def main():
    logger.info("=" * 50)
    logger.info("🚀 Axis Digest 開始執行")
    logger.info("=" * 50)

    # Step 1：爬文章
    logger.info("📰 Step 1：抓取 Axis 文章...")
    scraper = AxisScraper()
    new_articles = scraper.run()
    logger.info(f"   新增 {len(new_articles)} 篇")

    # Step 2：AI 摘要
    logger.info("🤖 Step 2：生成 AI 摘要與評論...")
    commentator = Commentator()
    done = commentator.process_all(batch=8)
    logger.info(f"   完成 {done} 篇")

    # Step 3：取出待發送文章
    logger.info("📋 Step 3：整理發送清單...")
    articles = scraper.get_unsent(limit=8)
    if not articles:
        logger.info("   沒有新文章，本週跳過")
        return

    # Step 4：組裝並寄出
    logger.info(f"✉️  Step 4：寄送 {len(articles)} 篇文章...")
    vol = get_vol()
    subject, html = build_email(articles, vol=vol)
    success = send_email(subject, html)

    if success:
        scraper.mark_sent([a["id"] for a in articles])
        next_vol()
        logger.info("✅ 完成！")
    else:
        logger.error("❌ 寄信失敗，下次重試")

if __name__ == "__main__":
    main()
