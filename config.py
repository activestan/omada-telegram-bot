"""
Configuration module - loads all settings from .env file
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = [
    int(uid.strip()) for uid in os.getenv("ALLOWED_USER_IDS", "").split(",") if uid.strip()
]

# Omada Controller
OMADA_CONTROLLER_URL = os.getenv("OMADA_CONTROLLER_URL", "").rstrip("/")
OMADA_USERNAME = os.getenv("OMADA_USERNAME")
OMADA_PASSWORD = os.getenv("OMADA_PASSWORD")
OMADA_SITE_ID = os.getenv("OMADA_SITE_ID")

# Flutterwave
FLUTTERWAVE_SECRET_KEY = os.getenv("FLUTTERWAVE_SECRET_KEY")

# SMTP Email
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Your Business")

# Re-engagement Links
WHATSAPP_LINK = os.getenv("WHATSAPP_LINK", "")
TELEGRAM_BOT_LINK = os.getenv("TELEGRAM_BOT_LINK", "")

# Database
DATABASE_PATH = os.getenv("DATABASE_PATH", "codes_database.db")
