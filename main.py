import os
import re
import json
import hmac
import time
import hashlib
import sqlite3
import smtplib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qsl
from email.message import EmailMessage

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
DB_PATH = os.getenv("DB_PATH", "garant_service.db")

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587").strip() or "587")
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
MAIL_FROM = os.getenv("MAIL_FROM", SMTP_USER).strip()
SMTP_TLS = os.getenv("SMTP_TLS", "1").strip() != "0"


def parse_admin_ids() -> set[int]:
    result = set()
    for item in ADMIN_IDS_RAW.replace(" ", "").split(","):
        if item.isdigit():
            result.add(int(item))
    return result


ADMIN_IDS = parse_admin_ids()

app = FastAPI(title="Garant Service Mini App")

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row


DEFAULTS = {
    "company_name": "GARANT SERVICE",
    "hero_text": (
        "Гарантії, яким довіряють\n\n"
        "ПТ «ГАРАНТ СЕРВІС» — надійний фінансовий партнер для бізнесу "
        "у сфері митних, тендерних та договірних гарантій. "
        "Допомагаємо швидко оформити гарантію, мінімізувати затримки "
        "та забезпечити стабільну роботу вашого бізнесу."
    ),
    "about": (
        "ПТ «ГАРАНТ СЕРВІС» — фінансова установа, включена Національним банком України "
        "до Державного реєстру фінансових установ.\n\n"
        "Компанія має ліцензію НБУ на надання послуг фінансової компанії в частині "
        "надання гарантій.\n\n"
        "Працюємо з бізнесом, який потребує швидкого та зрозумілого оформлення гарантій."
    ),
    "services": (
        "1. Загальні гарантії\n"
        "Для забезпечення митних платежів щодо товарів за декількома митними деклараціями.\n\n"
        "2. Індивідуальні гарантії\n"
        "Для забезпечення митних платежів щодо товарів за однією митною декларацією.\n\n"
        "3. Тендерні гарантії\n"
        "Для участі в тендерах без необхідності заморожувати власні кошти.\n\n"
        "4. Гарантії виконання договорів\n"
        "Для забезпечення виконання договірних зобов’язань перед замовником."
    ),
    "advantages": (
        "✅ Ліцензована фінансова установа\n"
        "✅ Оперативне оформлення документів\n"
        "✅ Професійна команда\n"
        "✅ Доступність послуг 24/7\n"
        "✅ Індивідуальні умови тарифікації\n"
        "✅ Економія часу при проходженні процедур\n"
        "✅ Зниження фінансового навантаження для бізнесу\n"
        "✅ Консультації щодо митних процедур, документів та брокерської діяльності"
    ),
    "pricing": (
        "Вартість гарантії розраховується індивідуально.\n\n"
        "Вона залежить від:\n"
        "• типу гарантії;\n"
        "• вартості товару;\n"
        "• суми митних платежів;\n"
        "• тендерної пропозиції;\n"
        "• вартості договору;\n"
        "• строку дії гарантії.\n\n"
        "Щоб отримати точний розрахунок, залиште заявку в додатку."
    ),
    "faq": (
        "Що таке гарантія?\n"
        "Гарантія — це письмове зобов’язання гаранта виконати платіж або інші умови, "
        "передбачені законодавством чи договором.\n\n"
        "Які види гарантій бувають?\n"
        "Індивідуальні, загальні, тендерні гарантії, гарантії виконання договору, "
        "гарантії повернення авансового платежу, платіжні та туристичні гарантії.\n\n"
        "Як визначити розмір необхідної гарантії?\n"
        "Розмір гарантії залежить від вартості товару, митних платежів, тендерної пропозиції "
        "або договору.\n\n"
        "Які документи потрібні для оформлення гарантії?\n"
        "Установчі документи компанії, анкета компанії та заявка на оформлення гарантії.\n\n"
        "Скільки коштує гарантія?\n"
        "Вартість розраховується індивідуально.\n\n"
        "Чи можна скасувати або замінити гарантію?\n"
        "Так, за запитом клієнта, якщо інше не передбачено договором або законодавством."
    ),
    "contacts": (
        "+38 067 000 28 11\n"
        "+38 067 795 10 90\n\n"
        "gp.garant.su@ukr.net\n"
        "gp.garant.docs@ukr.net\n\n"
        "Адреса:\n"
        "Україна, 21005, м. Вінниця,\n"
        "вул. Генерала Гандзюка, буд. 17, приміщення 341\n\n"
        "Графік роботи:\n"
        "Менеджер з видачі гарантій — 24/7\n\n"
        "Адміністрація:\n"
        "Пн–Пт з 09:00 до 18:00\n"
        "Сб–Нд — вихідний\n\n"
        "Працюємо по всій території України, окрім тимчасово окупованих територій."
    ),
    "logo_image": "/assets/logo.png",
    "background_image": "/assets/truck_bg.jpg",
    "email_enabled": "1",
    "email_to": "gp.garant.su@ukr.net\ngp.garant.docs@ukr.net",
}


