import smtplib
import os
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def build_email(articles, vol=1):
    now = datetime.now()
    date_str = now.strftime("%Y 年 %m 月 %d 日")

    cards = ""
    for i, art in enumerate(articles, 1):
        meta = art.get("author", "") or "Axis"
        if art.get("published"):
            meta += "　·　" + art["published"]

        cards += f"""
        <div style="background:#ffffff;margin:16px 0;border-radius:4px;border-left:4px solid #1a1a18;">
          <div style="padding:24px 28px 16px;border-bottom:1px solid #f1efe8;">
            <p style="font-family:Arial,sans-serif;font-size:11px;letter-spacing:0.15em;
               text-transform:uppercase;color:#b4b2a9;margin:0 0 8px;">文章 {i:02d}</p>
            <h2 style="font-size:20px;font-weight:400;margin:0 0 8px;line-height:1.3;">
              <a href="{art.get('url','#')}" style="color:#1a1a18;text-decoration:none;
                 border-bottom:1px solid #d3d1c7;">{art.get('title','（無標題）')}</a>
            </h2>
            <p style="font-family:Arial,sans-serif;font-size:12px;color:#888780;margin:0;">{meta}</p>
          </div>

          <div style="padding:20px 28px;border-bottom:1px solid #f1efe8;">
            <p style="font-family:Arial,sans-serif;font-size:10px;letter-spacing:0.2em;
               text-transform:uppercase;color:#b4b2a9;margin:0 0 12px;">編輯摘要</p>
            <p style="font-size:14px;line-height:1.8;color:#444441;margin:0;
               white-space:pre-line;">{art.get('summary','')}</p>
          </div>

          <div style="padding:20px 28px;background:#fafaf8;">
            <div style="display:inline-block;background:#1a1a18;color:#f1efe8;
               font-family:Arial,san
