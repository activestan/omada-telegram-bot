"""
Email Sender - Uses your exact email templates.

Two email types:
1. No-purchase reminder (registered but never bought)
2. Renewal reminder (bought before, subscription expired)
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
    SMTP_FROM_EMAIL, SMTP_FROM_NAME,
    TELEGRAM_BOT_LINK
)

logger = logging.getLogger(__name__)

# Your subscription durations
SUBSCRIPTION_DURATIONS = {
    400: 1,
    1000: 3,
    2000: 7,
    7000: 31
}


def build_no_purchase_email(name: str, days_since_registration) -> tuple:
    """Build email for customer who registered but never bought."""
    subject = f"Hi {name}, your Stannet internet code is waiting"

    if days_since_registration is None:
        reg_text = "You created your Stannet account, but you have not bought an internet code yet."
    else:
        reg_text = f"You created your Stannet account {days_since_registration} days ago, but you have not bought an internet code yet."

    text_body = f"""Hi {name},

{reg_text}

You can get connected in just a few seconds by buying your internet code through our Telegram bot:

👉 {TELEGRAM_BOT_LINK}

If you need help choosing a package or completing your purchase, we are ready to assist you.

We look forward to having you online.

Best regards,
The Stannet Team"""

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <p>Hi {name},</p>
        <p>{reg_text}</p>
        <p>You can get connected in just a few seconds by buying your internet code through our Telegram bot:</p>
        <p style="text-align: center; margin: 30px 0;">
            <a href="{TELEGRAM_BOT_LINK}" style="display: inline-block; padding: 14px 35px; background-color: #0088cc; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
                🤖 Get Your Code Now
            </a>
        </p>
        <p>If you need help choosing a package or completing your purchase, we are ready to assist you.</p>
        <p>We look forward to having you online.</p>
        <p>Best regards,<br><strong>The Stannet Team</strong></p>
    </div>
    """

    return subject, html_body.strip(), text_body.strip()


def build_renewal_email(name: str, days_since: int, amount: int, threshold: int) -> tuple:
    """Build email for customer who bought before but hasn't renewed."""
    duration = SUBSCRIPTION_DURATIONS.get(threshold, 0)
    days_to_show = max(0, days_since - duration)

    subject = f"We miss you, {name}! Ready to reconnect with Stannet?"

    text_body = f"""Hi {name},

We noticed it's been {days_to_show} days since your last subscription of ₦{amount} for your Stannet internet service.

We truly miss having you connected with us and can't wait to get you back online!

Your fast and reliable internet is just a quick top-up away. If you need any help or want to renew your subscription, simply reach out to our Telegram bot:

👉 {TELEGRAM_BOT_LINK}

We're here whenever you're ready.

Best regards,
The Stannet Team"""

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <p>Hi {name},</p>
        <p>We noticed it's been <strong>{days_to_show} days</strong> since your last subscription of <strong>₦{amount}</strong> for your Stannet internet service.</p>
        <p>We truly miss having you connected with us and can't wait to get you back online!</p>
        <p>Your fast and reliable internet is just a quick top-up away. If you need any help or want to renew your subscription, simply reach out to our Telegram bot:</p>
        <p style="text-align: center; margin: 30px 0;">
            <a href="{TELEGRAM_BOT_LINK}" style="display: inline-block; padding: 14px 35px; background-color: #0088cc; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
                🤖 Renew Your Subscription
            </a>
        </p>
        <p>We're here whenever you're ready.</p>
        <p>Best regards,<br><strong>The Stannet Team</strong></p>
    </div>
    """

    return subject, html_body.strip(), text_body.strip()


def send_email(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """Send an email via SMTP with timeout."""
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        logger.error("SMTP_USERNAME or SMTP_PASSWORD not set!")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"✅ Email sent to {to_email}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP Auth failed for {to_email}: {e}")
        logger.error("Check: SMTP_USERNAME and SMTP_PASSWORD (use App Password, not regular password)")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"❌ SMTP error for {to_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send to {to_email}: {e}")
        return False


async def send_reengagement_campaigns(customers: list, progress_callback=None) -> dict:
    """
    Send appropriate emails based on customer type.
    Tests SMTP first and stops early if auth fails.
    """
    results = {"sent": 0, "failed": 0, "total": len(customers), "auth_error": False}

    # Test SMTP connection first
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        logger.info("✅ SMTP connection test passed")
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP Authentication failed! Check SMTP_USERNAME and SMTP_PASSWORD.")
        results["auth_error"] = True
        results["failed"] = len(customers)
        return results
    except Exception as e:
        logger.error(f"SMTP connection test failed: {e}")
        results["auth_error"] = True
        results["failed"] = len(customers)
        return results

    for i, customer in enumerate(customers):
        email = customer.get("email", "")
        name = customer.get("name", "Valued Customer")
        cust_type = customer.get("type", "renewal")

        if not email:
            results["failed"] += 1
            continue

        if cust_type == "no_purchase":
            subject, html, text = build_no_purchase_email(
                name, customer.get("days_since")
            )
        else:
            subject, html, text = build_renewal_email(
                name,
                customer.get("days_since", 0),
                customer.get("amount", 0),
                customer.get("threshold", 400)
            )

        success = send_email(email, subject, html, text)

        if success:
            results["sent"] += 1
        else:
            results["failed"] += 1

        if progress_callback:
            await progress_callback(i + 1, results["total"], email, success)

    return results