def db_init():
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS content (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tg_name TEXT DEFAULT '',
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            company TEXT DEFAULT '',
            guarantee_type TEXT DEFAULT '',
            route TEXT DEFAULT '',
            cargo TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )

    lead_columns = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
    if "guarantee_type" not in lead_columns:
        conn.execute("ALTER TABLE leads ADD COLUMN guarantee_type TEXT DEFAULT ''")

    for key, value in DEFAULTS.items():
        conn.execute(
            "INSERT OR IGNORE INTO content (key, value) VALUES (?, ?)",
            (key, value),
        )

    conn.commit()


db_init()

bot_app: Optional[Application] = None


class InitPayload(BaseModel):
    initData: str


class LeadPayload(BaseModel):
    initData: str
    name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=5, max_length=50)
    company: str = Field(default="", max_length=150)
    guarantee_type: str = Field(default="", max_length=150)
    route: str = Field(default="", max_length=300)
    cargo: str = Field(default="", max_length=700)
    comment: str = Field(default="", max_length=1200)


class ContentSavePayload(BaseModel):
    initData: str
    company_name: str = Field(min_length=1, max_length=5000)
    hero_text: str = Field(min_length=1, max_length=8000)
    about: str = Field(min_length=1, max_length=12000)
    services: str = Field(min_length=1, max_length=15000)
    advantages: str = Field(min_length=1, max_length=12000)
    pricing: str = Field(min_length=1, max_length=12000)
    faq: str = Field(min_length=1, max_length=20000)
    contacts: str = Field(min_length=1, max_length=12000)
    logo_image: str = Field(default="", max_length=3500000)
    background_image: str = Field(default="", max_length=5000000)
    email_enabled: bool = True
    email_to: str = Field(default="", max_length=3000)


class TestEmailPayload(BaseModel):
    initData: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_content() -> dict:
    rows = conn.execute("SELECT key, value FROM content").fetchall()
    data = {row["key"]: row["value"] for row in rows}
    for key, value in DEFAULTS.items():
        data.setdefault(key, value)
    return data


