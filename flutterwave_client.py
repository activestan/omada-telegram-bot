"""
Flutterwave Integration - Based on your existing reminder logic.

Subscription tiers:
  ₦400   → 1 day  → remind after 2 days
  ₦1000  → 3 days → remind after 4 days
  ₦2000  → 7 days → remind after 8 days
  ₦7000  → 31 days → remind after 33 days

Also reminds customers who registered but never bought (after 1 day).
"""
import httpx
import logging
from datetime import datetime, timedelta, timezone
from config import FLUTTERWAVE_SECRET_KEY

logger = logging.getLogger(__name__)

FLUTTERWAVE_BASE_URL = "https://api.flutterwave.com/v3"

# How many days after registration before reminding customers who never bought
NO_PURCHASE_REMINDER_DAYS = 1

# Fetch transactions from this many days back
TRANSACTION_LOOKBACK_DAYS = 100

# Rules: amount_threshold → days_to_wait
REMINDER_RULES = {
    400: 2,
    1000: 4,
    2000: 8,
    7000: 33
}

# How many days each subscription lasts
SUBSCRIPTION_DURATIONS = {
    400: 1,
    1000: 3,
    2000: 7,
    7000: 31
}


def parse_flutterwave_date(date_string):
    """Convert Flutterwave date string to datetime."""
    if not date_string:
        return None
    try:
        return datetime.fromisoformat(date_string.replace("Z", "+00:00"))
    except Exception:
        return None


def normalize_email(email):
    """Clean and normalize email."""
    if not email:
        return None
    return email.strip().lower()


def should_send_reminder(last_amount, last_date):
    """
    Check if we should send a reminder based on previous payment amount.

    0 - 999       → use 400 package rule
    1000 - 1999   → use 1000 package rule
    2000 - 6999   → use 2000 package rule
    7000+         → use 7000 package rule
    """
    parsed_date = parse_flutterwave_date(last_date)
    if not parsed_date:
        return False, 0, None

    days_since = (datetime.now(timezone.utc) - parsed_date).days

    if last_amount < 1000:
        return days_since >= REMINDER_RULES[400], days_since, 400
    if last_amount < 2000:
        return days_since >= REMINDER_RULES[1000], days_since, 1000
    if last_amount < 7000:
        return days_since >= REMINDER_RULES[2000], days_since, 2000
    return days_since >= REMINDER_RULES[7000], days_since, 7000


def should_send_no_purchase_reminder(customer_created_at):
    """Check if a registered customer who never bought should receive reminder."""
    parsed_date = parse_flutterwave_date(customer_created_at)
    if not parsed_date:
        return True, None
    days_since_registration = (datetime.now(timezone.utc) - parsed_date).days
    return days_since_registration >= NO_PURCHASE_REMINDER_DAYS, days_since_registration


