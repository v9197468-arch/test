Гарант Сервіс Mini App — тестова версія

Файли:
- main.py
- requirements.txt

Render:
Build Command:
pip install -r requirements.txt

Start Command:
uvicorn main:app --host 0.0.0.0 --port $PORT

Environment Variables:
BOT_TOKEN=токен від @BotFather
ADMIN_IDS=твій Telegram ID
WEBAPP_URL=https://твій-render-url.onrender.com

Перевірка:
1. Задеплой на Render.
2. Напиши /start у @gssstest_bot.
3. Натисни "📱 Відкрити додаток".
4. Якщо твій ADMIN_IDS правильний, побачиш кнопку "⚙️ Адмінка".
