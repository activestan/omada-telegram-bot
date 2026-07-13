"""
Omada Code Extraction Script
Run this ONCE (or occasionally) to pull voucher codes from your Omada Cloud Controller.
Saves codes to the SQLite database for the Telegram bot to serve.

Usage:
    python extract_codes.py

This script:
1. Opens Omada Cloud in a headless browser
2. Logs in with your credentials
3. Navigates to the controller's hotspot voucher page
4. Extracts voucher codes matching: whatsapp_1day, whatsapp_3days, whatsapp_7days, whatsapp_31days
5. Saves them to the database
"""
import asyncio
import json
import sys
import logging
import httpx
import warnings
import re
from datetime import datetime

warnings.filterwarnings('ignore')
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================
# CONFIGURATION - Edit these or use .env
# ============================================
from dotenv import load_dotenv
import os
load_dotenv()

OMADA_EMAIL = os.getenv("OMADA_USERNAME", "")
OMADA_PASSWORD = os.getenv("OMADA_PASSWORD", "")
OMADA_URL = os.getenv("OMADA_CONTROLLER_URL", "https://euw1-omada-cloud.tplinkcloud.com")
DATABASE_PATH = os.getenv("DATABASE_PATH", "codes_database.db")

# The voucher name prefixes we want to extract
VOUCHER_NAMES = {
    "whatsapp_1day": ("daily", 1440),
    "whatsapp_3days": ("3days", 4320),
    "whatsapp_7days": ("weekly", 10080),
    "whatsapp_31days": ("monthly", 43200),
}


