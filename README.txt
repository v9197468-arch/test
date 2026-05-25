GARANT SERVICE Mini App v2

Що додано:
- сучасний преміальний дизайн;
- фон з вантажівкою;
- логотип;
- пункти меню: Головна, Про нас, Послуги, Переваги, Вартість, FAQ, Заявка, Контакти;
- адмінка;
- редагування всіх текстів;
- зміна логотипу через адмінку;
- зміна фону через адмінку;
- перегляд заявок через адмінку;
- керування email-адресами для отримання заявок;
- тестовий email з адмінки;
- заявки приходять адміну в Telegram;
- заявки можуть дублюватися на email.

Render:
Build Command:
pip install -r requirements.txt

Start Command:
uvicorn main:app --host 0.0.0.0 --port $PORT

Обов'язкові Environment Variables:
BOT_TOKEN=токен від @BotFather
ADMIN_IDS=твій Telegram ID
WEBAPP_URL=https://твій-render-url.onrender.com

Для email потрібно додати SMTP-змінні:
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=твоя_пошта@gmail.com
SMTP_PASSWORD=пароль_додатку_Gmail
MAIL_FROM=твоя_пошта@gmail.com
SMTP_TLS=1

Email-адреси отримувачів керуються вже в Mini App:
Адмінка -> Email для заявок -> Email-адреси отримувачів

Важливо:
На Gmail потрібно використовувати не звичайний пароль, а "пароль додатку".
