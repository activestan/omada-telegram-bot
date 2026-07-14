"""
Email Sender - Supports Resend API (works on Render free tier) and SMTP fallback.

Resend: Free 3000 emails/month, uses HTTPS (port 443) — works everywhere.
SMTP: Traditional, but blocked on some free hosting platforms.
"""
import smtplib
import logging
import httpx
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
    SMTP_FROM_EMAIL, SMTP_FROM_NAME,
    EMAIL_PROVIDER, RESEND_API_KEY,
    TELEGRAM_BOT_LINK
)

logger = logging.getLogger(__name__)

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

We noticed it's been {days_to_show} days since your last subscription of {amount} for your Stannet internet service.

We truly miss having you connected with us and can't wait to get you back online!

Your fast and reliable internet is just a quick top-up away. If you need any help or want to renew your subscription, simply reach out to our Telegram bot:

👉 {TELEGRAM_BOT_LINK}

We're here whenever you're ready.

Best regards,
The Stannet Team"""

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <p>Hi {name},</p>
        <p>We noticed it's been <strong>{days_to_show} days</strong> since your last subscription of <strong>{amount}</strong> for your Stannet internet service.</p>
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


def send_email_resend(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """Send email via Resend API (works on Render free tier)."""
    if not RESEND_API_KEY:
        logger.error("RESEND_API_KEY not set!")
        return False

    try:
        from_email = SMTP_FROM_EMAIL or "onboarding@resend.dev"
        from_name = SMTP_FROM_NAME or "Stannet"

        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "from": f"{from_name} <{from_email}>",
                "to": [to_email],
                "subject": subject,
                "html": html_body,
                "text": text_body
            },
            timeout=15.0
        )

        if resp.status_code in [200, 201]:
            logger.info(f"✅ Email sent to {to_email} via Resend")
            return True
        else:
            logger.error(f"❌ Resend API error for {to_email}: {resp.status_code} - {resp.text}")
            return False

    except Exception as e:
        logger.error(f"❌ Resend failed for {to_email}: {e}")
        return False


def send_email_smtp(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """Send email via SMTP (may not work on some free hosting)."""
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

        logger.info(f"✅ Email sent to {to_email} via SMTP")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP Auth failed: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ SMTP failed for {to_email}: {e}")
        return False


def send_email(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """Send email using the configured provider."""
    if EMAIL_PROVIDER == "resend":
        return send_email_resend(to_email, subject, html_body, text_body)
    else:
        return send_email_smtp(to_email, subject, html_body, text_body)


async def test_email_connection() -> tuple:
    """Test email connection. Returns (success: bool, message: str)."""
    if EMAIL_PROVIDER == "resend":
        if not RESEND_API_KEY:
            return False, "RESEND_API_KEY not set. Add it in Render Environment."
        try:
            resp = httpx.get(
                "https://api.resend.com/domains",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                timeout=10.0
            )
            if resp.status_code == 200:
                return True, "Resend API connection OK"
            else:
                return False, f"Resend API error: {resp.status_code}"
        except Exception as e:
            return False, f"Resend connection failed: {e}"
    else:
        if not SMTP_USERNAME or not SMTP_PASSWORD:
            return False, "SMTP_USERNAME or SMTP_PASSWORD not set"
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            return True, "SMTP connection OK"
        except smtplib.SMTPAuthenticationError:
            return False, "SMTP auth failed. Check SMTP_PASSWORD (use App Password)"
        except Exception as e:
            return False, f"SMTP failed: {e}"


async def send_reengagement_campaigns(customers: list, progress_callback=None) -> dict:
    """Send appropriate emails based on customer type."""
    results = {"sent": 0, "failed": 0, "total": len(customers), "auth_error": False}

    # Test connection first
    ok, msg = await test_email_connection()
    if not ok:
        logger.error(f"Email connection test failed: {msg}")
        results["auth_error"] = True
        results["error_message"] = msg
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
