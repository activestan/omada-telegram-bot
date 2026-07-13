"""
Omada Cloud Integration Module
Authenticates via Playwright (headless browser) to handle TP-Link's OAuth flow,
then uses httpx with the session cookies + csrf-token header for API access.

Key findings:
- Omada Cloud uses OAuth via id.tplinkcloud.com
- API calls require a `csrf-token` header (lowercase, hyphenated)
- Controller API is accessed via the connector at:
  https://{region}-api-omada-controller-connector.tplinkcloud.com/omadac/{deviceId}/{omadacId}/api/v2/...
- Hotspot/voucher endpoints may require specific site context
"""
import asyncio
import logging
import httpx
import warnings
from typing import Optional, Tuple
from config import (
    OMADA_CONTROLLER_URL, OMADA_USERNAME, OMADA_PASSWORD, OMADA_SITE_ID
)
from database import add_codes_bulk

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)

DURATION_MAP = {
    "daily": 1440,
    "3days": 4320,
    "weekly": 10080,
    "monthly": 43200
}


class OmadaCloudSession:
    """
    Manages an authenticated session to the Omada Cloud.
    Uses Playwright for the OAuth login flow, then httpx for API calls.
    """

    def __init__(self):
        self.email = OMADA_USERNAME
        self.password = OMADA_PASSWORD
        self.csrf_token = None
        self.session_cookie = None
        self.cookies = {}
        self.http_client = None
        self.device_id = None
        self.omadac_id = None
        self.site_id = None
        self.connector_base = None
        self.manager_base = None
        self.access_base = None

    async def login(self) -> bool:
        """Login to Omada Cloud using Playwright browser automation."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
            return False

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    ignore_https_errors=True,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()

                # Capture API responses to get controller info
                api_data = {}

                async def on_response(response):
                    url = response.url
                    if response.status == 200 and 'api-omada' in url:
                        try:
                            body = await response.json()
                            if body.get('errorCode') == 0:
                                if 'login-with-uid-code' in url:
                                    self.csrf_token = body['result']['csrfToken']
                                elif 'organizations' in url and 'cloud-device-info' not in url:
                                    result = body.get('result', {})
                                    if isinstance(result, dict) and result.get('data'):
                                        for org in result['data']:
                                            self.device_id = org.get('deviceId')
                                            break
                                elif 'cloud-device-info' in url:
                                    pass  # Device info captured
                        except:
                            pass

                page.on('response', on_response)

                # Navigate to Omada Cloud
                portal_url = OMADA_CONTROLLER_URL.rstrip('/')
                if not portal_url:
                    portal_url = "https://euw1-omada-cloud.tplinkcloud.com"

                logger.info(f"Navigating to {portal_url}...")
                await page.goto(portal_url, wait_until="networkidle", timeout=30000)

                # Fill login form
                await page.wait_for_selector('#form_item_email', timeout=15000)
                await page.fill('#form_item_email', self.email)
                await page.fill('#form_item_password', self.password)

                # Click Sign In
                sign_in = page.locator('a.s-button-primary')
                await sign_in.click()

                # Wait for redirect back to portal
                await page.wait_for_url("**/*omada*cloud*/**", timeout=45000)
                await page.wait_for_timeout(10000)

                # Get cookies
                cookies = await context.cookies()
                for c in cookies:
                    self.cookies[c['name']] = c['value']
                    if c['name'] == 'SESSION':
                        self.session_cookie = c['value']
                    if c['name'] == 'csrfToken' and not self.csrf_token:
                        self.csrf_token = c['value']

                # Extract region info from URL
                current_url = page.url
                if 'euw1' in current_url:
                    region = 'euw1'
                elif 'aps1' in current_url:
                    region = 'aps1'
                elif 'use1' in current_url:
                    region = 'use1'
                else:
                    region = 'euw1'

                # Set API base URLs
                self.manager_base = f"https://{region}-api-omada-cloud-manager.tplinkcloud.com"
                self.access_base = f"https://{region}-api-omada-cloud-access.tplinkcloud.com"
                self.connector_base = f"https://{region}-api-omada-controller-connector.tplinkcloud.com"

                # Try to get omadacId by clicking on the controller
                if self.device_id:
                    try:
                        ctrl_el = await page.query_selector('text=Omada Controller')
                        if ctrl_el:
                            await ctrl_el.dblclick()
                            await page.wait_for_timeout(5000)

                            # Get the controller page's API calls to extract omadacId
                            for pg in context.pages:
                                if 'omadacId' in pg.url:
                                    import re
                                    match = re.search(r'omadacId=([a-f0-9]+)', pg.url)
                                    if match:
                                        self.omadac_id = match.group(1)
                                    break
                    except Exception as e:
                        logger.warning(f"Could not get omadacId: {e}")

                await browser.close()

            # Set up httpx client with cookies
            self.http_client = httpx.Client(verify=False, timeout=30.0)
            for name, value in self.cookies.items():
                self.http_client.cookies.set(name, value, domain='.tplinkcloud.com', path='/')

            # If we don't have omadacId yet, try to get it via API
            if not self.omadac_id and self.device_id:
                await self._get_omadac_id()

            logger.info(f"✅ Omada Cloud login successful!")
            logger.info(f"   CSRF Token: {self.csrf_token}")
            logger.info(f"   Device ID: {self.device_id}")
            logger.info(f"   Omadac ID: {self.omadac_id}")
            return True

        except Exception as e:
            logger.error(f"Omada Cloud login failed: {e}")
            return False

    async def _get_omadac_id(self):
        """Get the omadacId for the controller via API."""
        if not self.device_id or not self.http_client:
            return

        try:
            r = self.http_client.get(
                f"{self.access_base}/api/v2/cloudaccess/organizations/{self.device_id}",
                headers=self._headers()
            )
            body = r.json()
            if body.get('errorCode') == 0:
                # The omadacId might be in the response
                pass

            # Try via v2 API
            r2 = self.http_client.post(
                f"{self.access_base}/api/v2/cloudaccess/organizations/{self.device_id}",
                json={},
                headers=self._headers()
            )
            body2 = r2.json()
            if body2.get('errorCode') == 0:
                self.omadac_id = body2.get('result', {}).get('omadacId')
        except Exception as e:
            logger.warning(f"Could not get omadacId via API: {e}")

    def _headers(self) -> dict:
        """Get the standard API headers including csrf-token."""
        return {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'csrf-token': self.csrf_token or '',
            'Referer': f'{OMADA_CONTROLLER_URL.rstrip("/")}/' if OMADA_CONTROLLER_URL else 'https://euw1-omada-cloud.tplinkcloud.com/',
            'Origin': OMADA_CONTROLLER_URL.rstrip('/') if OMADA_CONTROLLER_URL else 'https://euw1-omada-cloud.tplinkcloud.com',
        }

    def _connector_url(self, path: str) -> str:
        """Build a connector API URL."""
        if not self.device_id or not self.omadac_id:
            raise ValueError("device_id and omadac_id required for connector API")
        return f"{self.connector_base}/omadac/{self.device_id}/{self.omadac_id}{path}"

    async def get_sites(self) -> list:
        """Get list of sites from the controller."""
        if not self.http_client:
            return []

        try:
            r = self.http_client.get(
                self._connector_url("/api/v2/sites/basic?currentPageSize=50&currentPage=1"),
                headers=self._headers()
            )
            body = r.json()
            if body.get('errorCode') == 0:
                sites = body.get('result', {}).get('data', [])
                if sites and not self.site_id:
                    self.site_id = sites[0].get('id')
                return sites
        except Exception as e:
            logger.error(f"Error getting sites: {e}")
        return []

    async def get_vouchers(self) -> list:
        """Get hotspot voucher codes from the controller."""
        if not self.http_client:
            return []

        try:
            # Try multiple voucher endpoint patterns
            endpoints = [
                self._connector_url(f"/api/v2/sites/{self.site_id}/hotspot/vouchers"),
                self._connector_url(f"/api/v2/hotspot/vouchers?currentPageSize=100&currentPage=1"),
                self._connector_url(f"/{self.site_id}/api/v2/cmd/hotspot"),
            ]

            for url in endpoints:
                try:
                    if 'cmd/hotspot' in url:
                        r = self.http_client.post(url,
                            json={"cmd": "listVouchers", "params": {"currentPage": 1, "currentPageSize": 100}},
                            headers=self._headers())
                    else:
                        r = self.http_client.get(url, headers=self._headers())

                    body = r.json()
                    if body.get('errorCode') == 0:
                        result = body.get('result', {})
                        vouchers = result.get('data', []) if isinstance(result, dict) else result
                        return vouchers
                except:
                    continue

        except Exception as e:
            logger.error(f"Error getting vouchers: {e}")
        return []

    async def create_vouchers(self, duration_type: str, count: int = 10) -> list:
        """Create new voucher codes on the controller."""
        if not self.http_client:
            return []

        duration_minutes = DURATION_MAP.get(duration_type)
        if not duration_minutes:
            return []

        try:
            # Create vouchers via the controller API
            create_url = self._connector_url(f"/{self.site_id}/api/v2/cmd/hotspot")
            payload = {
                "cmd": "createVouchers",
                "params": {
                    "count": count,
                    "minutes": duration_minutes,
                    "name": f"bot_{duration_type}",
                    "uploadKbps": -1,
                    "downloadKbps": -1,
                    "byteQuota": -1,
                    "type": 1
                }
            }

            r = self.http_client.post(create_url, json=payload, headers=self._headers())
            body = r.json()

            if body.get('errorCode') == 0:
                # Fetch the newly created vouchers
                await asyncio.sleep(2)  # Brief delay for creation
                return await self.get_vouchers()

        except Exception as e:
            logger.error(f"Error creating vouchers: {e}")
        return []

    def close(self):
        """Close the HTTP client."""
        if self.http_client:
            self.http_client.close()


async def sync_codes_from_omada(duration_type: str = None, count: int = 20) -> Tuple[bool, str]:
    """
    Sync codes from Omada Cloud Controller into the local database.
    """
    session = OmadaCloudSession()

    try:
        logged_in = await session.login()
        if not logged_in:
            return False, "Failed to login to Omada Cloud. Check credentials in .env"

        # Get sites first
        sites = await session.get_sites()
        if not sites:
            return False, "No sites found on the controller"

        if duration_type:
            # Create new vouchers
            vouchers = await session.create_vouchers(duration_type, count)
        else:
            # Get existing vouchers
            vouchers = await session.get_vouchers()

        if not vouchers:
            return False, "No vouchers retrieved from Omada"

        # Map durations to types
        reverse_duration = {v: k for k, v in DURATION_MAP.items()}

        codes_data = []
        for v in vouchers:
            code = v.get('code', v.get('voucherCode', ''))
            duration = v.get('duration', v.get('minutes', 0))
            dur_type = reverse_duration.get(duration, 'unknown')

            if dur_type == 'unknown':
                for key, minutes in DURATION_MAP.items():
                    if abs(duration - minutes) < 60:
                        dur_type = key
                        break

            if code:
                codes_data.append((code, dur_type, duration, v.get('id', '')))

        if codes_data:
            await add_codes_bulk(codes_data)

        session.close()
        return True, f"Successfully synced {len(codes_data)} codes"

    except Exception as e:
        logger.error(f"Error syncing codes: {e}")
        return False, f"Error: {str(e)}"
    finally:
        session.close()


async def import_codes_from_file(filepath: str) -> Tuple[bool, str]:
    """Import codes from a CSV/text file."""
    try:
        codes_data = []
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                sep = ',' if ',' in line else '|'
                parts = line.split(sep)
                if len(parts) >= 2:
                    code = parts[0].strip()
                    dur_type = parts[1].strip().lower()
                    minutes = DURATION_MAP.get(dur_type, 0)
                    if code and dur_type in DURATION_MAP:
                        codes_data.append((code, dur_type, minutes, ""))

        if codes_data:
            await add_codes_bulk(codes_data)
            return True, f"Imported {len(codes_data)} codes from file"
        return False, "No valid codes found in file"
    except Exception as e:
        return False, f"Error importing file: {str(e)}"