def save_content(data: dict):
    for key, value in data.items():
        conn.execute(
            """
            INSERT INTO content (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
    conn.commit()


def validate_telegram_init_data(init_data: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="BOT_TOKEN is not configured")

    if not init_data:
        raise HTTPException(status_code=401, detail="Open Mini App from Telegram bot button")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)

    if not received_hash:
        raise HTTPException(status_code=401, detail="Telegram hash is missing")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(pairs.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=401, detail="Bad Telegram signature")

    auth_date = int(pairs.get("auth_date", "0") or "0")
    if auth_date and time.time() - auth_date > 7 * 24 * 60 * 60:
        raise HTTPException(status_code=401, detail="Telegram initData expired")

    try:
        user = json.loads(pairs.get("user", "{}"))
        user_id = int(user["id"])
    except Exception:
        raise HTTPException(status_code=401, detail="Telegram user not found")

    return {
        "user_id": user_id,
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "username": user.get("username", ""),
    }


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def smtp_is_configured() -> bool:
    return bool(SMTP_HOST and MAIL_FROM)


def parse_email_list(raw: str) -> list[str]:
    parts = re.split(r"[\s,;]+", raw or "")
    emails = []
    for item in parts:
        item = item.strip()
        if not item:
            continue
        if "@" in item and "." in item.split("@")[-1]:
            emails.append(item)
    return list(dict.fromkeys(emails))


def send_email_message(to_emails: list[str], subject: str, body: str):
    if not smtp_is_configured():
        raise RuntimeError("SMTP is not configured")

    if not to_emails:
        raise RuntimeError("No recipient emails")

    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = ", ".join(to_emails)
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        if SMTP_TLS:
            server.starttls()
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not WEBAPP_URL:
        await update.message.reply_text(
            "WEBAPP_URL ще не налаштований на сервері."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📱 Відкрити додаток",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )
        ]
    ])

    await update.message.reply_text(
        "Вітаємо 👋\n\n"
        "Відкрийте Mini App “GARANT SERVICE”, щоб переглянути інформацію або залишити заявку.",
        reply_markup=keyboard,
    )


@app.on_event("startup")
async def on_startup():
    global bot_app

    if not BOT_TOKEN:
        print("BOT_TOKEN is not set")
        return

    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)

    print("Telegram bot started")


@app.on_event("shutdown")
async def on_shutdown():
    global bot_app

    if bot_app:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        print("Telegram bot stopped")


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0" />
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <title>GARANT SERVICE</title>

  <style>
    * { box-sizing: border-box; }

    :root {
      --bg: #07111f;
      --card: rgba(13, 24, 42, 0.88);
      --card2: rgba(18, 33, 56, 0.92);
      --line: rgba(255,255,255,0.10);
      --text: #f8fafc;
      --muted: #a9b8cb;
      --accent: #38bdf8;
      --accent2: #22c55e;
      --danger: #fb7185;
    }

    body {
      margin: 0;
      font-family: Arial, sans-serif;
      background:
        radial-gradient(circle at 10% 0%, rgba(56,189,248,0.16), transparent 32%),
        linear-gradient(180deg, #06111f, #0b1322);
      color: var(--text);
      padding: 12px;
    }

    .wrap {
      max-width: 820px;
      margin: 0 auto;
      padding-bottom: 28px;
    }

    .hero {
      min-height: 420px;
      border-radius: 28px;
      padding: 18px;
      margin-bottom: 14px;
      border: 1px solid var(--line);
      background-size: cover;
      background-position: center;
      overflow: hidden;
      position: relative;
      box-shadow: 0 18px 55px rgba(0,0,0,0.38);
    }

    .hero::after {
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(180deg, rgba(5,13,25,0.20), rgba(5,13,25,0.84)),
        radial-gradient(circle at 50% 65%, rgba(56,189,248,0.16), transparent 38%);
      pointer-events: none;
    }

    .hero-content {
      position: relative;
      z-index: 2;
      min-height: 384px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }

    .logo-box {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      background: rgba(255,255,255,0.88);
      color: #111827;
      border-radius: 18px;
      padding: 10px 12px;
      width: fit-content;
      max-width: 100%;
      box-shadow: 0 10px 35px rgba(0,0,0,0.25);
    }

    .logo-box img {
      max-width: 185px;
      max-height: 58px;
      object-fit: contain;
      display: block;
    }

    h1 {
      font-size: 31px;
      line-height: 1.08;
      margin: 0 0 12px;
      letter-spacing: -0.03em;
      white-space: pre-line;
    }

    h2 {
      font-size: 21px;
      margin: 0 0 12px;
      letter-spacing: -0.02em;
    }

    h3 {
      font-size: 16px;
      margin: 0 0 8px;
    }

    .hero-bottom {
      padding-top: 30px;
    }

    .hero-text {
      color: #dbeafe;
      line-height: 1.5;
      white-space: pre-line;
      font-size: 15px;
      max-width: 650px;
      text-shadow: 0 2px 12px rgba(0,0,0,0.55);
    }

    .pill-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 14px;
    }

    .pill {
      background: rgba(56,189,248,0.15);
      border: 1px solid rgba(125,211,252,0.25);
      color: #dff6ff;
      border-radius: 999px;
      padding: 8px 10px;
      font-size: 13px;
      font-weight: 700;
      backdrop-filter: blur(10px);
    }

    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 16px;
      margin-bottom: 12px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.22);
      backdrop-filter: blur(12px);
    }

    .text {
      color: #d7e4f4;
      line-height: 1.48;
      white-space: pre-line;
      font-size: 15px;
    }

    .muted {
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }

    .tabs {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 9px;
      margin-bottom: 12px;
      position: sticky;
      top: 0;
      z-index: 20;
      padding: 8px 0;
      background: linear-gradient(180deg, rgba(7,17,31,0.95), rgba(7,17,31,0.78));
      backdrop-filter: blur(14px);
    }

    .tab-btn,
    button {
      width: 100%;
      border: 0;
      border-radius: 16px;
      padding: 13px 12px;
      font-size: 14px;
      font-weight: 800;
      cursor: pointer;
      background: #16243a;
      color: #ffffff;
      border: 1px solid rgba(255,255,255,0.08);
    }

    .tab-btn.active {
      background: linear-gradient(135deg, #38bdf8, #67e8f9);
      color: #04111d;
      box-shadow: 0 10px 22px rgba(56,189,248,0.18);
    }

    .primary {
      background: linear-gradient(135deg, #22c55e, #86efac);
      color: #04130a;
    }

    .secondary {
      background: linear-gradient(135deg, #38bdf8, #67e8f9);
      color: #04111d;
    }

    .danger {
      background: rgba(251,113,133,0.18);
      color: #fecdd3;
      border-color: rgba(251,113,133,0.28);
    }

    input,
    textarea,
    select {
      width: 100%;
      border: 1px solid rgba(255,255,255,0.13);
      border-radius: 15px;
      background: rgba(3, 9, 20, 0.78);
      color: white;
      padding: 13px;
      margin: 8px 0;
      font-size: 15px;
      outline: none;
    }

    textarea {
      min-height: 118px;
      resize: vertical;
      line-height: 1.45;
    }

    label {
      display: block;
      margin-top: 12px;
      color: #dbeafe;
      font-weight: 800;
      font-size: 14px;
    }

    .hidden { display: none !important; }

    .status {
      margin-top: 10px;
      font-size: 14px;
      color: #a7f3d0;
      white-space: pre-line;
    }

    .error {
      margin-top: 10px;
      font-size: 14px;
      color: #fecdd3;
      white-space: pre-line;
    }

    .grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }

    .mini-card {
      background: rgba(255,255,255,0.055);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 18px;
      padding: 13px;
    }

    .lead-card {
      background: rgba(255,255,255,0.055);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 18px;
      padding: 13px;
      margin-top: 10px;
      white-space: pre-line;
    }

    .admin-badge {
      display: inline-block;
      margin-top: 10px;
      background: rgba(34,197,94,0.16);
      color: #86efac;
      border: 1px solid rgba(134,239,172,0.25);
      padding: 7px 10px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 800;
    }

    .preview {
      max-width: 100%;
      border-radius: 16px;
      border: 1px solid rgba(255,255,255,0.10);
      margin-top: 8px;
      display: block;
    }

    .preview.logo-preview {
      max-height: 75px;
      background: white;
      padding: 8px;
      object-fit: contain;
    }

    .admin-section {
      margin-top: 16px;
      padding-top: 14px;
      border-top: 1px solid rgba(255,255,255,0.10);
    }

    @media (min-width: 720px) {
      .tabs {
        grid-template-columns: repeat(5, 1fr);
      }

      .grid {
        grid-template-columns: 1fr 1fr;
      }

      .hero {
        min-height: 500px;
      }
    }
  </style>
</head>

<body>
  <div class="wrap">
    <div class="hero" id="heroCard">
      <div class="hero-content">
        <div>
          <div class="logo-box">
            <img id="logoImg" src="/assets/logo.png" alt="GARANT SERVICE" />
          </div>
          <div id="adminBadge" class="admin-badge hidden">⚙️ Ви адмін</div>
        </div>

        <div class="hero-bottom">
          <h1 id="companyName">GARANT SERVICE</h1>
          <div class="hero-text" id="heroText">Завантаження...</div>
          <div class="pill-row">
            <div class="pill">24/7</div>
            <div class="pill">Митні гарантії</div>
            <div class="pill">Тендерні гарантії</div>
          </div>
          <div style="margin-top:14px;">
            <button class="primary" onclick="showTab('lead', document.getElementById('leadTabBtn'))">📝 Залишити заявку</button>
          </div>
        </div>
      </div>
    </div>

    <div class="tabs" id="tabs">
      <button class="tab-btn active" onclick="showTab('home', this)">🏠 Головна</button>
      <button class="tab-btn" onclick="showTab('about', this)">🏢 Про нас</button>
      <button class="tab-btn" onclick="showTab('services', this)">📄 Послуги</button>
      <button class="tab-btn" onclick="showTab('advantages', this)">⭐ Переваги</button>
      <button class="tab-btn" onclick="showTab('pricing', this)">💰 Вартість</button>
      <button class="tab-btn" onclick="showTab('faq', this)">❓ FAQ</button>
      <button class="tab-btn" id="leadTabBtn" onclick="showTab('lead', this)">📝 Заявка</button>
      <button class="tab-btn" onclick="showTab('contacts', this)">📞 Контакти</button>
      <button id="adminTabBtn" class="tab-btn hidden" onclick="showTab('admin', this)">⚙️ Адмінка</button>
    </div>

    <div id="screen-home" class="card screen">
      <h2>Гарантії, яким довіряють</h2>
      <div class="text" id="homeText"></div>
    </div>

    <div id="screen-about" class="card screen hidden">
      <h2>🏢 Про компанію</h2>
      <div class="text" id="aboutText"></div>
    </div>

    <div id="screen-services" class="card screen hidden">
      <h2>📄 Послуги</h2>
      <div class="text" id="servicesText"></div>
    </div>

    <div id="screen-advantages" class="card screen hidden">
      <h2>⭐ Переваги</h2>
      <div class="text" id="advantagesText"></div>
    </div>

    <div id="screen-pricing" class="card screen hidden">
      <h2>💰 Вартість гарантії</h2>
      <div class="text" id="pricingText"></div>
    </div>

    <div id="screen-faq" class="card screen hidden">
      <h2>❓ FAQ</h2>
      <div class="text" id="faqText"></div>
    </div>

    <div id="screen-contacts" class="card screen hidden">
      <h2>📞 Контакти</h2>
      <div class="text" id="contactsText"></div>
    </div>

    <div id="screen-lead" class="card screen hidden">
      <h2>📝 Залишити заявку</h2>
      <div class="muted">Заповніть форму, і менеджер отримає вашу заявку в Telegram та на email, якщо email налаштовано.</div>

      <input id="leadName" placeholder="Ваше імʼя" />
      <input id="leadPhone" placeholder="Телефон" />
      <input id="leadCompany" placeholder="Назва компанії" />

      <select id="leadGuaranteeType">
        <option value="">Оберіть тип гарантії</option>
        <option value="Загальна гарантія">Загальна гарантія</option>
        <option value="Індивідуальна гарантія">Індивідуальна гарантія</option>
        <option value="Тендерна гарантія">Тендерна гарантія</option>
        <option value="Гарантія виконання договору">Гарантія виконання договору</option>
        <option value="Інше">Інше</option>
      </select>

      <input id="leadRoute" placeholder="Маршрут / напрямок" />
      <textarea id="leadCargo" placeholder="Опис вантажу, договору або ситуації"></textarea>
      <textarea id="leadComment" placeholder="Коментар"></textarea>

      <button class="primary" onclick="sendLead()">Відправити заявку</button>

      <div id="leadStatus" class="status"></div>
      <div id="leadError" class="error"></div>
    </div>

    <div id="screen-admin" class="card screen hidden">
      <h2>⚙️ Адмін-панель</h2>
      <div class="muted">Тут можна змінювати інформацію, логотип, фон, email для заявок і дивитися заявки.</div>

      <div class="admin-section">
        <h3>📝 Тексти додатку</h3>

        <label>Назва компанії</label>
        <textarea id="editCompanyName"></textarea>

        <label>Головний опис</label>
        <textarea id="editHeroText"></textarea>

        <label>Про компанію</label>
        <textarea id="editAbout"></textarea>

        <label>Послуги</label>
        <textarea id="editServices"></textarea>

        <label>Переваги</label>
        <textarea id="editAdvantages"></textarea>

        <label>Вартість / тарифи</label>
        <textarea id="editPricing"></textarea>

        <label>FAQ</label>
        <textarea id="editFaq"></textarea>

        <label>Контакти</label>
        <textarea id="editContacts"></textarea>
      </div>

      <div class="admin-section">
        <h3>🎨 Дизайн</h3>

        <label>Логотип</label>
        <input type="file" id="logoFile" accept="image/*" onchange="handleImageUpload('logo')" />
        <img id="logoPreview" class="preview logo-preview" src="/assets/logo.png" />

        <label>Фон головного екрану</label>
        <input type="file" id="bgFile" accept="image/*" onchange="handleImageUpload('background')" />
        <img id="bgPreview" class="preview" src="/assets/truck_bg.jpg" />

        <button class="danger" style="margin-top:10px;" onclick="resetImages()">Скинути логотип і фон на стандартні</button>
      </div>

      <div class="admin-section">
        <h3>📧 Email для заявок</h3>
        <div class="muted" id="smtpInfo"></div>

        <label>Відправляти заявки на email</label>
        <select id="editEmailEnabled">
          <option value="1">Так</option>
          <option value="0">Ні</option>
        </select>

        <label>Email-адреси отримувачів</label>
        <textarea id="editEmailTo" placeholder="info@example.com&#10;manager@example.com"></textarea>

        <button class="secondary" onclick="sendTestEmail()">Надіслати тестовий email</button>
        <div id="emailStatus" class="status"></div>
        <div id="emailError" class="error"></div>
      </div>

      <div class="admin-section">
        <button class="primary" onclick="saveContent()">💾 Зберегти всі зміни</button>
        <div id="adminStatus" class="status"></div>
        <div id="adminError" class="error"></div>
      </div>

      <div class="admin-section">
        <h3>📋 Заявки</h3>
        <button class="secondary" onclick="loadLeads()">Оновити список заявок</button>
        <div id="leadsList" class="muted" style="margin-top:10px;">Натисніть “Оновити список заявок”.</div>
      </div>
    </div>

    <div id="openError" class="card hidden">
      <h2>Помилка відкриття</h2>
      <div class="error">
        Відкрийте додаток саме через кнопку в Telegram-боті.
        Якщо відкрити просто в браузері, Telegram не передасть дані користувача.
      </div>
    </div>
  </div>

<script>
  const tg = window.Telegram?.WebApp;
  let initData = "";
  let content = {};
  let isAdmin = false;
  let smtpConfigured = false;
  let currentLogoImage = "";
  let currentBackgroundImage = "";

  if (tg) {
    tg.ready();
    tg.expand();
    initData = tg.initData || "";
  }

  function setText(id, value) {
    document.getElementById(id).textContent = value || "";
  }

  async function postJSON(url, data) {
    const res = await fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(data)
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(text);
    }

    return await res.json();
  }

  function fillPublicContent() {
    setText("companyName", content.company_name);
    setText("heroText", content.hero_text);
    setText("homeText", content.hero_text);
    setText("aboutText", content.about);
    setText("servicesText", content.services);
    setText("advantagesText", content.advantages);
    setText("pricingText", content.pricing);
    setText("faqText", content.faq);
    setText("contactsText", content.contacts);

    currentLogoImage = content.logo_image || "/assets/logo.png";
    currentBackgroundImage = content.background_image || "/assets/truck_bg.jpg";

    document.getElementById("logoImg").src = currentLogoImage;
    document.getElementById("logoPreview").src = currentLogoImage;
    document.getElementById("bgPreview").src = currentBackgroundImage;

    const hero = document.getElementById("heroCard");
    hero.style.backgroundImage =
      `linear-gradient(180deg, rgba(5,13,25,0.05), rgba(5,13,25,0.50)), url("${currentBackgroundImage}")`;
  }

  function fillAdminForm() {
    document.getElementById("editCompanyName").value = content.company_name || "";
    document.getElementById("editHeroText").value = content.hero_text || "";
    document.getElementById("editAbout").value = content.about || "";
    document.getElementById("editServices").value = content.services || "";
    document.getElementById("editAdvantages").value = content.advantages || "";
    document.getElementById("editPricing").value = content.pricing || "";
    document.getElementById("editFaq").value = content.faq || "";
    document.getElementById("editContacts").value = content.contacts || "";
    document.getElementById("editEmailEnabled").value = String(content.email_enabled || "1");
    document.getElementById("editEmailTo").value = content.email_to || "";
    document.getElementById("smtpInfo").textContent = smtpConfigured
      ? "SMTP на сервері налаштований. Заявки можуть приходити на email."
      : "SMTP на сервері ще не налаштований. Email-адреси можна зберігати, але листи не будуть відправлятися, поки не додані SMTP-змінні в Render.";
  }

  function showTab(name, btn) {
    document.querySelectorAll(".screen").forEach(el => el.classList.add("hidden"));
    document.getElementById("screen-" + name).classList.remove("hidden");

    document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));
    if (btn) btn.classList.add("active");

    if (name === "admin" && isAdmin) {
      loadLeads();
    }
  }

  async function loadApp() {
    try {
      const data = await postJSON("/api/init", {initData});
      content = data.content;
      isAdmin = data.is_admin;
      smtpConfigured = data.smtp_configured;

      fillPublicContent();

      if (isAdmin) {
        document.getElementById("adminTabBtn").classList.remove("hidden");
        document.getElementById("adminBadge").classList.remove("hidden");
        fillAdminForm();
      }

    } catch (e) {
      document.getElementById("openError").classList.remove("hidden");
    }
  }

  async function sendLead() {
    const status = document.getElementById("leadStatus");
    const error = document.getElementById("leadError");
    status.textContent = "";
    error.textContent = "";

    const payload = {
      initData,
      name: document.getElementById("leadName").value.trim(),
      phone: document.getElementById("leadPhone").value.trim(),
      company: document.getElementById("leadCompany").value.trim(),
      guarantee_type: document.getElementById("leadGuaranteeType").value.trim(),
      route: document.getElementById("leadRoute").value.trim(),
      cargo: document.getElementById("leadCargo").value.trim(),
      comment: document.getElementById("leadComment").value.trim()
    };

    if (!payload.name || !payload.phone) {
      error.textContent = "Вкажіть імʼя та телефон.";
      return;
    }

    try {
      await postJSON("/api/lead", payload);

      document.getElementById("leadName").value = "";
      document.getElementById("leadPhone").value = "";
      document.getElementById("leadCompany").value = "";
      document.getElementById("leadGuaranteeType").value = "";
      document.getElementById("leadRoute").value = "";
      document.getElementById("leadCargo").value = "";
      document.getElementById("leadComment").value = "";

      status.textContent = "✅ Заявку відправлено. Менеджер звʼяжеться з вами.";
      tg?.HapticFeedback?.notificationOccurred("success");
    } catch (e) {
      error.textContent = "Не вдалося відправити заявку. Перевірте, що додаток відкрито через Telegram.";
    }
  }

  function resetImages() {
    currentLogoImage = "/assets/logo.png";
    currentBackgroundImage = "/assets/truck_bg.jpg";
    document.getElementById("logoPreview").src = currentLogoImage;
    document.getElementById("bgPreview").src = currentBackgroundImage;
    content.logo_image = currentLogoImage;
    content.background_image = currentBackgroundImage;
    fillPublicContent();
  }

  function readFileAsDataURL(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  async function compressImageFile(file, mode) {
    const dataUrl = await readFileAsDataURL(file);
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const maxWidth = mode === "background" ? 1600 : 800;
        const scale = Math.min(1, maxWidth / img.width);
        const width = Math.round(img.width * scale);
        const height = Math.round(img.height * scale);

        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");

        if (mode === "logo") {
          ctx.fillStyle = "#ffffff";
          ctx.fillRect(0, 0, width, height);
          ctx.drawImage(img, 0, 0, width, height);
          resolve(canvas.toDataURL("image/png"));
        } else {
          ctx.drawImage(img, 0, 0, width, height);
          resolve(canvas.toDataURL("image/jpeg", 0.78));
        }
      };
      img.onerror = () => resolve(dataUrl);
      img.src = dataUrl;
    });
  }

  async function handleImageUpload(mode) {
    const input = mode === "logo"
      ? document.getElementById("logoFile")
      : document.getElementById("bgFile");

    const file = input.files[0];
    if (!file) return;

    const result = await compressImageFile(file, mode);

    if (mode === "logo") {
      currentLogoImage = result;
      content.logo_image = result;
      document.getElementById("logoPreview").src = result;
      document.getElementById("logoImg").src = result;
    } else {
      currentBackgroundImage = result;
      content.background_image = result;
      document.getElementById("bgPreview").src = result;
      fillPublicContent();
    }
  }

  async function saveContent() {
    const status = document.getElementById("adminStatus");
    const error = document.getElementById("adminError");
    status.textContent = "";
    error.textContent = "";

    const payload = {
      initData,
      company_name: document.getElementById("editCompanyName").value.trim(),
      hero_text: document.getElementById("editHeroText").value.trim(),
      about: document.getElementById("editAbout").value.trim(),
      services: document.getElementById("editServices").value.trim(),
      advantages: document.getElementById("editAdvantages").value.trim(),
      pricing: document.getElementById("editPricing").value.trim(),
      faq: document.getElementById("editFaq").value.trim(),
      contacts: document.getElementById("editContacts").value.trim(),
      logo_image: currentLogoImage,
      background_image: currentBackgroundImage,
      email_enabled: document.getElementById("editEmailEnabled").value === "1",
      email_to: document.getElementById("editEmailTo").value.trim()
    };

    try {
      const data = await postJSON("/api/admin/content", payload);
      content = data.content;
      fillPublicContent();
      fillAdminForm();
      status.textContent = "✅ Збережено. Інформація в додатку оновлена.";
      tg?.HapticFeedback?.notificationOccurred("success");
    } catch (e) {
      error.textContent = "Помилка збереження. Можливо, ви не адмін або файл занадто великий.";
    }
  }

  async function loadLeads() {
    if (!isAdmin) return;
    const box = document.getElementById("leadsList");
    box.textContent = "Завантаження...";

    try {
      const data = await postJSON("/api/admin/leads", {initData});
      if (!data.leads.length) {
        box.textContent = "Заявок поки немає.";
        return;
      }

      box.innerHTML = data.leads.map(l => `
        <div class="lead-card">
          <b>Заявка #${l.id}</b>
          <br><span class="muted">${l.created_at || ""}</span>
          <br><br><b>Клієнт:</b> ${escapeText(l.name)} / ${escapeText(l.phone)}
          <br><b>Telegram:</b> ${escapeText(l.tg_name || String(l.user_id))}
          <br><b>Компанія:</b> ${escapeText(l.company || "-")}
          <br><b>Тип гарантії:</b> ${escapeText(l.guarantee_type || "-")}
          <br><b>Маршрут:</b> ${escapeText(l.route || "-")}
          <br><b>Вантаж / договір:</b> ${escapeText(l.cargo || "-")}
          <br><b>Коментар:</b> ${escapeText(l.comment || "-")}
        </div>
      `).join("");
    } catch (e) {
      box.textContent = "Не вдалося завантажити заявки.";
    }
  }

  function escapeText(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  async function sendTestEmail() {
    const status = document.getElementById("emailStatus");
    const error = document.getElementById("emailError");
    status.textContent = "";
    error.textContent = "";

    try {
      await saveContent();
      const data = await postJSON("/api/admin/test-email", {initData});
      status.textContent = data.message || "✅ Тестовий email відправлено.";
    } catch (e) {
      error.textContent = "Не вдалося відправити тест. Перевір SMTP-змінні в Render і email-адреси в адмінці.";
    }
  }

  loadApp();
</script>
</body>
</html>
    """)


