import smtplib
import os
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def make_card(i, art):
    meta = art.get("author", "") or "Axis"
    if art.get("published"):
        meta += "　·　" + art["published"]
    url = art.get("url", "#")
    title = art.get("title", "（無標題）")
    summary = art.get("summary", "")
    commentary = art.get("commentary", "")
    translation = art.get("translation", "")

    card = '<div style="background:#ffffff;margin:16px 0;border-radius:4px;border-left:4px solid #1a1a18;">'

    # 標題區
    card += '<div style="padding:24px 28px 16px;border-bottom:1px solid #f1efe8;">'
    card += '<p style="font-family:Arial,sans-serif;font-size:11px;letter-spacing:0.15em;text-transform:uppercase;color:#b4b2a9;margin:0 0 8px;">文章 ' + f"{i:02d}" + '</p>'
    card += '<h2 style="font-size:20px;font-weight:400;margin:0 0 8px;line-height:1.3;">'
    card += '<a href="' + url + '" style="color:#1a1a18;text-decoration:none;border-bottom:1px solid #d3d1c7;">' + title + '</a>'
    card += '</h2>'
    card += '<p style="font-family:Arial,sans-serif;font-size:12px;color:#888780;margin:0;">' + meta + '</p>'
    card += '</div>'

    # 摘要區
    card += '<div style="padding:20px 28px;border-bottom:1px solid #f1efe8;">'
    card += '<p style="font-family:Arial,sans-serif;font-size:10px;letter-spacing:0.2em;text-transform:uppercase;color:#b4b2a9;margin:0 0 12px;">編輯摘要</p>'
    card += '<p style="font-size:14px;line-height:1.8;color:#444441;margin:0;white-space:pre-line;">' + summary + '</p>'
    card += '</div>'

    # 評論區
    card += '<div style="padding:20px 28px;background:#fafaf8;border-bottom:1px solid #f1efe8;">'
    card += '<div style="display:inline-block;background:#1a1a18;color:#f1efe8;font-family:Arial,sans-serif;font-size:10px;letter-spacing:0.15em;text-transform:uppercase;padding:4px 10px;border-radius:2px;margin-bottom:12px;">軸心評論 · AI 評論員</div>'
    card += '<p style="font-size:14px;line-height:1.85;color:#2c2c2a;margin:0;font-style:italic;">' + commentary + '</p>'
    card += '</div>'

    # 翻譯全文區
    if translation:
        card += '<div style="padding:20px 28px;border-bottom:1px solid #f1efe8;">'
        card += '<p style="font-family:Arial,sans-serif;font-size:10px;letter-spacing:0.2em;text-transform:uppercase;color:#b4b2a9;margin:0 0 12px;">繁體中文全文</p>'
        card += '<p style="font-size:14px;line-height:1.9;color:#2c2c2a;margin:0;white-space:pre-line;">' + translation + '</p>'
        card += '</div>'

    # 閱讀原文
    card += '<div style="padding:16px 28px 24px;">'
    card += '<a href="' + url + '" style="font-family:Arial,sans-serif;font-size:12px;color:#1a1a18;text-decoration:none;border-bottom:1px solid #1a1a18;">閱讀原文 →</a>'
    card += '</div>'
    card += '</div>'
    return card


def build_email(articles, vol=1):
    now = datetime.now()
    date_str = now.strftime("%Y 年 %m 月 %d 日")
    n = len(articles)

    cards = ""
    for i, art in enumerate(articles, 1):
        cards += make_card(i, art)

    header = '<div style="background:#1a1a18;padding:40px 32px 32px;border-radius:4px 4px 0 0;">'
    header += '<p style="font-family:Arial,sans-serif;font-size:11px;letter-spacing:0.2em;text-transform:uppercase;color:#888780;margin:0 0 12px;">Axis Digest · 軸心週報</p>'
    header += '<h1 style="font-size:36px;font-weight:400;color:#f1efe8;margin:0 0 8px;letter-spacing:-0.02em;line-height:1.1;">本週藝術與設計<br>精選摘要</h1>'
    header += '<p style="font-size:14px;color:#888780;margin:0;font-style:italic;">由 AI 評論員「軸心評論」精讀，為你萃取洞見</p>'
    header += '<div style="margin-top:24px;padding-top:20px;border-top:1px solid #333330;font-family:Arial,sans-serif;font-size:12px;color:#5f5e5a;">'
    header += 'Vol. ' + str(vol) + ' &nbsp;·&nbsp; ' + date_str + ' &nbsp;·&nbsp; 共 ' + str(n) + ' 篇文章'
    header += '</div></div>'

    intro = '<div style="background:#2c2c2a;padding:20px 32px;">'
    intro += '<p style="margin:0;font-size:15px;color:#b4b2a9;line-height:1.7;font-style:italic;">'
    intro += '本週 <strong style="color:#f1efe8;font-style:normal;">Axis Digest</strong> 精選了 ' + str(n) + ' 篇文章，由 AI 評論員為你萃取重點與洞見。'
    intro += '</p></div>'

    footer = '<div style="background:#1a1a18;padding:28px 32px;border-radius:0 0 4px 4px;">'
    footer += '<p style="font-family:Arial,sans-serif;font-size:11px;color:#5f5e5a;margin:0 0 6px;line-height:1.6;">文章來源：axismag.jp　·　AI 摘要由 Gemini 生成，僅供參考</p>'
    footer += '<p style="font-family:Arial,sans-serif;font-size:11px;color:#444441;margin:0;">© ' + str(now.year) + ' Axis Digest</p>'
    footer += '</div>'

    html = '<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>'
    html += '<body style="margin:0;padding:0;background:#f5f4f0;font-family:Georgia,serif;color:#2c2c2a;">'
    html += '<div style="max-width:640px;margin:0 auto;padding:24px 16px;">'
    html += header + intro + cards + footer
    html += '</div></body></html>'

    subject = "🎨 軸心週報 Vol." + str(vol) + "｜本週 Axis 精選 " + str(n) + " 篇"
    return subject, html


def send_email(subject, html):
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    to_email = os.environ.get("TO_EMAIL", smtp_user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("軸心週報 Axis Digest", smtp_user))
    msg["To"] = to_email
    msg.attach(MIMEText("請使用支援 HTML 的郵件客戶端查看。", "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
        logger.info("✅ Email 已寄出至 " + to_email)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Gmail 認證失敗，請確認 App Password 是否正確")
    except Exception as e:
        logger.error("❌ 寄信失敗：" + str(e))
    return False