async def get_flw_customers():
    """Fetch registered customers from Flutterwave."""
    if not FLUTTERWAVE_SECRET_KEY:
        logger.error("FLUTTERWAVE_SECRET_KEY not set")
        return []

    headers = {
        "Authorization": f"Bearer {FLUTTERWAVE_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    all_customers = []
    page = 1
    per_page = 100

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params = {"page": page, "per_page": per_page}
            try:
                resp = await client.get(
                    f"{FLUTTERWAVE_BASE_URL}/customers",
                    headers=headers, params=params
                )
            except Exception as e:
                logger.error(f"Error connecting to Flutterwave customers API: {e}")
                break

            if resp.status_code != 200:
                logger.error(f"Error fetching customers: {resp.text}")
                break

            result = resp.json()
            customers = result.get("data", [])
            if not customers:
                break

            for customer in customers:
                email = normalize_email(customer.get("email"))
                if not email:
                    continue

                name = (
                    customer.get("name")
                    or customer.get("full_name")
                    or customer.get("customer_name")
                    or "Valued Customer"
                )
                created_at = (
                    customer.get("created_at")
                    or customer.get("date_created")
                    or customer.get("createdAt")
                )

                all_customers.append({
                    "email": email,
                    "name": name,
                    "created_at": created_at
                })

            logger.info(f"Fetched Flutterwave customers page {page}")
            if len(customers) < per_page:
                break
            page += 1

    return all_customers


async def get_flw_transactions():
    """Fetch successful transactions from Flutterwave."""
    if not FLUTTERWAVE_SECRET_KEY:
        logger.error("FLUTTERWAVE_SECRET_KEY not set")
        return []

    headers = {
        "Authorization": f"Bearer {FLUTTERWAVE_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    all_transactions = []
    page = 1
    per_page = 100

    from_date = (datetime.now() - timedelta(days=TRANSACTION_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    to_date = datetime.now().strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params = {
                "status": "successful",
                "from": from_date,
                "to": to_date,
                "page": page,
                "per_page": per_page
            }
            try:
                resp = await client.get(
                    f"{FLUTTERWAVE_BASE_URL}/transactions",
                    headers=headers, params=params
                )
            except Exception as e:
                logger.error(f"Error connecting to Flutterwave transactions API: {e}")
                break

            if resp.status_code != 200:
                logger.error(f"Error fetching transactions: {resp.text}")
                break

            result = resp.json()
            transactions = result.get("data", [])
            if not transactions:
                break

            all_transactions.extend(transactions)
            logger.info(f"Fetched Flutterwave transactions page {page}")
            if len(transactions) < per_page:
                break
            page += 1

    return all_transactions


def group_last_transactions(transactions):
    """Group transactions by customer email and get the most recent one."""
    customers = {}
    for tx in transactions:
        customer_data = tx.get("customer", {})
        email = normalize_email(customer_data.get("email"))
        if not email:
            continue

        amount = float(tx.get("amount", 0))
        created_at = tx.get("created_at")
        if not created_at:
            continue

        if email not in customers or created_at > customers[email]["created_at"]:
            customers[email] = {
                "email": email,
                "name": customer_data.get("name", "Valued Customer"),
                "amount": amount,
                "created_at": created_at
            }

    return customers


async def fetch_inactive_customers() -> tuple:
    """
    Main function — uses your exact reminder logic.

    Returns: (success, result_dict, message)

    result_dict contains:
        - no_purchase: list of customers who registered but never bought
        - renewal: list of customers who bought before but need renewal
        - active: list of customers still within their subscription
        - total_customers: total registered
        - total_transactions: total transactions found
        - total_paying: total unique paying customers
    """
    try:
        # 1. Get all registered customers
        registered_customers = await get_flw_customers()
        logger.info(f"Found {len(registered_customers)} registered customers")

        # 2. Get all transactions
        transactions = await get_flw_transactions()
        logger.info(f"Found {len(transactions)} transactions")

        # 3. Group paying customers
        paying_customers = group_last_transactions(transactions)
        logger.info(f"Found {len(paying_customers)} unique paying customers")

        # 4. Find customers who need reminders
        no_purchase = []
        renewal = []
        active = []

        # Customers who never bought
        for customer in registered_customers:
            email = customer["email"]
            if email not in paying_customers:
                should_send, days = should_send_no_purchase_reminder(customer.get("created_at"))
                if should_send:
                    no_purchase.append({
                        "email": email,
                        "name": customer["name"],
                        "type": "no_purchase",
                        "days_since": days
                    })

        # Customers who bought but need renewal
        for email, customer in paying_customers.items():
            should_send, days, threshold = should_send_reminder(
                customer["amount"], customer["created_at"]
            )
            if should_send and threshold:
                duration = SUBSCRIPTION_DURATIONS.get(threshold, 0)
                renewal.append({
                    "email": email,
                    "name": customer["name"],
                    "type": "renewal",
                    "amount": int(customer["amount"]),
                    "days_since": days,
                    "threshold": threshold,
                    "duration": duration
                })
            else:
                active.append({
                    "email": email,
                    "name": customer["name"],
                    "amount": int(customer["amount"]),
                    "days_since": days
                })

        all_to_email = no_purchase + renewal

        result = {
            "inactive": all_to_email,
            "no_purchase": no_purchase,
            "renewal": renewal,
            "active": active,
            "no_email": [],
            "total": len(registered_customers),
            "total_transactions": len(transactions),
            "total_paying": len(paying_customers),
        }

        if all_to_email:
            return True, result, f"Found {len(all_to_email)} customers to email"
        else:
            return False, result, f"No customers need reminders right now"

    except Exception as e:
        logger.error(f"Error in fetch_inactive_customers: {e}")
        return False, {
            "inactive": [], "no_purchase": [], "renewal": [],
            "active": [], "no_email": [], "total": 0,
            "total_transactions": 0, "total_paying": 0
        }, f"Error: {str(e)}"
