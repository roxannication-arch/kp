import os
import json
import logging
import tempfile
import unicodedata
from datetime import datetime
from io import BytesIO

# Устанавливаем UTF-8
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from openai import OpenAI
from anthropic import Anthropic
from fpdf import FPDF

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Конфигурация
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))

openai_client = OpenAI(api_key=OPENAI_API_KEY)
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
sessions = {}

def c(s):
    """Очистка текста для PDF."""
    if not s: return ""
    s = str(s)
    # Нормализация убирает проблемные символы типа \u2028
    s = unicodedata.normalize('NFC', s)
    return s.replace('\u2028', ' ').replace('\u2029', ' ').replace('\u0000', '')

def cobj(obj):
    if isinstance(obj, dict): return {k: cobj(v) for k, v in obj.items()}
    if isinstance(obj, list): return [cobj(v) for v in obj]
    if isinstance(obj, str): return c(obj)
    return obj

class KP_PDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font('DejaVu', '', 'DejaVuSans.ttf')
        self.add_font('DejaVu', 'B', 'DejaVuSans-Bold.ttf')
        self.set_auto_page_break(auto=True, margin=15)
        
    def header(self):
        if self.page_no() == 1:
            self.set_font('DejaVu', 'B', 14)
            self.set_text_color(15, 12, 42) # TEXT_DARK
            self.cell(0, 10, 'CareerPlus', ln=True)
            self.set_font('DejaVu', '', 9)
            self.set_text_color(153, 153, 153) # TEXT_LIGHT
            self.cell(0, 5, f'Персональное предложение · {datetime.now().strftime("%d.%m.%Y")}', ln=True)
            self.ln(5)

def render_pdf(kp):
    kp = cobj(kp)
    pdf = KP_PDF()
    pdf.add_page()
    
    # Цвета из вашего исходного кода
    PURPLE = (108, 92, 231)
    BG_GRAY = (244, 243, 255)
    TEXT_DARK = (15, 12, 42)
    TEXT_MID = (102, 102, 102)

    # BLOCK 1: HERO
    pdf.set_fill_color(*PURPLE)
    pdf.rect(10, pdf.get_y(), 190, 40, 'F')
    pdf.set_xy(15, pdf.get_y() + 5)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('DejaVu', '', 9)
    pdf.cell(0, 5, "CareerPlus · Персональное предложение", ln=True)
    pdf.set_font('DejaVu', 'B', 18)
    pdf.multi_cell(180, 10, kp["block1"]["headline"])
    pdf.set_y(pdf.get_y() + 10)

    # BLOCK 2: CASE
    pdf.ln(5)
    pdf.set_text_color(*PURPLE)
    pdf.set_font('DejaVu', 'B', 10)
    pdf.cell(0, 10, "ПОХОЖИЙ КЕЙС", ln=True)
    
    pdf.set_fill_color(*BG_GRAY)
    pdf.set_text_color(*TEXT_DARK)
    pdf.set_font('DejaVu', 'B', 14)
    pdf.multi_cell(0, 10, kp["block2"]["case_name"], fill=True)
    pdf.set_font('DejaVu', '', 10)
    pdf.set_text_color(*TEXT_MID)
    pdf.multi_cell(0, 7, f"\"{kp['block2']['case_quote']}\"")
    pdf.ln(5)

    # BLOCK 3: SERVICES
    pdf.set_font('DejaVu', 'B', 12)
    pdf.set_text_color(*PURPLE)
    pdf.cell(0, 10, "ЧТО МЫ БЕРЕМ НА СЕБЯ:", ln=True)
    for svc in kp["block3"]["services"]:
        pdf.set_font('DejaVu', 'B', 10)
        pdf.set_text_color(*TEXT_DARK)
        pdf.cell(0, 7, f"• {svc['title']}", ln=True)
        pdf.set_font('DejaVu', '', 9)
        pdf.set_text_color(*TEXT_MID)
        pdf.multi_cell(0, 5, svc['desc'])
        pdf.ln(2)

    # BLOCK 4: PROCESS
    pdf.ln(5)
    pdf.set_font('DejaVu', 'B', 12)
    pdf.set_text_color(*PURPLE)
    pdf.cell(0, 10, "ПРОЦЕСС РАБОТЫ:", ln=True)
    for step in kp["block4"]["steps"]:
        pdf.set_font('DejaVu', 'B', 10)
        pdf.set_text_color(*TEXT_DARK)
        pdf.multi_cell(0, 7, f"{step['num']}. {step['title']} ({step['time']})")
        pdf.set_font('DejaVu', '', 9)
        pdf.multi_cell(0, 5, step['desc'])
        pdf.ln(2)

    # BLOCK 5: PRICE
    pdf.ln(10)
    pdf.set_fill_color(*PURPLE)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('DejaVu', 'B', 16)
    pdf.cell(0, 20, f"ИНВЕСТИЦИЯ: {kp['block5']['price']}", ln=True, fill=True, align='C')
    pdf.set_font('DejaVu', '', 10)
    pdf.set_text_color(*TEXT_MID)
    pdf.multi_cell(0, 7, f"Вариант рассрочки: {kp['block5']['installment']}", align='C')

    # BLOCK 6: CTA
    pdf.ln(10)
    pdf.set_font('DejaVu', 'B', 12)
    pdf.set_text_color(*TEXT_DARK)
    pdf.multi_cell(0, 10, kp["block6"]["headline"], align='C')
    pdf.set_font('DejaVu', '', 10)
    pdf.multi_cell(0, 7, kp["block6"]["body"], align='C')

    return pdf.output()

