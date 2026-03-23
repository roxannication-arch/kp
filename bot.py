import os
import sys
import json
import logging
import tempfile
from datetime import datetime
from io import BytesIO

# Устанавливаем UTF-8 ДО всего остального
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

logging.basicConfig(level=logging.WARNING)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))

openai_client = OpenAI(api_key=OPENAI_API_KEY)
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
sessions = {}


def c(s):
    """Убирает всё что не ASCII-safe из строки."""
    if not isinstance(s, str):
        s = str(s)
    result = []
    for ch in s:
        if ch in ('\u2028', '\u2029', '\u0000'):
            result.append(' ')
        else:
            result.append(ch)
    return ''.join(result)


def cobj(obj):
    """Рекурсивно чистит все строки в объекте."""
    if isinstance(obj, dict):
        return {k: cobj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [cobj(v) for v in obj]
    if isinstance(obj, str):
        return c(obj)
    return obj


SYSTEM_PROMPT = "Ты генерируешь коммерческое предложение для карьерного агентства CareerPlus (careerplus.us). КП отправляется клиенту после диагностической консультации. Вытащи из транскрипта ключевые данные и напиши КП живым конкретным языком. ГОЛОС: пиши как Роксана - основатель CareerPlus. Прямо без корпоративщины. Миксует русский и английский: оффер, LinkedIn, ATS, kick-off, market research, тайтл, lay-off. Короткие предложения. ЗАПРЕЩЕНО: в рамках нашего сотрудничества, мы рады предложить, индивидуальный подход, команда профессионалов, любой канцелярит. ЧТО ВЫТАЩИТЬ: текущая зарплата и целевая, локация, сколько лет в индустрии, специализация, конкретные боли, тайминг. НЕ указывать: иммиграционный статус, имя клиента, Telegram клиента. КЕЙС: та же индустрия, срок поиска СТРОГО 2-5 месяцев, рост зарплаты +15k-35k. СТРУКТУРА 6 БЛОКОВ: БЛОК1 заголовок [Цель] это реально вот как мы это сделаем + 4 метрики. БЛОК2 кейс + цифры 200+ офферов за 2 года +22K средний рост 3.5 мес средний срок. БЛОК3 Твоя задача прийти на интервью всё остальное наше + 5 услуг ручной поиск utp true. БЛОК4 От тебя нужен 1 час дальше наша работа + 5 шагов с таймингом. БЛОК5 3100 и твой следующий шаг в карьере уже в работе цена PayPal ROI продление 690 мес. БЛОК6 конкретный CTA без имени и TG footer Договор отправлен на email вопросы по ходу чтения пиши. ФОРМАТ: ТОЛЬКО валидный JSON без markdown. {\"block1\":{\"headline\":\"...\",\"meta\":[{\"label\":\"Специалист\",\"value\":\"...\"},{\"label\":\"Локация\",\"value\":\"...\"},{\"label\":\"Цель\",\"value\":\"...\"},{\"label\":\"Старт\",\"value\":\"...\"}]},\"block2\":{\"stats\":[{\"num\":\"200+\",\"label\":\"офферов за 2 года\"},{\"num\":\"+22K\",\"label\":\"средний рост зарплаты\"},{\"num\":\"3.5 мес\",\"label\":\"средний срок до оффера\"}],\"case_name\":\"...\",\"case_sub\":\"...\",\"case_before_role\":\"...\",\"case_before_sal\":\"...\",\"case_after_role\":\"...\",\"case_after_sal\":\"...\",\"case_quote\":\"...\",\"case_badges\":[\"...\",\"...\",\"...\"]},\"block3\":{\"headline\":\"Твоя задача - прийти на интервью. Всё остальное - наше.\",\"services\":[{\"num\":\"01\",\"title\":\"Market Research\",\"desc\":\"...\",\"utp\":false},{\"num\":\"02\",\"title\":\"Резюме\",\"desc\":\"...\",\"utp\":false},{\"num\":\"03\",\"title\":\"LinkedIn\",\"desc\":\"...\",\"utp\":false},{\"num\":\"04\",\"title\":\"Ручной поиск\",\"desc\":\"...\",\"utp\":true},{\"num\":\"05\",\"title\":\"Мок-интервью\",\"desc\":\"...\",\"utp\":false}]},\"block4\":{\"headline\":\"От тебя нужен 1 час. Дальше - наша работа\",\"steps\":[{\"num\":\"01\",\"title\":\"Договор + оплата\",\"time\":\"День 1\",\"desc\":\"...\"},{\"num\":\"02\",\"title\":\"Kick-off созвон\",\"time\":\"День 1-3\",\"desc\":\"...\"},{\"num\":\"03\",\"title\":\"Research + резюме + LinkedIn\",\"time\":\"Нед. 1-1.5\",\"desc\":\"...\"},{\"num\":\"04\",\"title\":\"Активный поиск\",\"time\":\"С нед. 2\",\"desc\":\"...\"},{\"num\":\"05\",\"title\":\"Интервью оффер\",\"time\":\"С нед. 3-4\",\"desc\":\"...\"}]},\"block5\":{\"headline\":\"3100 и твой следующий шаг в карьере уже в работе\",\"price\":\"$3 100\",\"installment\":\"PayPal Pay Later разбивает без больших процентов\",\"includes\":[\"...\",\"...\",\"...\",\"...\",\"...\"],\"roi\":\"Один оффер на +20K в год окупает вложение за первые два месяца.\",\"extension_price\":\"$690/месяц\",\"extension_desc\":\"...\",\"tip\":\"Пока мы ищем - инвестируй время в скиллы или английский.\"},\"block6\":{\"headline\":\"...\",\"body\":\"...\",\"footer\":\"Договор отправлен на email - вопросы по ходу чтения, пиши.\"}}"

PURPLE = colors.HexColor('#6c5ce7')
PURPLE_LIGHT = colors.HexColor('#f0edff')
PURPLE_BORDER = colors.HexColor('#c4b5fd')
GRAY_BG = colors.HexColor('#f4f3ff')
GRAY_LIGHT = colors.HexColor('#faf9ff')
TEXT_DARK = colors.HexColor('#0f0c2a')
TEXT_MID = colors.HexColor('#666666')
TEXT_LIGHT = colors.HexColor('#999999')
WHITE = colors.white


def render_pdf(kp):
    pdfmetrics.registerFont(TTFont('DJ', 'DejaVuSans.ttf'))
    pdfmetrics.registerFont(TTFont('DJB', 'DejaVuSans-Bold.ttf'))
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    W = A4[0] - 30*mm
    story = []
    b1, b2, b3, b4, b5, b6 = (kp["block1"], kp["block2"], kp["block3"],
                                kp["block4"], kp["block5"], kp["block6"])

    def sp(h=4): return Spacer(1, h*mm)
    def p(txt, fn='DJ', sz=10, clr=TEXT_MID, lead=14, align=0):
        return Paragraph(txt, ParagraphStyle('x', fontName=fn, fontSize=sz,
                                              textColor=clr, leading=lead, alignment=align))
    def box(items, bg=WHITE, bc=PURPLE_BORDER):
        t = Table([[items]], colWidths=[W])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),bg), ('BOX',(0,0),(-1,-1),0.5,bc),
            ('ROUNDEDCORNERS',[6,6,6,6]),
            ('TOPPADDING',(0,0),(-1,-1),10), ('BOTTOMPADDING',(0,0),(-1,-1),10),
            ('LEFTPADDING',(0,0),(-1,-1),12), ('RIGHTPADDING',(0,0),(-1,-1),12),
        ]))
        return t

    today = datetime.now().strftime("%d.%m.%Y")

    # HEADER
    hdr = Table([[p('<b>CareerPlus</b>','DJB',13,TEXT_DARK),
                  p(f'Персональное предложение · {today}','DJ',9,TEXT_LIGHT)]],
                colWidths=[W*0.5,W*0.5])
    hdr.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),WHITE), ('BOX',(0,0),(-1,-1),0.5,colors.HexColor('#e8e4ff')),
        ('ROUNDEDCORNERS',[6,6,6,6]),
        ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ALIGN',(1,0),(1,0),'RIGHT'),
    ]))
    story += [hdr, sp()]

    # HERO
    meta_t = Table(
        [[p(m["label"].upper(),'DJ',8,colors.HexColor('#ffffff88')) for m in b1["meta"]],
         [p(m["value"],'DJB',10,WHITE) for m in b1["meta"]]],
        colWidths=[W/4]*4)
    meta_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#ffffff15')),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('LINEAFTER',(0,0),(2,-1),0.5,colors.HexColor('#ffffff25')),
    ]))
    hero = Table([[
        [p('CareerPlus · Персональное предложение','DJ',8,colors.HexColor('#ffffffaa')),
         sp(3), p(b1["headline"],'DJB',16,WHITE,20), sp(4), meta_t]
    ]], colWidths=[W])
    hero.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),PURPLE), ('ROUNDEDCORNERS',[8,8,8,8]),
        ('TOPPADDING',(0,0),(-1,-1),14),('BOTTOMPADDING',(0,0),(-1,-1),14),
        ('LEFTPADDING',(0,0),(-1,-1),16),('RIGHTPADDING',(0,0),(-1,-1),16),
    ]))
    story += [hero, sp()]

    # CASE
    st = Table(
        [[p(s["num"],'DJB',18,PURPLE,22,TA_CENTER) for s in b2["stats"]],
         [p(s["label"],'DJ',9,TEXT_LIGHT,11,TA_CENTER) for s in b2["stats"]]],
        colWidths=[W/3]*3)
    st.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),GRAY_BG),('BOX',(0,0),(-1,-1),0.5,PURPLE_BORDER),
        ('LINEAFTER',(0,0),(1,-1),0.5,PURPLE_BORDER),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
    ]))
    cw = W/2-2*mm
    bs = Table([[
        [p('БЫЛО','DJ',8,TEXT_LIGHT), p(b2["case_before_role"],'DJ',10,TEXT_MID),
         p(b2["case_before_sal"],'DJB',13,TEXT_LIGHT)],
        [p('СТАЛО','DJ',8,TEXT_LIGHT), p(b2["case_after_role"],'DJ',10,TEXT_DARK),
         p(b2["case_after_sal"],'DJB',15,PURPLE)]
    ]], colWidths=[cw,cw])
    bs.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(0,-1),GRAY_LIGHT),('BACKGROUND',(1,0),(1,-1),GRAY_BG),
        ('BOX',(0,0),(-1,-1),0.5,PURPLE_BORDER),('LINEAFTER',(0,0),(0,-1),0.5,PURPLE_BORDER),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
    ]))
    story.append(box([
        p('ПОХОЖИЙ КЕЙС','DJB',8,PURPLE), sp(2), st, sp(3),
        p(b2["case_name"],'DJB',13,PURPLE), p(b2["case_sub"],'DJ',9,TEXT_LIGHT),
        sp(2), bs, sp(3),
        p(f'"{b2["case_quote"]}"','DJ',10,TEXT_MID),
        sp(2), p('  '.join(b2["case_badges"]),'DJ',9,PURPLE),
    ]))
    story.append(sp())

    # SERVICES
    si = [p('ЧТО МЫ БЕРЕМ НА СЕБЯ','DJB',8,PURPLE), p(b3["headline"],'DJB',13,TEXT_DARK)]
    for svc in b3["services"]:
        bg = PURPLE_LIGHT if svc.get("utp") else GRAY_LIGHT
        bc = PURPLE_BORDER if svc.get("utp") else colors.HexColor('#e8e4ff')
        badge = ' [УТП]' if svc.get("utp") else ''
        r = Table([[p(f'<b>{svc["num"]}</b>','DJB',10,PURPLE),
                    [p(f'<b>{svc["title"]}{badge}</b>','DJB',11,TEXT_DARK),
                     p(svc["desc"],'DJ',9,TEXT_LIGHT)]
                   ]], colWidths=[10*mm,W-10*mm])
        r.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),bg),('BOX',(0,0),(-1,-1),0.5,bc),
            ('ROUNDEDCORNERS',[5,5,5,5]),
            ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
            ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ]))
        si += [sp(2), r]
    story.append(box(si))
    story.append(sp())

    # PROCESS
    pi = [p('ПРОЦЕСС','DJB',8,PURPLE), p(b4["headline"],'DJB',13,TEXT_DARK)]
    for step in b4["steps"]:
        r = Table([[p(f'<b>{step["num"]}</b>','DJB',9,PURPLE,12,TA_CENTER),
                    [p(f'<b>{step["title"]}</b>  <font color="#6c5ce7">{step["time"]}</font>','DJB',11,TEXT_DARK),
                     p(step["desc"],'DJ',9,TEXT_LIGHT)]
                   ]], colWidths=[10*mm,W-10*mm])
        r.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2),
            ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
        ]))
        pi += [sp(2), r]
    story.append(box(pi))
    story.append(sp())

    # PRICE
    inc = '<br/>'.join([f'• {i}' for i in b5["includes"]])
    pt = Table([[
        [p('ОСНОВНОЙ ПАКЕТ 2.5 МЕСЯЦА','DJ',8,colors.HexColor('#ffffff88')),
         p(b5["price"],'DJB',26,WHITE,30),
         p('или рассрочка','DJ',11,colors.HexColor('#ffffffaa')),
         p(b5["installment"],'DJ',9,colors.HexColor('#ffffff88')),
         sp(3), p(inc,'DJ',10,colors.HexColor('#ffffffcc'),16)]
    ]], colWidths=[W])
    pt.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),PURPLE),('ROUNDEDCORNERS',[8,8,8,8]),
        ('TOPPADDING',(0,0),(-1,-1),14),('BOTTOMPADDING',(0,0),(-1,-1),14),
        ('LEFTPADDING',(0,0),(-1,-1),16),('RIGHTPADDING',(0,0),(-1,-1),16),
    ]))
    rt = Table([[p(b5["roi"],'DJ',10,TEXT_MID)]], colWidths=[W])
    rt.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),PURPLE_LIGHT),('BOX',(0,0),(-1,-1),0.5,PURPLE_BORDER),
        ('ROUNDEDCORNERS',[6,6,6,6]),
        ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),
    ]))
    et = Table([[
        [p('ПРОДЛЕНИЕ','DJ',8,TEXT_LIGHT),
         p(b5["extension_price"],'DJB',15,TEXT_DARK),
         p(b5["extension_desc"],'DJ',9,TEXT_LIGHT)]
    ]], colWidths=[W])
    et.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),GRAY_LIGHT),('BOX',(0,0),(-1,-1),0.5,colors.HexColor('#e8e4ff')),
        ('ROUNDEDCORNERS',[6,6,6,6]),
        ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),
    ]))
    tip_t = Table([[p(b5["tip"],'DJ',10,TEXT_MID)]], colWidths=[W])
    tip_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),GRAY_BG),('BOX',(0,0),(-1,-1),0.5,PURPLE_BORDER),
        ('ROUNDEDCORNERS',[6,6,6,6]),
        ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),
    ]))
    story.append(box([
        p('ИНВЕСТИЦИЯ','DJB',8,PURPLE), p(b5["headline"],'DJB',13,TEXT_DARK),
        pt, sp(3), rt, sp(3), et, sp(3), tip_t,
    ]))
    story.append(sp())

    # CTA
    cta = Table([[
        [p('СЛЕДУЮЩИЙ ШАГ','DJ',8,colors.HexColor('#ffffffaa'),12,TA_CENTER), sp(3),
         p(b6["headline"],'DJB',15,WHITE,19,TA_CENTER), sp(3),
         p(b6["body"],'DJ',10,colors.HexColor('#ffffffaa'),14,TA_CENTER), sp(3),
         p(b6["footer"],'DJ',9,colors.HexColor('#ffffff66'),12,TA_CENTER)]
    ]], colWidths=[W])
    cta.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),PURPLE),('ROUNDEDCORNERS',[8,8,8,8]),
        ('TOPPADDING',(0,0),(-1,-1),16),('BOTTOMPADDING',(0,0),(-1,-1),16),
        ('LEFTPADDING',(0,0),(-1,-1),16),('RIGHTPADDING',(0,0),(-1,-1),16),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
    ]))
    story.append(cta)

    doc.build(story)
    return buf.getvalue()