@app.post("/api/init")
def api_init(payload: InitPayload):
    user = validate_telegram_init_data(payload.initData)

    return {
        "ok": True,
        "user": user,
        "is_admin": is_admin(user["user_id"]),
        "smtp_configured": smtp_is_configured(),
        "content": get_content(),
    }


@app.post("/api/admin/content")
def api_save_content(payload: ContentSavePayload):
    user = validate_telegram_init_data(payload.initData)

    if not is_admin(user["user_id"]):
        raise HTTPException(status_code=403, detail="Only admin can edit content")

    save_content({
        "company_name": payload.company_name,
        "hero_text": payload.hero_text,
        "about": payload.about,
        "services": payload.services,
        "advantages": payload.advantages,
        "pricing": payload.pricing,
        "faq": payload.faq,
        "contacts": payload.contacts,
        "logo_image": payload.logo_image or "/assets/logo.png",
        "background_image": payload.background_image or "/assets/truck_bg.jpg",
        "email_enabled": "1" if payload.email_enabled else "0",
        "email_to": payload.email_to,
    })

    return {
        "ok": True,
        "content": get_content(),
    }


@app.post("/api/admin/leads")
def api_admin_leads(payload: InitPayload):
    user = validate_telegram_init_data(payload.initData)

    if not is_admin(user["user_id"]):
        raise HTTPException(status_code=403, detail="Only admin can view leads")

    rows = conn.execute(
        """
        SELECT id, user_id, tg_name, name, phone, company, guarantee_type, route, cargo, comment, created_at
        FROM leads
        ORDER BY id DESC
        LIMIT 50
        """
    ).fetchall()

    return {
        "ok": True,
        "leads": [dict(row) for row in rows],
    }


