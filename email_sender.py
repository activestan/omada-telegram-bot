"""
Email Sender Module
Sends re-engagement emails to inactive customers via SMTP.
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
    SMTP_FROM_EMAIL, SMTP_FROM_NAME,
    WHATSAPP_LINK, TELEGRAM_BOT_LINK
)

logger = logging.getLogger(__name__)


def build_reengagement_email(customer_name: str) -> tuple:
    """
    Build the re-engagement email HTML and plain text content.
    
    Returns: (subject, html_body, text_body)
    """
    name = customer_name if customer_name else "Valued Customer"

    subject = f"We Miss You, {name}! 🎉 We're Still Here For You"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                       color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
            .button {{ display: inline-block; padding: 12px 30px; margin: 10px;
                      background-color: #25D366; color: white; text-decoration: none;
                      border-radius: 5px; font-weight: bold; }}
            .button-telegram {{ background-color: #0088cc; }}
            .footer {{ text-align: center; padding: 20px; color: #888; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>👋 Hello {name}!</h1>
                <p>We've Missed You!</p>
            </div>
            <div class="content">
                <p>Hi {name},</p>
                
                <p>We noticed it's been a while since you last used our services, and we wanted 
                to let you know that <strong>we're still active and ready to serve you!</strong></p>
                
                <p>Our team has been working hard to improve your experience, and we'd love 
                for you to come back and see what's new.</p>
                
                <h3>📱 Stay Connected With Us:</h3>
                
                <p>
                    <a href="{WHATSAPP_LINK}" class="button">
                        💬 Chat on WhatsApp
                    </a>
                </p>
                <p>
                    <a href="{TELEGRAM_BOT_LINK}" class="button button-telegram">
                        🤖 Use Our Telegram Bot
                    </a>
                </p>
                
                <p>Whether you need support, want to place an order, or just want to say hello, 
                we're just a message away!</p>
                
                <p>Looking forward to hearing from you! 🙌</p>
                
                <p>Best regards,<br>
                <strong>{SMTP_FROM_NAME}</strong></p>
            </div>
            <div class="footer">
                <p>This email was sent on {datetime.now().strftime("%B %d, %Y")}.</p>
                <p>If you no longer wish to receive emails, please reply with "unsubscribe".</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
Hello {name}!

We noticed it's been a while since you last used our services, and we wanted 
to let you know that we're still active and ready to serve you!

Our team has been working hard to improve your experience, and we'd love 
for you to come back and see what's new.

Stay Connected With Us:
- WhatsApp: {WHATSAPP_LINK}
- Telegram Bot: {TELEGRAM_BOT_LINK}

Whether you need support, want to place an order, or just want to say hello, 
we're just a message away!

Looking forward to hearing from you!

Best regards,
{SMTP_FROM_NAME}
    """

    return subject, html_body.strip(), text_body.strip()


def send_email(to_email: str, to_name: str, subject: str, html_body: str, text_body: str) -> bool:
    """
    Send an email via SMTP.
    
    Returns True if sent successfully, False otherwise.
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        # Attach plain text and HTML versions
        part1 = MIMEText(text_body, "plain")
        part2 = MIMEText(html_body, "html")
        msg.attach(part1)
        msg.attach(part2)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"Email sent to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


async def send_reengagement_campaigns(customers: list, progress_callback=None) -> dict:
    """
    Send re-engagement emails to a list of inactive customers.
    
    Args:
        customers: List of customer dicts with 'email' and 'name' keys
        progress_callback: Optional async function(sent, total, email, success) for progress updates
    
    Returns:
        Dict with 'sent', 'failed', 'total' counts
    """
    results = {"sent": 0, "failed": 0, "total": len(customers)}

    for i, customer in enumerate(customers):
        email = customer.get("email", "")
        name = customer.get("name", "")

        if not email:
            results["failed"] += 1
            continue

        subject, html_body, text_body = build_reengagement_email(name)
        success = send_email(email, name, subject, html_body, text_body)

        if success:
            results["sent"] += 1
        else:
            results["failed"] += 1

        if progress_callback:
            await progress_callback(i + 1, results["total"], email, success)

    return results
