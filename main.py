import os
import json
import hmac
import time
import hashlib
import sqlite3
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
DB_PATH = os.getenv("DB_PATH", "garant_service.db")


def parse_admin_ids() -> set[int]:
    result = set()
    for item in ADMIN_IDS_RAW.replace(" ", "").split(","):
        if item.isdigit():
            result.add(int(item))
    return result


ADMIN_IDS = parse_admin_ids()

app = FastAPI(title="Garant Service Mini App")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row


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
            route TEXT DEFAULT '',
            cargo TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )

    defaults = {
        "company_name": 'ПОВНЕ ТОВАРИСТВО “ГАРАНТ СЕРВІС”\nТОВ “ДЕЛЮКС ФІНАНС” І КОМПАНІЯ',
        "hero_text": "Оформлення гарантій та консультації для перевезення вантажів. Залиште заявку — менеджер звʼяжеться з вами.",
        "services": "• Гарантійне забезпечення перевезення вантажів\n• Консультація щодо документів\n• Супровід клієнта\n• Допомога з оформленням заявки",
        "tariffs": "Тарифи уточнюються індивідуально після розгляду заявки.\n\nДля регулярних клієнтів можливі окремі умови.",
        "faq": "Що потрібно для заявки?\nПотрібні контактні дані, інформація про маршрут і вантаж.\n\nЯк швидко зі мною звʼяжуться?\nМенеджер звʼяжеться після отримання заявки.\n\nЧи можна отримати консультацію?\nТак, залиште заявку в додатку.",
        "contacts": "Телефон: +380 XX XXX XX XX\nEmail: info@example.com\nГрафік роботи: Пн–Пт, 09:00–18:00",
    }

    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO content (key, value) VALUES (?, ?)",
            (key, value),
        )

    conn.commit()


db_init()

bot_app: Optional[Application] = None


class InitPayload(BaseModel):
    initData: str


class ContentSavePayload(BaseModel):
    initData: str
    company_name: str = Field(min_length=1, max_length=5000)
    hero_text: str = Field(min_length=1, max_length=5000)
    services: str = Field(min_length=1, max_length=10000)
    tariffs: str = Field(min_length=1, max_length=10000)
    faq: str = Field(min_length=1, max_length=15000)
    contacts: str = Field(min_length=1, max_length=10000)