@app.post("/api/admin/test-email")
def api_test_email(payload: TestEmailPayload):
    user = validate_telegram_init_data(payload.initData)

    if not is_admin(user["user_id"]):
        raise HTTPException(status_code=403, detail="Only admin can send test email")

    content = get_content()
    recipients = parse_email_list(content.get("email_to", ""))

    if content.get("email_enabled", "1") != "1":
        raise HTTPException(status_code=400, detail="Email sending is disabled in admin panel")

    try:
        send_email_message(
            recipients,
            "Тестовий лист GARANT SERVICE Mini App",
            (
                "Це тестовий лист з адмін-панелі GARANT SERVICE Mini App.\n\n"
                "Якщо ви отримали цей лист, email-надсилання налаштовано правильно."
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email error: {e}")

    return {"ok": True, "message": "✅ Тестовий email відправлено."}


@app.post("/api/lead")
async def api_create_lead(payload: LeadPayload):
    user = validate_telegram_init_data(payload.initData)

    tg_name = " ".join(
        x for x in [
            user.get("first_name", ""),
            user.get("last_name", "")
        ] if x
    ).strip()

    if user.get("username"):
        tg_name += f" (@{user['username']})"

    cur = conn.execute(
        """
        INSERT INTO leads (
            user_id, tg_name, name, phone, company, guarantee_type, route, cargo, comment, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user["user_id"],
            tg_name,
            payload.name.strip(),
            payload.phone.strip(),
            payload.company.strip(),
            payload.guarantee_type.strip(),
            payload.route.strip(),
            payload.cargo.strip(),
            payload.comment.strip(),
            now_iso(),
        ),
    )
    conn.commit()

    lead_id = cur.lastrowid

    lead_text = (
        "📝 Нова заявка з GARANT SERVICE Mini App\n\n"
        f"ID заявки: {lead_id}\n"
        f"Telegram: {tg_name or user['user_id']}\n\n"
        f"Імʼя: {payload.name}\n"
        f"Телефон: {payload.phone}\n"
        f"Компанія: {payload.company or '-'}\n"
        f"Тип гарантії: {payload.guarantee_type or '-'}\n"
        f"Маршрут: {payload.route or '-'}\n"
        f"Вантаж / договір: {payload.cargo or '-'}\n"
        f"Коментар: {payload.comment or '-'}"
    )

    if bot_app and ADMIN_IDS:
        for admin_id in ADMIN_IDS:
            try:
                await bot_app.bot.send_message(chat_id=admin_id, text=lead_text)
            except Exception as e:
                print(f"Cannot send lead to admin {admin_id}: {e}")

    content = get_content()
    if content.get("email_enabled", "1") == "1":
        recipients = parse_email_list(content.get("email_to", ""))
        if recipients and smtp_is_configured():
            try:
                send_email_message(
                    recipients,
                    f"Нова заявка GARANT SERVICE #{lead_id}",
                    lead_text,
                )
            except Exception as e:
                print(f"Cannot send lead email: {e}")

    return {"ok": True, "lead_id": lead_id}


@app.get("/health")
def health():
    return {"ok": True}
