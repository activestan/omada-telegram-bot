"""
Omada Controller Integration Module
Fetches/generates voucher codes from TP-Link Omada Controller API
and stores them in the database.

Omada API Reference:
- Login: POST /{controllerId}/api/v2/sites/{siteId}/login
- Create Vouchers: POST /{controllerId}/api/v2/sites/{siteId}/cmd/hotspot
- List Vouchers: POST /{controllerId}/api/v2/sites/{siteId}/cmd/hotspot (action=list)
"""
import httpx
import logging
import json
from typing import Optional
from config import (
    OMADA_CONTROLLER_URL, OMADA_USERNAME, OMADA_PASSWORD, OMADA_SITE_ID
)
from database import add_codes_bulk

logger = logging.getLogger(__name__)

# Duration mapping: type -> minutes
DURATION_MAP = {
    "daily": 1440,       # 24 hours
    "3days": 4320,       # 72 hours
    "weekly": 10080,     # 7 days
    "monthly": 43200     # 30 days
}


class OmadaController:
    """Client for TP-Link Omada Controller API."""

    def __init__(self):
        self.base_url = OMADA_CONTROLLER_URL
        self.username = OMADA_USERNAME
        self.password = OMADA_PASSWORD
        self.site_id = OMADA_SITE_ID
        self.token = None
        self.csrf_token = None
        self.controller_id = None
        self.client = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(
                verify=False,  # Omada often uses self-signed certs
                timeout=30.0
            )
        return self.client

    async def login(self) -> bool:
        """Authenticate with the Omada Controller."""
        client = await self._get_client()

        try:
            # First, try to get the controller ID
            resp = await client.get(f"{self.base_url}/api/v2/sites")
            if resp.status_code == 200:
                data = resp.json()
                if "result" in data and data["result"]:
                    self.controller_id = None  # No controller ID prefix for newer versions

            # Try login with v2 API
            login_url = f"{self.base_url}/api/v2/sites/{self.site_id}/login"
            login_data = {
                "userName": self.username,
                "password": self.password
            }

            resp = await client.post(login_url, json=login_data)

            if resp.status_code == 200:
                data = resp.json()
                if data.get("errorCode") == 0:
                    # Extract token from response
                    result = data.get("result", {})
                    self.token = result.get("token")
                    self.csrf_token = resp.headers.get("Csrf-Token", "")

                    # Set cookies/headers for future requests
                    if self.token:
                        self.client.cookies.set("TOKEN", self.token)

                    logger.info("Successfully logged into Omada Controller")
                    return True
                else:
                    logger.error(f"Omada login failed: {data}")
            else:
                logger.error(f"Omada login HTTP error: {resp.status_code}")

            # Try alternate login endpoint (older firmware)
            alt_login_url = f"{self.base_url}/login"
            resp = await client.post(alt_login_url, data={
                "userName": self.username,
                "password": self.password
            })

            if resp.status_code == 200:
                self.csrf_token = resp.headers.get("Csrf-Token", "")
                logger.info("Logged in via alternate endpoint")
                return True

        except Exception as e:
            logger.error(f"Omada login error: {e}")

        return False

    async def _api_request(self, method: str, endpoint: str, data: dict = None) -> Optional[dict]:
        """Make an authenticated API request to Omada."""
        client = await self._get_client()

        url = f"{self.base_url}/api/v2/sites/{self.site_id}/{endpoint}"
        headers = {}

        if self.csrf_token:
            headers["Csrf-Token"] = self.csrf_token

        if method == "POST":
            resp = await client.post(url, json=data, headers=headers)
        else:
            resp = await client.get(url, headers=headers)

        if resp.status_code == 200:
            return resp.json()

        logger.error(f"Omada API error: {resp.status_code} - {resp.text}")
        return None

    async def create_vouchers(self, duration_type: str, count: int = 10) -> list:
        """
        Create new voucher codes on the Omada Controller.
        
        Args:
            duration_type: 'daily', '3days', 'weekly', or 'monthly'
            count: Number of vouchers to create
        
        Returns:
            List of voucher code strings
        """
        duration_minutes = DURATION_MAP.get(duration_type)
        if not duration_minutes:
            logger.error(f"Invalid duration type: {duration_type}")
            return []

        # Create vouchers via Omada API
        data = {
            "cmd": "createVouchers",
            "action": "createVouchers",
            "params": {
                "count": count,
                "minutes": duration_minutes,
                "name": f"bot_{duration_type}",
                "uploadKbps": -1,    # Unlimited
                "downloadKbps": -1,  # Unlimited
                "byteQuota": -1,     # Unlimited
                "type": 1            # Type 1 = time-based
            }
        }

        result = await self._api_request("POST", "cmd/hotspot", data)

        if not result or result.get("errorCode") != 0:
            logger.error(f"Failed to create vouchers: {result}")
            return []

        # After creation, fetch the vouchers to get the actual codes
        vouchers = await self._fetch_recent_vouchers(count)
        return vouchers

    async def _fetch_recent_vouchers(self, count: int = 10) -> list:
        """Fetch the most recently created vouchers."""
        data = {
            "cmd": "listVouchers",
            "action": "listVouchers",
            "params": {
                "currentPage": 1,
                "currentPageSize": count,
                "orderBy": "createTime",
                "sortOrder": "DESC"
            }
        }

        result = await self._api_request("POST", "cmd/hotspot", data)

        if not result or result.get("errorCode") != 0:
            logger.error(f"Failed to list vouchers: {result}")
            return []

        vouchers = []
        voucher_list = result.get("result", {}).get("data", [])

        for v in voucher_list:
            code = v.get("code", "")
            if code:
                vouchers.append({
                    "code": code,
                    "id": v.get("id", ""),
                    "duration": v.get("minutes", 0)
                })

        return vouchers

    async def list_all_unused_vouchers(self) -> list:
        """List all unused vouchers from the Omada controller."""
        data = {
            "cmd": "listVouchers",
            "action": "listVouchers",
            "params": {
                "currentPage": 1,
                "currentPageSize": 200,
                "status": 0  # 0 = unused
            }
        }

        result = await self._api_request("POST", "cmd/hotspot", data)

        if not result or result.get("errorCode") != 0:
            logger.error(f"Failed to list unused vouchers: {result}")
            return []

        vouchers = []
        voucher_list = result.get("result", {}).get("data", [])

        for v in voucher_list:
            code = v.get("code", "")
            if code:
                vouchers.append({
                    "code": code,
                    "id": v.get("id", ""),
                    "duration": v.get("minutes", 0),
                    "status": v.get("status", -1)
                })

        return vouchers

    async def close(self):
        """Close the HTTP client."""
        if self.client and not self.client.is_closed:
            await self.client.aclose()


