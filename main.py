import logging
from scraper import AxisScraper
from commentator import Commentator
from mailer import build_email, send_email
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

VOL_FILE = Path("vol_number.txt")

def get_vol():
    return int(VOL_FILE.read_text()) if VOL_FILE.exists() else 1

def next_vol():
    VOL_FILE.write_text(str(get_vol() + 1))

def main():
    logger.info("==================================================")
    logger.info("🚀 Axis Digest 開始執行")
    logger.info("==================================================")

    logger.info("📰 Step 1：抓取 Axis 文章...")
    scraper = AxisScraper()
    new_articles = scraper.run()
    logger.info("   新增 " + str(len(new_articles)) + " 篇")

    logger.info("🤖 Step 2：生成 AI 摘要與評論...")
    commentator = Commentator()
    done = commentator.process_all(batch=8)
    logger.info("   完成 " + str(done) + " 篇")

    logger.info("📋 Step 3：整理發送清單...")
    articles = scraper.get_unsent(limit=8)
    if not articles:
        logger.info("   沒有新文章，本週跳過")
        return

    logger.info("✉️  Step 4：寄送 " + str(len(articles)) + " 篇文章...")
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
