"""
Flutterwave Integration Module
Fetches customer data and identifies customers without active subscriptions.
"""
import httpx
import logging
from config import FLUTTERWAVE_SECRET_KEY

logger = logging.getLogger(__name__)

FLUTTERWAVE_BASE_URL = "https://api.flutterwave.com/v3"


class FlutterwaveClient:
    """Client for Flutterwave API."""

    def __init__(self):
        self.secret_key = FLUTTERWAVE_SECRET_KEY
        self.headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json"
        }

    async def get_all_customers(self) -> list:
        """Fetch all customers from Flutterwave."""
        all_customers = []
        page = 1

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                try:
                    resp = await client.get(
                        f"{FLUTTERWAVE_BASE_URL}/customers",
                        headers=self.headers,
                        params={"page": page, "limit": 100}
                    )

                    if resp.status_code != 200:
                        logger.error(f"Flutterwave API error: {resp.status_code} - {resp.text}")
                        break

                    data = resp.json()

                    if data.get("status") != "success":
                        logger.error(f"Flutterwave error: {data}")
                        break

                    customers = data.get("data", [])
                    if not customers:
                        break

                    all_customers.extend(customers)

                    # Check if there are more pages
                    meta = data.get("meta", {})
                    total_pages = meta.get("page_info", {}).get("total_pages", 1)
                    if page >= total_pages:
                        break

                    page += 1

                except Exception as e:
                    logger.error(f"Error fetching customers: {e}")
                    break

        logger.info(f"Fetched {len(all_customers)} total customers from Flutterwave")
        return all_customers

    async def get_customer_subscriptions(self, customer_id: str) -> list:
        """Get subscription/payment history for a specific customer."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # Fetch transactions for this customer
                resp = await client.get(
                    f"{FLUTTERWAVE_BASE_URL}/transactions",
                    headers=self.headers,
                    params={
                        "customer_id": customer_id,
                        "status": "successful"
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("data", [])

            except Exception as e:
                logger.error(f"Error fetching subscriptions for {customer_id}: {e}")

        return []

    async def get_subscriptions(self) -> list:
        """Get all subscriptions/payment plans."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(
                    f"{FLUTTERWAVE_BASE_URL}/payment-plans",
                    headers=self.headers
                )

                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("data", [])

            except Exception as e:
                logger.error(f"Error fetching subscriptions: {e}")

        return []

    async def get_inactive_customers(self) -> list:
        """
        Get customers who are NOT on an active subscription.
        
        Logic:
        1. Fetch all customers
        2. Fetch all active subscriptions/transfers
        3. Cross-reference to find customers without active subs
        
        Returns list of customer dicts with email info.
        """
        customers = await self.get_all_customers()
        if not customers:
            return []

        # Get all transactions to identify active subscribers
        active_customer_ids = set()

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                # Fetch recent successful transactions (last 30 days worth)
                resp = await client.get(
                    f"{FLUTTERWAVE_BASE_URL}/transactions",
                    headers=self.headers,
                    params={
                        "status": "successful",
                        "from": _get_date_30_days_ago(),
                        "to": _get_today(),
                        "limit": 500
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    transactions = data.get("data", [])

                    for txn in transactions:
                        customer = txn.get("customer", {})
                        cust_id = customer.get("id")
                        if cust_id:
                            active_customer_ids.add(cust_id)

            except Exception as e:
                logger.error(f"Error fetching transactions: {e}")

        # Filter customers not in active list
        inactive = []
        for customer in customers:
            cust_id = customer.get("id")
            email = customer.get("email", "")

            if cust_id not in active_customer_ids and email:
                inactive.append({
                    "id": cust_id,
                    "name": customer.get("name", ""),
                    "email": email,
                    "phone": customer.get("phone", ""),
                    "created_at": customer.get("created_at", "")
                })

        logger.info(f"Found {len(inactive)} inactive customers out of {len(customers)} total")
        return inactive


def _get_date_30_days_ago() -> str:
    """Get date string for 30 days ago in ISO format."""
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")


def _get_today() -> str:
    """Get today's date in ISO format."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


async def fetch_inactive_customers() -> tuple:
    """
    Main function to fetch inactive customers.
    Returns: (success: bool, customers: list, message: str)
    """
    try:
        client = FlutterwaveClient()
        inactive = await client.get_inactive_customers()

        if inactive:
            return True, inactive, f"Found {len(inactive)} inactive customers"
        else:
            return False, [], "No inactive customers found or error fetching data"

    except Exception as e:
        logger.error(f"Error in fetch_inactive_customers: {e}")
        return False, [], f"Error: {str(e)}"
