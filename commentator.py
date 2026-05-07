import google.generativeai as genai
import sqlite3
import logging
import time
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path("articles.db")

COMMENTATOR_SYSTEM = """你是「軸心評論」的首席評論員——
一位融合藝術史學者、當代策展人與文化批評家三重身份的評論員。
你的文字兼具學術深度與當代銳利，善於從社會脈絡、市場動態、
跨文化視角解析設計與藝術現象。

風格要求：
- 開篇以一個犀利的核心觀點破題
- 引用具體的歷史或當代案例作為參照
- 點出文章的盲點或值得延伸思考的面向
- 結尾給一句有記憶點的金句或提問
- 繁體中文，約 200 字
- 口吻：自信但不傲慢，學術但不艱澀"""


class Commentator:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY", "")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.5-flash-preview-04-17")

    def _ask(self, prompt, max_tokens=600):
        for attempt in range(3):
            try:
                resp = self.model.generate_content(
                    prompt,
                    generation_config={"max_output_tokens": max_tokens}
                )
                return resp.text.strip()
            except Exception as e:
                logger.warning(f"第 {attempt+1} 次失敗：{e}")
                time.sleep(3)
        return ""

    def summarize(self, article):
        content = article.get("content", "")[:3000]
        prompt = f"""請為以下文章產生結構化摘要，分三段輸出：

【核心主題】一句話說明文章核心（30字內）
【重點整理】3個要點，每點以「• 」開頭
【延伸思考】建議讀者可進一步思考的問題（1句）

文章標題：{article.get('title', '')}
文章內容：{content}"""
        return self._ask(prompt, max_tokens=400)

    def comment(self, article, summary):
        content = article.get("content", "")[:1500]
        prompt = f"""{COMMENTATOR_SYSTEM}

請針對以下文章提供專業點評，直接輸出點評內文：

文章標題：{article.get('title', '')}
文章摘要：{summary}
文章節錄：{content}"""
        return self._ask(prompt, max_tokens=500)

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
            logger.info(f"處理：{art['title'][:50]}")
            summary = self.summarize(art)
            time.sleep(1)
            commentary = self.comment(art, summary) if summary else ""

            if summary:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        "UPDATE articles SET summary=?, commentary=? WHERE id=?",
                        (summary, commentary, art["id"])
                    )
                    conn.commit()
                done += 1
            time.sleep(2)

        logger.info(f"完成 {done} 篇")
        return done