# --- API LOGIC (Whisper & Claude) ---

SYSTEM_PROMPT = "Ты генерируешь коммерческое предложение для карьерного агентства CareerPlus... (Ваш полный промпт)"

def generate_kp(transcript):
    resp = anthropic_client.messages.create(
        model="claude-3-5-sonnet-20240620", max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role":"user","content":f"Транскрипт:\n\n{c(transcript)}"}]
    )
    raw = c(resp.content[0].text.strip())
    start = raw.find("{")
    end = raw.rfind("}")
    return json.loads(raw[start:end+1])

def edit_kp(kp, history, instruction):
    um = {"role":"user","content": f"Внеси правку: {instruction}\n\nКП:\n{json.dumps(kp,ensure_ascii=False)}"}
    resp = anthropic_client.messages.create(
        model="claude-3-5-sonnet-20240620", max_tokens=2000,
        system=SYSTEM_PROMPT, messages=history+[um]
    )
    raw = c(resp.content[0].text.strip())
    start = raw.find("{")
    end = raw.rfind("}")
    return json.loads(raw[start:end+1]), um, {"role":"assistant","content":resp.content[0].text}

# --- TELEGRAM HANDLERS ---

def get_session(uid):
    if uid not in sessions: sessions[uid] = {"kp":None,"history":[]}
    return sessions[uid]

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Пришлите аудиофайл для генерации КП.")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID: return
    session = get_session(update.effective_user.id)
    
    file = await (update.message.voice or update.message.audio or update.message.document).get_file()
    ext = ".mp3" # Упростим для примера
    
    msg = await update.message.reply_text("Транскрибирую и создаю КП...")
    
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        with open(tmp.name, "rb") as f:
            trans = openai_client.audio.transcriptions.create(model="whisper-1", file=f, language="ru", response_format="text")
        os.unlink(tmp.name)

    try:
        kp = generate_kp(trans)
        session["kp"] = kp
        pdf_bytes = render_pdf(kp)
        
        await update.message.reply_document(
            document=BytesIO(pdf_bytes),
            filename="CareerPlus_Proposal.pdf",
            caption="Ваше предложение готово!"
        )
        await msg.delete()
    except Exception as e:
        logging.error(e)
        await msg.edit_text(f"Ошибка: {e}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    if not session["kp"]: return
    
    msg = await update.message.reply_text("Обновляю КП...")
    try:
        updated, um, am = edit_kp(session["kp"], session["history"], update.message.text)
        session["history"] += [um, am]
        session["kp"] = updated
        pdf_bytes = render_pdf(updated)
        await update.message.reply_document(document=BytesIO(pdf_bytes), filename="Updated_Proposal.pdf")
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"Ошибка: {e}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.Document.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