def generate_kp(transcript):
    transcript = c(transcript)
    resp = anthropic_client.messages.create(
        model="claude-opus-4-5", max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role":"user","content":f"Транскрипт:\n\n{transcript}"}]
    )
    raw = c(resp.content[0].text.strip())
    return json.loads(raw[raw.index("{"):raw.rindex("}")+1])


def edit_kp(kp, history, instruction):
    instruction = c(instruction)
    um = {"role":"user","content":c(
        f"Внеси правку: {instruction}\n\nКП:\n{json.dumps(kp,ensure_ascii=True)}\n\nВерни ТОЛЬКО обновлённый JSON."
    )}
    resp = anthropic_client.messages.create(
        model="claude-opus-4-5", max_tokens=2000,
        system=SYSTEM_PROMPT, messages=history+[um]
    )
    raw = c(resp.content[0].text.strip())
    updated = json.loads(raw[raw.index("{"):raw.rindex("}")+1])
    return updated, um, {"role":"assistant","content":resp.content[0].text}


def get_session(uid):
    if uid not in sessions:
        sessions[uid] = {"kp":None,"history":[]}
    return sessions[uid]


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text(
        "Скинь голосовое или аудиофайл — пришлю КП в PDF.\n"
        "Форматы: голосовые, .mp3, .m4a, .ogg, .wav"
    )


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        return
    session = get_session(update.effective_user.id)

    if update.message.voice:
        file = await update.message.voice.get_file()
        ext = ".ogg"
    elif update.message.audio:
        file = await update.message.audio.get_file()
        ext = os.path.splitext(update.message.audio.file_name or "a.mp3")[-1] or ".mp3"
    elif update.message.document:
        doc = update.message.document
        if not (doc.mime_type and doc.mime_type.startswith("audio")):
            await update.message.reply_text("Пришли аудиофайл.")
            return
        file = await doc.get_file()
        ext = os.path.splitext(doc.file_name or "a.mp3")[-1] or ".mp3"
    else:
        await update.message.reply_text("Формат не распознан.")
        return

    msg = await update.message.reply_text("Транскрибирую...")
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await file.download_to_drive(tmp_path)
        with open(tmp_path, "rb") as f:
            transcript_text = openai_client.audio.transcriptions.create(
                model="whisper-1", file=f, language="ru",
                response_format="text"
            )
        transcript_text = c(str(transcript_text).strip())
        if not transcript_text:
            await msg.edit_text("Не удалось распознать речь.")
            return

        await msg.edit_text("Составляю КП...")
        kp = cobj(generate_kp(transcript_text))
        session["kp"] = kp
        session["history"] = []

        await msg.edit_text("Верстаю PDF...")
        pdf = render_pdf(kp)
        await msg.delete()
        await update.message.reply_document(
            document=pdf, filename="CareerPlus_KP.pdf",
            caption="Готово! Нужны правки — пиши сюда."
        )
    except Exception as err:
        await msg.edit_text(f"Ошибка: {c(str(err))}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        return
    session = get_session(update.effective_user.id)
    if not session["kp"]:
        await update.message.reply_text("Сначала пришли запись.")
        return

    msg = await update.message.reply_text("Вношу правку...")
    try:
        updated, um, am = edit_kp(session["kp"], session["history"],
                                   update.message.text.strip())
        session["history"] += [um, am]
        session["kp"] = cobj(updated)
        pdf = render_pdf(session["kp"])
        await msg.delete()
        await update.message.reply_document(
            document=pdf, filename="CareerPlus_KP.pdf",
            caption="Готово! Ещё правки — пиши."
        )
    except Exception as err:
        await msg.edit_text(f"Ошибка: {c(str(err))}")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(
        filters.VOICE | filters.AUDIO | filters.Document.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
