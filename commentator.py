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
        self.model = genai.GenerativeModel("gemini-1.5-flash")

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
