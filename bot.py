import os
import sys
import json
import logging
import tempfile
import unicodedata
import httpx
from datetime import datetime
from io import BytesIO

# Устанавливаем UTF-8
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

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Конфигурация из переменных окружения
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))

# Инициализация клиентов с обходом ошибки 'proxies'
openai_client = OpenAI(api_key=OPENAI_API_KEY, http_client=httpx.Client())
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY, http_client=httpx.Client())

sessions = {}

def c(s):
    """Ультимативная очистка текста от проблемных Unicode символов (\u2028 и др.)"""
    if not s: return ""
    if not isinstance(s, str): s = str(s)
    s = unicodedata.normalize('NFC', s)
    # Удаляем управляющие символы, кроме переноса строки, и заменяем разделители строк на пробелы
    s = s.replace('\u2028', ' ').replace('\u2029', ' ').replace('\u0000', '')
    return "".join(ch for ch in s if unicodedata.category(ch)[0] != "C" or ch == '\n')

def cobj(obj):
    """Рекурсивная очистка всех строк в объекте (для JSON от Claude)"""
    if isinstance(obj, dict): return {k: cobj(v) for k, v in obj.items()}
    if isinstance(obj, list): return [cobj(v) for v in obj]
    if isinstance(obj, str): return c(obj)
    return obj

# Цвета для оформления
PURPLE = colors.HexColor('#6c5ce7')
PURPLE_LIGHT = colors.HexColor('#f0edff')
TEXT_DARK = colors.HexColor('#0f0c2a')
TEXT_MID = colors.HexColor('#666666')
TEXT_LIGHT = colors.HexColor('#999999')

def render_pdf(kp):
    """Генерация PDF с использованием ReportLab"""
    buf = BytesIO()
    # Регистрация шрифтов (должны быть в папке с ботом)
    try:
        pdfmetrics.registerFont(TTFont('DJ', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DJB', 'DejaVuSans-Bold.ttf'))
    except:
        logging.warning("Шрифты DejaVu не найдены, использую стандартные (могут быть проблемы с кириллицей)")

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    W = A4[0] - 30*mm
    story = []

    def p(txt, fn='DJ', sz=10, clr=TEXT_MID, lead=14, align=0):
        return Paragraph(c(txt), ParagraphStyle('x', fontName=fn, fontSize=sz, textColor=clr, leading=lead, alignment=align))

    # Пример упрощенной верстки (Block 1)
    story.append(p(kp.get("block1", {}).get("headline", "Предложение"), 'DJB', 18, PURPLE))
    story.append(Spacer(1, 10*mm))
    
    # Block 2: Кейс
    case = kp.get("block2", {})
    story.append(p(f"Кейс: {case.get('case_name', '')}", 'DJB', 12, TEXT_DARK))
    story.append(p(case.get('case_quote', ''), 'DJ', 10, TEXT_MID))
    story.append(Spacer(1, 10*mm))

    # Block 5: Цена (выделенная)
    price = kp.get("block5", {})
    story.append(p(f"Инвестиция: {price.get('price', '')}", 'DJB', 14, PURPLE))
    
    doc.build(story)
    buf.seek(0)
    return buf

def generate_kp(transcript):
    """Запрос к Claude для генерации JSON структуры"""
    prompt = "Ты — эксперт. Создай КП в формате JSON на основе транскрипта. Структура: block1:{headline}, block2:{case_name, case_quote}, block5:{price, installment}..." # Упрощено для примера
    resp = anthropic_client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=2000,
        system=prompt,
        messages=[{"role": "user", "content": f"Транскрипт:\n{c(transcript)}"}]
    )
    text = resp.content[0].text
    start = text.find('{')
    end = text.rfind('}') + 1
    return json.loads(text[start:end])

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Пришли аудио или голосовое, и я сделаю из него КП.")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID: return
    
    msg = await update.message.reply_text("Слушаю аудио...")
    file = await (update.message.voice or update.message.audio).get_file()
    
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        with open(tmp.name, "rb") as f:
            transcript = openai_client.audio.transcriptions.create(model="whisper-1", file=f, response_format="text")
        os.unlink(tmp.name)

    try:
        await msg.edit_text("Генерирую структуру...")
        kp_raw = generate_kp(transcript)
        kp = cobj(kp_raw)
        
        await msg.edit_text("Рисую PDF...")
        pdf = render_pdf(kp)
        
        await update.message.reply_document(document=pdf, filename="Proposal.pdf")
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"Произошла ошибка: {str(e)}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    app.run_polling()

if __name__ == "__main__":
    main()
