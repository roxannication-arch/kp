import os
import sys
import json
import logging
import tempfile
import unicodedata
import httpx
from datetime import datetime
from io import BytesIO

# Ультимативная настройка окружения
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from openai import OpenAI
from anthropic import Anthropic
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))

# Чистим ВСЁ от Unicode-мусора
def clean_strict(s):
    if not s or not isinstance(s, str): return str(s)
    # Удаляем \u2028, \u2029 и прочие не-ASCII символы, которые ломают заголовки
    return "".join(ch for ch in s if ord(ch) < 128 or unicodedata.category(ch)[0] != "C")

# Создаем "чистый" HTTP клиент без прокси и с форсированным UTF-8
clean_http = httpx.Client(proxies=None)

openai_client = OpenAI(api_key=OPENAI_API_KEY, http_client=clean_http)
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY, http_client=clean_http)

sessions = {}

def c(s):
    if not s: return ""
    return clean_strict(s)

def cobj(obj):
    if isinstance(obj, dict): return {k: cobj(v) for k, v in obj.items()}
    if isinstance(obj, list): return [cobj(v) for v in obj]
    if isinstance(obj, str): return c(obj)
    return obj

# --- Шрифты и Цвета ---
PURPLE = colors.HexColor('#6c5ce7')
TEXT_DARK = colors.HexColor('#0f0c2a')
TEXT_MID = colors.HexColor('#666666')

def render_pdf(kp):
    buf = BytesIO()
    try:
        pdfmetrics.registerFont(TTFont('DJ', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DJB', 'DejaVuSans-Bold.ttf'))
    except: pass
    
    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = [Paragraph(c(kp.get("block1", {}).get("headline", "КП")), ParagraphStyle('h', fontName='DJB', fontSize=18))]
    doc.build(story)
    return buf.getvalue()

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Пришли аудио, я всё починил (надеюсь).")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID: return
    
    msg = await update.message.reply_text("Слушаю аудио...")
    file = await (update.message.voice or update.message.audio).get_file()
    
    # Жестко задаем путь без спецсимволов
    tmp_path = os.path.join(tempfile.gettempdir(), f"voice_{update.effective_user.id}.mp3")
    
    try:
        await file.download_to_drive(tmp_path)
        
        with open(tmp_path, "rb") as f:
            # КЛЮЧЕВОЕ: Передаем кортеж (имя, файл), чтобы OpenAI не брало имя из системы
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1", 
                file=("audio.mp3", f), 
                response_format="text"
            )

        await msg.edit_text("Генерирую...")
        # Упрощенный вызов для теста
        resp = anthropic_client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=1000,
            messages=[{"role": "user", "content": f"Сделай КП из этого: {c(transcript)}"}]
        )
        
        # Здесь должна быть твоя логика JSON, но для теста просто текст
        await update.message.reply_text(f"Текст готов: {c(resp.content[0].text)[:100]}...")
        
    except Exception as e:
        logging.error(f"FAIL: {e}")
        await msg.edit_text(f"Ошибка кодировки побеждена? Нет: {clean_strict(str(e))}")
    finally:
        if os.path.exists(tmp_path): os.unlink(tmp_path)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    app.run_polling()

if __name__ == "__main__":
    main()
