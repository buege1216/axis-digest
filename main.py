import logging
import os
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
    mode = os.environ.get("RUN_MODE", "process")
    # process = 只爬蟲+摘要，不寄信
    # send    = 從庫存寄一篇給你

    logger.info("==================================================")
    logger.info("🚀 Axis Digest 開始執行，模式：" + mode)
    logger.info("==================================================")

    scraper = AxisScraper()
    commentator = Commentator()

    if mode == "process":
        logger.info("📰 Step 1：抓取新文章...")
        new_articles = scraper.run()
        logger.info("   新增 " + str(len(new_articles)) + " 篇")

        logger.info("🤖 Step 2：生成 AI 摘要與評論...")
        done = commentator.process_all(batch=8)
        logger.info("   完成 " + str(done) + " 篇")

        # 顯示目前庫存數量
        pending = scraper.get_unsent_count()
        logger.info("📦 目前庫存：" + str(pending) + " 篇待寄出")

    elif mode == "send":
        logger.info("📬 寄信模式：從庫存取文章寄出...")
        articles = scraper.get_unsent(limit=1)

        if not articles:
            logger.info("   庫存是空的，請先等系統累積更多文章")
            return

        vol = get_vol()
        subject, html = build_email(articles, vol=vol)
        success = send_email(subject, html)

        if success:
            scraper.mark_sent([a["id"] for a in articles])
            next_vol()
            logger.info("✅ 已寄出 " + str(len(articles)) + " 篇，庫存剩 " + str(scraper.get_unsent_count()) + " 篇")
        else:
            logger.error("❌ 寄信失敗")

if __name__ == "__main__":
    main()