async def sync_codes_from_omada(duration_type: str = None, count: int = 20):
    """
    Sync codes from Omada Controller into the local database.
    Can be called to create new codes or import existing unused ones.
    
    Args:
        duration_type: If specified, create new codes of this type.
                       If None, import all existing unused vouchers.
        count: Number of new codes to create (if duration_type specified)
    """
    controller = OmadaController()

    try:
        logged_in = await controller.login()
        if not logged_in:
            logger.error("Could not login to Omada Controller")
            return False, "Failed to connect to Omada Controller"

        if duration_type:
            # Create new vouchers of specified type
            vouchers = await controller.create_vouchers(duration_type, count)
        else:
            # Import all existing unused vouchers
            vouchers = await controller.list_all_unused_vouchers()

        if not vouchers:
            return False, "No vouchers retrieved from Omada"

        # Map durations back to types
        reverse_duration = {v: k for k, v in DURATION_MAP.items()}

        # Prepare bulk insert data
        codes_data = []
        for v in vouchers:
            dur_type = reverse_duration.get(v["duration"], "unknown")
            if dur_type == "unknown":
                # Try to find closest match
                for key, minutes in DURATION_MAP.items():
                    if abs(v["duration"] - minutes) < 60:
                        dur_type = key
                        break

            codes_data.append((
                v["code"],
                dur_type,
                v["duration"],
                v.get("id", "")
            ))

        await add_codes_bulk(codes_data)
        await controller.close()

        return True, f"Successfully synced {len(codes_data)} codes"

    except Exception as e:
        logger.error(f"Error syncing codes from Omada: {e}")
        return False, f"Error: {str(e)}"
    finally:
        await controller.close()


async def import_codes_from_file(filepath: str) -> tuple:
    """
    Import codes from a CSV or text file as an alternative to Omada API.
    
    File format (CSV):
        code,duration_type
        
    File format (TXT - one per line):
        CODE123|daily
        CODE456|weekly
    
    Returns: (success: bool, message: str)
    """
    try:
        codes_data = []

        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # Try CSV format
                if ',' in line:
                    parts = line.split(',')
                elif '|' in line:
                    parts = line.split('|')
                else:
                    continue

                if len(parts) >= 2:
                    code = parts[0].strip()
                    dur_type = parts[1].strip().lower()
                    minutes = DURATION_MAP.get(dur_type, 0)

                    if code and dur_type in DURATION_MAP:
                        codes_data.append((code, dur_type, minutes, ""))

        if codes_data:
            await add_codes_bulk(codes_data)
            return True, f"Imported {len(codes_data)} codes from file"
        else:
            return False, "No valid codes found in file"

    except Exception as e:
        return False, f"Error importing file: {str(e)}"