class LeadPayload(BaseModel):
    initData: str
    name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=5, max_length=50)
    company: str = Field(default="", max_length=150)
    route: str = Field(default="", max_length=300)
    cargo: str = Field(default="", max_length=500)
    comment: str = Field(default="", max_length=1000)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_content() -> dict:
    rows = conn.execute("SELECT key, value FROM content").fetchall()
    return {row["key"]: row["value"] for row in rows}


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
        "Відкрийте міні-додаток “Гарант Сервіс”, щоб переглянути інформацію або залишити заявку.",
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
  <title>Гарант Сервіс</title>

  <style>
    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: Arial, sans-serif;
      background: #0f172a;
      color: #ffffff;
      padding: 14px;
    }

    .wrap {
      max-width: 760px;
      margin: 0 auto;
    }

    .card {
      background: #172033;
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 20px;
      padding: 16px;
      margin-bottom: 14px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.25);
    }

    .hero {
      background: linear-gradient(135deg, #172033, #1f3b57);
    }

    h1 {
      font-size: 23px;
      line-height: 1.2;
      margin: 0 0 10px;
      white-space: pre-line;
    }

    h2 {
      font-size: 19px;
      margin: 0 0 12px;
    }

    .text {
      color: #d5e3f0;
      line-height: 1.45;
      white-space: pre-line;
      font-size: 15px;
    }

    .muted {
      color: #99a9bd;
      font-size: 14px;
      line-height: 1.4;
    }

    .tabs {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 9px;
      margin-bottom: 14px;
    }

    .tab-btn,
    button {
      width: 100%;
      border: 0;
      border-radius: 15px;
      padding: 13px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      background: #25334a;
      color: #ffffff;
    }

    .tab-btn.active {
      background: #38bdf8;
      color: #07111f;
    }

    .primary {
      background: #22c55e;
      color: #04130a;
    }

    input,
    textarea {
      width: 100%;
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 14px;
      background: #0b1220;
      color: white;
      padding: 13px;
      margin: 8px 0;
      font-size: 15px;
      outline: none;
    }

    textarea {
      min-height: 115px;
      resize: vertical;
      line-height: 1.4;
    }

    label {
      display: block;
      margin-top: 10px;
      color: #cbd5e1;
      font-weight: 700;
      font-size: 14px;
    }

    .hidden { display: none; }

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

    .admin-badge {
      display: inline-block;
      margin-top: 10px;
      background: rgba(34,197,94,0.16);
      color: #86efac;
      border: 1px solid rgba(134,239,172,0.25);
      padding: 7px 10px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
    }
  </style>
</head>

<body>
  <div class="wrap">
    <div class="card hero">
      <h1 id="companyName">Гарант Сервіс</h1>
      <div class="text" id="heroText">Завантаження...</div>
      <div id="adminBadge" class="admin-badge hidden">⚙️ Ви адмін</div>
    </div>

    <div class="tabs" id="tabs">
      <button class="tab-btn active" onclick="showTab('services', this)">📄 Послуги</button>
      <button class="tab-btn" onclick="showTab('tariffs', this)">💰 Тарифи</button>
      <button class="tab-btn" onclick="showTab('faq', this)">❓ FAQ</button>
      <button class="tab-btn" onclick="showTab('lead', this)">📝 Заявка</button>
      <button class="tab-btn" onclick="showTab('contacts', this)">📞 Контакти</button>
      <button id="adminTabBtn" class="tab-btn hidden" onclick="showTab('admin', this)">⚙️ Адмінка</button>
    </div>

    <div id="screen-services" class="card screen">
      <h2>📄 Послуги</h2>
      <div class="text" id="servicesText"></div>
    </div>

    <div id="screen-tariffs" class="card screen hidden">
      <h2>💰 Тарифи</h2>
      <div class="text" id="tariffsText"></div>
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
      <div class="muted">Заповніть форму, і менеджер отримає вашу заявку.</div>

      <input id="leadName" placeholder="Ваше імʼя" />
      <input id="leadPhone" placeholder="Телефон" />
      <input id="leadCompany" placeholder="Назва компанії, якщо є" />
      <input id="leadRoute" placeholder="Маршрут / напрямок" />
      <textarea id="leadCargo" placeholder="Опис вантажу"></textarea>
      <textarea id="leadComment" placeholder="Коментар"></textarea>

      <button class="primary" onclick="sendLead()">Відправити заявку</button>

      <div id="leadStatus" class="status"></div>
      <div id="leadError" class="error"></div>
    </div>

    <div id="screen-admin" class="card screen hidden">
      <h2>⚙️ Адмін-панель</h2>
      <div class="muted">Цей розділ бачить тільки адмін. Тут можна змінювати інформацію без коду.</div>

      <label>Назва компанії</label>
      <textarea id="editCompanyName"></textarea>

      <label>Головний опис</label>
      <textarea id="editHeroText"></textarea>

      <label>Послуги</label>
      <textarea id="editServices"></textarea>

      <label>Тарифи</label>
      <textarea id="editTariffs"></textarea>

      <label>FAQ</label>
      <textarea id="editFaq"></textarea>

      <label>Контакти</label>
      <textarea id="editContacts"></textarea>

      <button class="primary" onclick="saveContent()">Зберегти зміни</button>

      <div id="adminStatus" class="status"></div>
      <div id="adminError" class="error"></div>
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

  if (tg) {
    tg.ready();
    tg.expand();
    initData = tg.initData || "";
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
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

  function setText(id, value) {
    document.getElementById(id).innerHTML = escapeHtml(value);
  }

  function fillPublicContent() {
    setText("companyName", content.company_name);
    setText("heroText", content.hero_text);
    setText("servicesText", content.services);
    setText("tariffsText", content.tariffs);
    setText("faqText", content.faq);
    setText("contactsText", content.contacts);
  }

  function fillAdminForm() {
    document.getElementById("editCompanyName").value = content.company_name || "";
    document.getElementById("editHeroText").value = content.hero_text || "";
    document.getElementById("editServices").value = content.services || "";
    document.getElementById("editTariffs").value = content.tariffs || "";
    document.getElementById("editFaq").value = content.faq || "";
    document.getElementById("editContacts").value = content.contacts || "";
  }

  function showTab(name, btn) {
    document.querySelectorAll(".screen").forEach(el => el.classList.add("hidden"));
    document.getElementById("screen-" + name).classList.remove("hidden");

    document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));
    if (btn) btn.classList.add("active");
  }

  async function loadApp() {
    try {
      const data = await postJSON("/api/init", {initData});
      content = data.content;
      isAdmin = data.is_admin;

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
    status.innerText = "";
    error.innerText = "";

    const payload = {
      initData,
      name: document.getElementById("leadName").value.trim(),
      phone: document.getElementById("leadPhone").value.trim(),
      company: document.getElementById("leadCompany").value.trim(),
      route: document.getElementById("leadRoute").value.trim(),
      cargo: document.getElementById("leadCargo").value.trim(),
      comment: document.getElementById("leadComment").value.trim()
    };

    if (!payload.name || !payload.phone) {
      error.innerText = "Вкажіть імʼя та телефон.";
      return;
    }

    try {
      await postJSON("/api/lead", payload);

      document.getElementById("leadName").value = "";
      document.getElementById("leadPhone").value = "";
      document.getElementById("leadCompany").value = "";
      document.getElementById("leadRoute").value = "";
      document.getElementById("leadCargo").value = "";
      document.getElementById("leadComment").value = "";

      status.innerText = "✅ Заявку відправлено. Менеджер звʼяжеться з вами.";
      tg?.HapticFeedback?.notificationOccurred("success");
    } catch (e) {
      error.innerText = "Не вдалося відправити заявку. Перевірте, що додаток відкрито через Telegram.";
    }
  }

  async function saveContent() {
    const status = document.getElementById("adminStatus");
    const error = document.getElementById("adminError");
    status.innerText = "";
    error.innerText = "";

    const payload = {
      initData,
      company_name: document.getElementById("editCompanyName").value.trim(),
      hero_text: document.getElementById("editHeroText").value.trim(),
      services: document.getElementById("editServices").value.trim(),
      tariffs: document.getElementById("editTariffs").value.trim(),
      faq: document.getElementById("editFaq").value.trim(),
      contacts: document.getElementById("editContacts").value.trim()
    };

    try {
      const data = await postJSON("/api/admin/content", payload);
      content = data.content;
      fillPublicContent();
      fillAdminForm();
      status.innerText = "✅ Збережено. Інформація в додатку оновлена.";
      tg?.HapticFeedback?.notificationOccurred("success");
    } catch (e) {
      error.innerText = "Помилка збереження. Можливо, ви не адмін або сесія Telegram застаріла.";
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
        "services": payload.services,
        "tariffs": payload.tariffs,
        "faq": payload.faq,
        "contacts": payload.contacts,
    })

    return {
        "ok": True,
        "content": get_content(),
    }


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
            user_id, tg_name, name, phone, company, route, cargo, comment, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user["user_id"],
            tg_name,
            payload.name.strip(),
            payload.phone.strip(),
            payload.company.strip(),
            payload.route.strip(),
            payload.cargo.strip(),
            payload.comment.strip(),
            now_iso(),
        ),
    )
    conn.commit()

    lead_id = cur.lastrowid

    text = (
        "📝 Нова заявка з Mini App\n\n"
        f"ID заявки: {lead_id}\n"
        f"Telegram: {tg_name or user['user_id']}\n\n"
        f"Імʼя: {payload.name}\n"
        f"Телефон: {payload.phone}\n"
        f"Компанія: {payload.company or '-'}\n"
        f"Маршрут: {payload.route or '-'}\n"
        f"Вантаж: {payload.cargo or '-'}\n"
        f"Коментар: {payload.comment or '-'}"
    )

    if bot_app and ADMIN_IDS:
        for admin_id in ADMIN_IDS:
            try:
                await bot_app.bot.send_message(chat_id=admin_id, text=text)
            except Exception as e:
                print(f"Cannot send lead to admin {admin_id}: {e}")

    return {"ok": True, "lead_id": lead_id}


@app.get("/health")
def health():
    return {"ok": True}
