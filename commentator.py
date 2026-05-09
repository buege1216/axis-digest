import sqlite3
import logging
import time
import os
from pathlib import Path
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path("articles.db")

SYSTEM_PROMPT = (
    "你是「軸心評論」首席評論員，融合藝術史學者、策展人與文化批評家三重身份。\n"
    "無論原文是什麼語言，一律用繁體中文回應。\n"
    "口吻：自信但不傲慢，學術但不艱澀。"
)


class Commentator:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY", "")
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.5-flash"
        self._last_error_is_quota = False

    def _ask(self, prompt, max_tokens=900):
        self._last_error_is_quota = False
        for attempt in range(3):
            try:
                resp = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        max_output_tokens=max_tokens,
                    )
                )
                return resp.text.strip()
            except Exception as e:
                msg = str(e)
                logger.warning("第 " + str(attempt + 1) + " 次失敗：" + msg)
                if "503" in msg or "UNAVAILABLE" in msg:
                    time.sleep(60)
                elif "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    self._last_error_is_quota = True
                    time.sleep(45)
                else:
                    time.sleep(15)
        return ""

    def process_article(self, article):
        content = article.get("content", "")[:3000]
        title = article.get("title", "")

        prompt = (
            "請嚴格按照以下格式輸出，不要加任何額外說明：\n\n"
            "===摘要===\n"
            "核心主題：（25字內）\n"
            "• 要點一\n"
            "• 要點二\n"
            "• 要點三\n"
            "延伸思考：（一句提問）\n\n"
            "===評論===\n"
            "（犀利開篇、引用案例、點出盲點、金句結尾，約150字，繁體中文）\n\n"
            "===翻譯===\n"
            "（從文章挑選2-3段最重要的內容，翻譯成繁體中文）\n\n"
            "以下是文章內容：\n"
            "標題：" + title + "\n"
            "內容：" + content
        )

        result = self._ask(prompt, max_tokens=900)
        if not result:
            return "", "", ""

        import re as _re
        summary     = _re.search(r"===摘要===(.*?)===評論===", result, _re.DOTALL)
        commentary  = _re.search(r"===評論===(.*?)===翻譯===", result, _re.DOTALL)
        translation = _re.search(r"===翻譯===(.*?)$",          result, _re.DOTALL)

        summary     = summary.group(1).strip()     if summary     else ""
        commentary  = commentary.group(1).strip()  if commentary  else ""
        translation = translation.group(1).strip() if translation else ""

        return summary, commentary, translation

    def process_all(self, batch=5):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, title, content FROM articles
                WHERE summary IS NULL AND content != ''
                ORDER BY fetched_at DESC LIMIT ?
            """, (batch,)).fetchall()

        articles = [dict(r) for r in rows]
        if not articles:
            logger.info("沒有待處理文章")
            return 0

        done = 0
        for art in articles:
            logger.info("處理：" + art["title"][:50])
            summary, commentary, translation = self.process_article(art)

            if summary:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        "UPDATE articles SET summary=?, commentary=?, translation=? WHERE id=?",
                        (summary, commentary, translation, art["id"])
                    )
                    conn.commit()
                done += 1
                logger.info("  ✓ 完成（今日已處理 " + str(done) + " 篇）")
            elif self._last_error_is_quota:
                logger.warning("  配額已用盡，今天剩下的留給明天處理")
                break
            else:
                logger.warning("  ✗ 失敗，跳過")

            time.sleep(5)

        logger.info("完成 " + str(done) + " 篇")
        return done
