# 🤖 Omada Telegram Bot

A Telegram bot that manages TP-Link Omada WiFi access codes and runs customer re-engagement campaigns via Flutterwave.

## ✨ Features

### 🔑 Access Code Management
- **Daily codes** (24 hours)
- **3-Day codes** (72 hours)
- **Weekly codes** (7 days)
- **Monthly codes** (30 days)
- ✅ Codes are **never repeated** - tracked in SQLite database
- ✅ Cooldown periods prevent abuse
- ✅ Full audit trail of all code usage

### 📧 Customer Outreach
- Fetches all customers from **Flutterwave**
- Identifies customers **without active subscriptions**
- Sends re-engagement emails with:
  - Your WhatsApp link
  - Your Telegram bot link
- Progress tracking in real-time

### 🛠️ Admin Panel
- Sync new codes from Omada Controller
- Import existing unused vouchers
- Import codes from CSV file
- View code inventory statistics

---

## 🚀 Quick Setup

### Step 1: Create Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name and username for your bot
4. Copy the **bot token** (you'll need it later)
5. Get your Telegram user ID by messaging **@userinfobot**

### Step 2: Clone and Install

```bash
cd omada-telegram-bot
pip install -r requirements.txt
```

### Step 3: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Telegram
TELEGRAM_BOT_TOKEN=7000000000:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ALLOWED_USER_IDS=123456789  # Your Telegram user ID

# Omada Controller
OMADA_CONTROLLER_URL=https://your-controller:8043
OMADA_USERNAME=admin
OMADA_PASSWORD=your_password
OMADA_SITE_ID=default

# Flutterwave
FLUTTERWAVE_SECRET_KEY=FLWSECK-xxxxxxxxxxxxx-X

# Email (SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password  # Use App Password, NOT regular password
SMTP_FROM_EMAIL=your-email@gmail.com
SMTP_FROM_NAME=Your Business Name

# Links for re-engagement emails
WHATSAPP_LINK=https://wa.me/2348012345678
TELEGRAM_BOT_LINK=https://t.me/your_bot_name
```

### Step 4: Run the Bot

```bash
python bot.py
```

---

## 📱 How to Use

### For Getting Codes
1. Start the bot with `/start`
2. Tap **Daily**, **3-Day**, **Weekly**, or **Monthly** buttons
3. Or type the keywords: `daily`, `3days`, `weekly`, `monthly`

### For Admin (Code Management)
1. Tap **⚙️ Admin Panel**
2. Use **Sync** buttons to create new codes on Omada
3. Use **Import All** to pull existing unused vouchers
4. Or create a `codes_import.csv` file and import it:

```csv
ABC123,daily
DEF456,weekly
GHI789,monthly
```

### For Customer Outreach
1. Tap **📧 Customer Outreach**
2. Tap **Preview** to see inactive customers first
3. Tap **Run Campaign** to send emails

---

## 🏗️ Architecture

```
omada-telegram-bot/
├── bot.py                  # Main Telegram bot with all handlers
├── config.py               # Configuration loader (.env)
├── database.py             # SQLite database management
├── omada_fetcher.py        # Omada Controller API client
├── flutterwave_client.py   # Flutterwave API client
├── email_sender.py         # SMTP email sender
├── requirements.txt        # Python dependencies
├── Procfile                # Heroku/Railway deployment config
├── .env.example            # Environment template
├── .gitignore
└── README.md
```

### Database Schema

**codes** table:
| Column | Type | Description |
|--------|------|-------------|
| code | TEXT | The access code string |
| duration_type | TEXT | daily, 3days, weekly, monthly |
| duration_minutes | INTEGER | Duration in minutes |
| status | TEXT | unused or used |
| used_at | TIMESTAMP | When the code was used |
| used_by | TEXT | User ID who used it |

**usage_log** table - Complete audit trail of every code delivered.

**request_tracker** table - Cooldown tracking per user per code type.

---

## 🔒 Code Safety (No Repeats)

The bot ensures codes are **never repeated** through:

1. **UNIQUE constraint** on `(code, duration_type)` in the database
2. **Atomic transactions** - Code is marked as "used" in the same transaction as retrieval
3. **Status tracking** - Only `unused` codes are ever selected
4. **Audit trail** - Every code delivery is logged with timestamp and user

---

## 🌐 Deployment

### Railway/Render/Heroku

1. Push code to GitHub
2. Connect your repo to Railway/Render/Heroku
3. Set all environment variables in the platform's dashboard
4. Deploy!

### VPS (Systemd Service)

Create `/etc/systemd/system/omada-bot.service`:

```ini
[Unit]
Description=Omada Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/omada-telegram-bot
ExecStart=/usr/bin/python3 /home/ubuntu/omada-telegram-bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable omada-bot
sudo systemctl start omada-bot
```

---

## 🔧 Omada Controller Setup

### Find Your Site ID

1. Login to your Omada Controller web interface
2. Go to **Settings > Site**
3. The Site ID is usually `default` or found in the URL

### API Access

Make sure your Omada Controller:
- Has API access enabled
- Has the hotspot/captive portal feature configured
- Has voucher codes enabled under **Settings > Authentication > Hotspot**

### Creating Vouchers via Omada UI (Alternative)

If the API doesn't work, you can:
1. Create vouchers manually in the Omada Controller UI
2. Export them to a CSV file
3. Import them using the **Import from File** option in the Admin Panel

---

## 📧 Gmail SMTP Setup

1. Go to Google Account settings
2. Navigate to **Security > 2-Step Verification**
3. Enable 2FA if not already enabled
4. Go to **App Passwords**
5. Create a new app password for "Mail"
6. Use that 16-character password in `.env` as `SMTP_PASSWORD`

---

## ⚠️ Important Notes

- **Cooldown periods**: Daily (20h), 3-Day (68h), Weekly (6 days), Monthly (28 days)
- **Authorization**: Only users in `ALLOWED_USER_IDS` can use the bot
- **Email limits**: Gmail allows ~500 emails/day. For higher volumes, use SendGrid or Mailgun
- **Code storage**: Database file (`codes_database.db`) must be persisted on your server
- **Omada API**: Self-signed certificates are handled automatically (`verify=False`)

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Bot doesn't respond | Check `TELEGRAM_BOT_TOKEN` in `.env` |
| "Not authorized" | Add your user ID to `ALLOWED_USER_IDS` |
| Omada sync fails | Verify controller URL, credentials, and site ID |
| Emails not sending | Check SMTP settings; use App Password for Gmail |
| No codes available | Use Admin Panel to sync/import codes first |
| Flutterwave error | Verify your secret key has read permissions |

---

## 📄 License

MIT License - Use freely for your business!
