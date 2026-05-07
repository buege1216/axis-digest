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

COMMENTATOR_SYSTEM = (
    "你是「軸心評論」的首席評論員——"
    "一位融合藝術史學者、當代策展人與文化批評家三重身份的評論員。\n"
    "無論文章原文是日文還是英文，你的回應一律使用繁體中文。\n\n"
    "風格要求：\n"
    "• 開篇以一個犀利的核心觀點破題\n"
    "• 引用具體的歷史或當代案例作為參照\n"
    "• 點出文章的盲點或值得延伸思考的面向\n"
    "• 結尾給一句有記憶點的金句或提問\n"
    "• 全程使用繁體中文，約 200 字\n"
    "• 口吻：自信但不傲慢，學術但不艱澀"
)


class Commentator:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY", "")
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.0-flash"

    def _ask(self, system, prompt, max_tokens=600):
        for attempt in range(3):
            try:
                resp = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=max_tokens,
                    )
                )
                return resp.text.strip()
            except Exception as e:
                logger.warning("第 " + str(attempt + 1) + " 次失敗：" + str(e))
                time.sleep(45)
        return ""

    def summarize(self, article):
        content = article.get("content", "")[:3000]
        prompt = (
            "請用繁體中文為以下文章產生結構化摘要，分三段輸出：\n\n"
            "【核心主題】一句話說明文章核心（30字內）\n"
            "【重點整理】3個要點，每點以「• 」開頭\n"
            "【延伸思考】建議讀者可進一步思考的問題（1句）\n\n"
            "文章標題：" + article.get("title", "") + "\n"
            "文章內容：" + content
        )
        return self._ask("你是一位專業的設計與藝術媒體編輯，擅長精準摘要，一律使用繁體中文。", prompt, max_tokens=400)

    def comment(self, article, summary):
        content = article.get("content", "")[:1500]
        prompt = (
            "請針對以下文章提供專業點評，直接輸出點評內文：\n\n"
            "文章標題：" + article.get("title", "") + "\n"
            "文章摘要：" + summary + "\n"
            "文章節錄：" + content
        )
        return self._ask(COMMENTATOR_SYSTEM, prompt, max_tokens=500)

    def translate(self, article):
        content = article.get("content", "")[:4000]
        prompt = (
            "請將以下日文文章翻譯成繁體中文，保持原文段落結構，自然流暢：\n\n"
            "文章標題：" + article.get("title", "") + "\n"
            "文章內容：" + content
        )
        return self._ask("你是一位專業的日繁翻譯，翻譯自然流暢，保留原文語氣。", prompt, max_tokens=1500)
    
    def process_all(self, batch=8):
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
            summary = self.summarize(art)
            time.sleep(15)
            commentary = self.comment(art, summary) if summary else ""

            if summary:
                time.sleep(3)
                translation = self.translate(art)
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        "UPDATE articles SET summary=?, commentary=?, translation=? WHERE id=?",
                        (summary, commentary, translation, art["id"])
                    )
                    conn.commit()
                done += 1
                logger.info("  ✓ 完成")
            time.sleep(15)

        logger.info("完成 " + str(done) + " 篇")
        return done