async def init_db():
    """Initialize the database."""
    import aiosqlite
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                duration_type TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                status TEXT DEFAULT 'unused',
                omada_voucher_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_at TIMESTAMP,
                used_by TEXT,
                UNIQUE(code, duration_type)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                duration_type TEXT NOT NULL,
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                requested_by TEXT,
                status TEXT DEFAULT 'delivered'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS request_tracker (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                duration_type TEXT NOT NULL,
                last_requested TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, duration_type)
            )
        """)
        await db.commit()


async def save_codes_to_db(codes_data: list):
    """Save extracted codes to the database."""
    import aiosqlite
    async with aiosqlite.connect(DATABASE_PATH) as db:
        inserted = 0
        for code, dur_type, dur_minutes, voucher_id in codes_data:
            try:
                await db.execute(
                    """INSERT OR IGNORE INTO codes (code, duration_type, duration_minutes, omada_voucher_id)
                       VALUES (?, ?, ?, ?)""",
                    (code, dur_type, dur_minutes, voucher_id)
                )
                if db.total_changes > 0:
                    inserted += 1
            except Exception as e:
                logger.warning(f"Could not insert code {code}: {e}")
        await db.commit()
    return inserted


async def extract_codes():
    """
    Main extraction function using Playwright to login and httpx to fetch vouchers.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed!")
        logger.error("Run: pip install playwright && python -m playwright install chromium && python -m playwright install-deps chromium")
        sys.exit(1)

    if not OMADA_EMAIL or not OMADA_PASSWORD:
        logger.error("OMADA_USERNAME and OMADA_PASSWORD must be set in .env")
        sys.exit(1)

    print("=" * 60)
    print("🔑 Omada Code Extraction Tool")
    print("=" * 60)
    print(f"   Email: {OMADA_EMAIL}")
    print(f"   Portal: {OMADA_URL}")
    print(f"   Target vouchers: {', '.join(VOUCHER_NAMES.keys())}")
    print("=" * 60)
    print()

    # Initialize database
    await init_db()
    print("✅ Database initialized")

    # Step 1: Login via Playwright
    print("\n🌐 Opening Omada Cloud...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # Capture critical data during login
        csrf_token = None
        device_id = None
        omadac_id = None
        site_id = None
        connector_base = None

        captured_apis = {}

        async def on_response(response):
            nonlocal csrf_token, device_id, omadac_id
            url = response.url
            if response.status == 200 and 'api-omada' in url:
                try:
                    body = await response.json()
                    if body.get('errorCode') == 0:
                        if 'login-with-uid-code' in url:
                            csrf_token = body['result']['csrfToken']
                        elif 'organizations' in url and 'cloud-device-info' not in url:
                            result = body.get('result', {})
                            if isinstance(result, dict) and result.get('data'):
                                for org in result['data']:
                                    device_id = org.get('deviceId')
                                    break

                        # Store all successful API responses
                        path = url.split('tplinkcloud.com')[-1] if 'tplinkcloud' in url else url
                        captured_apis[path] = body
                except:
                    pass

        page.on('response', on_response)

        # Navigate to Omada Cloud
        await page.goto(OMADA_URL, wait_until="networkidle", timeout=30000)

        # Login
        print("📧 Logging in...")
        await page.wait_for_selector('#form_item_email', timeout=15000)
        await page.fill('#form_item_email', OMADA_EMAIL)
        await page.fill('#form_item_password', OMADA_PASSWORD)

        sign_in = page.locator('a.s-button-primary')
        await sign_in.click()

        # Wait for redirect to portal
        await page.wait_for_url("**/*omada*cloud*/**", timeout=45000)
        await page.wait_for_timeout(10000)

        # Close any dialog
        ok_btn = await page.query_selector('text=OK')
        if ok_btn:
            await ok_btn.click()
            await page.wait_for_timeout(500)

        if not csrf_token:
            cookies = await context.cookies()
            for c in cookies:
                if c['name'] == 'csrfToken':
                    csrf_token = c['value']

        print(f"✅ Logged in! csrfToken: {csrf_token[:20]}...")

        # Get cookies
        cookies = await context.cookies()
        cookie_dict = {c['name']: c['value'] for c in cookies}

        # Determine region from URL
        current_url = page.url
        if 'euw1' in current_url:
            region = 'euw1'
        elif 'aps1' in current_url:
            region = 'aps1'
        elif 'use1' in current_url:
            region = 'use1'
        else:
            region = 'euw1'

        connector_base = f"https://{region}-api-omada-controller-connector.tplinkcloud.com"
        access_base = f"https://{region}-api-omada-cloud-access.tplinkcloud.com"

        # Launch controller to get omadacId
        if device_id:
            print(f"🎮 Controller found: {device_id[:20]}...")
            
            # Set up listener for controller page
            ctrl_page_ref = [None]
            ctrl_apis = []

            async def on_ctrl_response(response):
                url = response.url
                if response.status == 200:
                    try:
                        body = await response.json()
                        if body.get('errorCode') == 0:
                            ctrl_apis.append({'url': url, 'body': body})
                    except:
                        pass

            async def on_new_page(new_page):
                ctrl_page_ref[0] = new_page
                new_page.on('response', on_ctrl_response)

            context.on('page', on_new_page)

            # Double-click to launch controller
            ctrl_el = await page.query_selector('text=Omada Controller')
            if ctrl_el:
                await ctrl_el.dblclick()
                await page.wait_for_timeout(15000)

            # Extract omadacId from controller page URL
            for pg in context.pages:
                if 'omadacId' in pg.url:
                    match = re.search(r'omadacId=([a-f0-9]+)', pg.url)
                    if match:
                        omadac_id = match.group(1)
                    break

            if omadac_id:
                print(f"✅ OmadacId: {omadac_id[:20]}...")
            else:
                # Try to get it from API
                try:
                    client = httpx.Client(verify=False, timeout=15.0)
                    for name, value in cookie_dict.items():
                        client.cookies.set(name, value, domain='.tplinkcloud.com', path='/')

                    r = client.post(
                        f"{access_base}/api/v2/cloudaccess/organizations/{device_id}",
                        json={},
                        headers={
                            'Accept': 'application/json',
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest',
                            'csrf-token': csrf_token,
                            'Referer': f'{OMADA_URL}/',
                            'Origin': OMADA_URL,
                        }
                    )
                    body = r.json()
                    if body.get('errorCode') == 0:
                        omadac_id = body.get('result', {}).get('omadacId')
                    client.close()
                except Exception as e:
                    logger.warning(f"Could not get omadacId via API: {e}")

        if not device_id or not omadac_id:
            print("❌ Could not find controller or omadacId")
            await browser.close()
            return False

        # Step 2: Set up httpx client and fetch vouchers
        print("\n📋 Fetching voucher codes...")
        client = httpx.Client(verify=False, timeout=30.0)
        for name, value in cookie_dict.items():
            client.cookies.set(name, value, domain='.tplinkcloud.com', path='/')

        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'csrf-token': csrf_token,
            'Referer': f'{OMADA_URL}/',
            'Origin': OMADA_URL,
        }

        conn_prefix = f"{connector_base}/omadac/{device_id}/{omadac_id}"

        # Get sites
        r = client.get(f"{conn_prefix}/api/v2/sites/basic?currentPageSize=50&currentPage=1", headers=headers)
        sites_body = r.json()
        if sites_body.get('errorCode') == 0:
            sites = sites_body['result']['data']
            site_id = sites[0]['id']
            site_name = sites[0]['name']
            print(f"✅ Site: {site_name} ({site_id})")
        else:
            print(f"❌ Could not get sites: {sites_body}")
            await browser.close()
            client.close()
            return False

        # Fetch vouchers from the controller page
        # Navigate the controller page to the hotspot section to trigger voucher API calls
        ctrl_page = ctrl_page_ref[0]
        if ctrl_page:
            # Clear previous captures
            ctrl_apis.clear()

            # Try to navigate to the hotspot/voucher section through the controller SPA
            # The hotspot is under Settings > Authentication > Portal
            # or directly via the site-specific route
            
            # Navigate via URL hash to the hotspot settings page
            base_url = ctrl_page.url.split('#')[0]
            token_part = ctrl_page.url.split('?')[1] if '?' in ctrl_page.url else ''
            
            hotspot_paths = [
                f"#/sites/{site_id}/hotspot",
                f"#/sites/{site_id}/setting/hotspot",
                f"#/sites/{site_id}/auth/portal",
                f"#/hotspot",
                f"#/setting/hotspot",
                f"#/auth/portal",
            ]

            for hp in hotspot_paths:
                try:
                    await ctrl_page.goto(f"{base_url}?{token_part}{hp}", wait_until="networkidle", timeout=10000)
                    await ctrl_page.wait_for_timeout(3000)
                    
                    # Check if we got hotspot-related API calls
                    hotspot_calls = [c for c in ctrl_apis if any(kw in c['url'].lower() for kw in ['hotspot', 'voucher', 'portal'])]
                    if hotspot_calls:
                        print(f"  ✅ Found hotspot API calls via {hp}")
                        break
                except:
                    continue

            # Also try navigating via Vue router within the page
            await ctrl_page.evaluate(f'''() => {{
                const app = document.querySelector("#app")?.__vue_app__;
                if (app) {{
                    const router = app.config.globalProperties.$router;
                    try {{ router.push("/sites/{site_id}/hotspot"); }} catch(e) {{}}
                }}
            }}''')
            await ctrl_page.wait_for_timeout(3000)

        # Try to get vouchers via various API endpoints
        all_vouchers = []

        # Method 1: Direct connector API for vouchers
        voucher_endpoints = [
            f"{conn_prefix}/api/v2/sites/{site_id}/hotspot/vouchers",
            f"{conn_prefix}/api/v2/hotspot/vouchers",
            f"{conn_prefix}/{site_id}/api/v2/hotspot/vouchers",
        ]

        for ep in voucher_endpoints:
            try:
                r = client.get(ep, headers=headers)
                body = r.json()
                if body.get('errorCode') == 0:
                    vouchers = body.get('result', {}).get('data', [])
                    if vouchers:
                        all_vouchers.extend(vouchers)
                        print(f"  ✅ Got {len(vouchers)} vouchers from {ep.split('tplinkcloud.com')[-1]}")
            except:
                continue

        # Method 2: Try cmd/hotspot
        cmd_endpoints = [
            f"{conn_prefix}/api/v2/cmd/hotspot",
            f"{conn_prefix}/{site_id}/api/v2/cmd/hotspot",
        ]

        for ep in cmd_endpoints:
            try:
                r = client.post(ep,
                    json={"cmd": "listVouchers", "params": {"currentPage": 1, "currentPageSize": 500}},
                    headers=headers)
                body = r.json()
                if body.get('errorCode') == 0:
                    vouchers = body.get('result', {}).get('data', [])
                    if vouchers:
                        all_vouchers.extend(vouchers)
                        print(f"  ✅ Got {len(vouchers)} vouchers from cmd/hotspot")
            except:
                continue

        # Method 3: Check captured API responses from the controller page
        for call in ctrl_apis:
            if any(kw in call['url'].lower() for kw in ['hotspot', 'voucher']):
                result = call['body'].get('result', {})
                if isinstance(result, dict):
                    vouchers = result.get('data', [])
                    if vouchers:
                        all_vouchers.extend(vouchers)

        # Method 4: If controller page loaded, try fetching via its own API
        if ctrl_page and not all_vouchers:
            try:
                voucher_data = await ctrl_page.evaluate(f'''async () => {{
                    const results = [];
                    const paths = [
                        "/api/v2/sites/{site_id}/hotspot/vouchers",
                        "/api/v2/hotspot/vouchers?currentPageSize=500&currentPage=1",
                    ];
                    for (const p of paths) {{
                        try {{
                            const r = await fetch(p, {{credentials: "include"}});
                            const data = await r.json();
                            if (data.errorCode === 0 && data.result?.data) {{
                                results.push(...data.result.data);
                            }}
                        }} catch(e) {{}}
                    }}
                    return results;
                }}''')
                if voucher_data:
                    all_vouchers.extend(voucher_data)
                    print(f"  ✅ Got {len(voucher_data)} vouchers from controller page JS")
            except:
                pass

        # Filter vouchers to only our target types
        print(f"\n🔍 Filtering vouchers for: {', '.join(VOUCHER_NAMES.keys())}")
        
        codes_to_save = []
        matched = 0
        unmatched_names = set()

        for v in all_vouchers:
            voucher_name = v.get('name', v.get('portalName', ''))
            code = v.get('code', v.get('voucherCode', v.get('pin', '')))
            voucher_id = v.get('id', '')
            duration = v.get('duration', v.get('minutes', 0))

            if not code:
                continue

            # Check if voucher name matches our targets
            for target_name, (dur_type, dur_minutes) in VOUCHER_NAMES.items():
                if target_name.lower() in voucher_name.lower():
                    codes_to_save.append((code, dur_type, dur_minutes, voucher_id))
                    matched += 1
                    break
            else:
                # If no name match, try to match by duration
                for target_name, (dur_type, dur_minutes) in VOUCHER_NAMES.items():
                    if duration == dur_minutes:
                        codes_to_save.append((code, dur_type, dur_minutes, voucher_id))
                        matched += 1
                        break
                else:
                    if voucher_name:
                        unmatched_names.add(voucher_name)

        print(f"   Found {len(all_vouchers)} total vouchers")
        print(f"   Matched {matched} to our target types")
        
        if unmatched_names:
            print(f"   Other voucher names found: {', '.join(unmatched_names)}")

        # Show sample of what we found
        if codes_to_save:
            print(f"\n📋 Sample codes to save:")
            by_type = {}
            for code, dt, dm, vid in codes_to_save:
                by_type.setdefault(dt, []).append(code)
            for dt, codes in by_type.items():
                print(f"   {dt}: {len(codes)} codes (e.g., {codes[0]}, {codes[1] if len(codes) > 1 else '...'})")

        # Save to database
        if codes_to_save:
            inserted = await save_codes_to_db(codes_to_save)
            print(f"\n💾 Saved {inserted} new codes to database ({len(codes_to_save) - inserted} already existed)")
        else:
            print("\n⚠️ No matching voucher codes found!")
            print("   Make sure your Omada controller has vouchers with these names:")
            for name in VOUCHER_NAMES:
                print(f"   - {name}")

        # Show current database stats
        import aiosqlite
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("""
                SELECT duration_type, 
                       COUNT(*) as total,
                       SUM(CASE WHEN status = 'unused' THEN 1 ELSE 0 END) as unused,
                       SUM(CASE WHEN status = 'used' THEN 1 ELSE 0 END) as used
                FROM codes GROUP BY duration_type
            """)
            rows = await cursor.fetchall()

        print(f"\n📊 Database Stats:")
        if rows:
            for dtype, total, unused, used in rows:
                print(f"   {dtype}: {unused} available / {used} used / {total} total")
        else:
            print("   (empty)")

        print("\n" + "=" * 60)
        print("✅ Extraction complete!")
        print("=" * 60)

        # Cleanup
        client.close()
        await browser.close()
        return True


if __name__ == "__main__":
    asyncio.run(extract_codes())
