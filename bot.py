import os
import json
import logging
import tempfile
import unicodedata
import httpx
from io import BytesIO

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from openai import OpenAI
from anthropic import Anthropic
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Настройки логирования
logging.basicConfig(level=logging.INFO)

# Конфигурация (берется из настроек Amvera)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))

# Инициализация клиентов (на Amvera это сработает без ошибок)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)

def clean_text(s):
    """Удаление проблемных символов Unicode"""
    if not s: return ""
    s = unicodedata.normalize('NFC', str(s))
    return "".join(ch for ch in s if unicodedata.category(ch)[0] != "C" or ch == '\n')

def render_pdf(text_content):
    """Простейшая генерация PDF для теста"""
    buf = BytesIO()
    # Пытаемся загрузить шрифт, если его нет — используем стандартный
    try:
        pdfmetrics.registerFont(TTFont('DJ', 'DejaVuSans.ttf'))
        font_name = 'DJ'
    except:
        font_name = 'Helvetica'
        logging.warning("Шрифт DejaVu не найден, кириллица может отображаться некорректно")

    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = [
        Paragraph(clean_text("Коммерческое предложение"), ParagraphStyle('h', fontName=font_name, fontSize=18)),
        Spacer(1, 10*mm),
        Paragraph(clean_text(text_content), ParagraphStyle('p', fontName=font_name, fontSize=11))
    ]
    doc.build(story)
    buf.seek(0)
    return buf

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен на Amvera! Пришли аудио для создания КП.")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID: return
    
    msg = await update.message.reply_text("Обрабатываю аудио...")
    file = await (update.message.voice or update.message.audio).get_file()
    
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        with open(tmp.name, "rb") as f:
            # Исправленная отправка файла
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1", 
                file=("file.mp3", f), 
                response_format="text"
            )
        os.unlink(tmp.name)

    try:
        await msg.edit_text("Claude пишет текст...")
        resp = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=2000,
            messages=[{"role": "user", "content": f"Сделай структурированное КП из этого текста:\n{transcript}"}]
        )
        final_text = resp.content[0].text
        
        await msg.edit_text("Создаю PDF...")
        pdf = render_pdf(final_text)
        
        await update.message.reply_document(document=pdf, filename="KP.pdf")
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"Ошибка: {str(e)}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    app.run_polling()

if __name__ == "__main__":
    main()
