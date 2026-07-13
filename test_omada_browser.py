"""
Omada Cloud Login Script using Playwright (headless browser)
Handles the two-step login flow (email first, then password).
"""
import asyncio
import json
from playwright.async_api import async_playwright

EMAIL = "odimegwustanley2004@gmail.com"
PASSWORD = "@Chinoyerem101"
OMADA_URL = "https://euw1-omada-cloud.tplinkcloud.com"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ignore_https_errors=True
        )
        page = await context.new_page()
        
        # Capture API responses
        api_responses = []
        
        async def handle_response(response):
            url = response.url
            if any(x in url for x in ['login-with-uid-code', '/api/v1/central/', 'hotspot', 'voucher']):
                try:
                    body = await response.json()
                    api_responses.append({'url': url, 'status': response.status, 'body': body})
                    print(f"  📡 {response.status} {url[:100]}")
                    if body.get('errorCode') == 0:
                        print(f"     ✅ {json.dumps(body.get('result', {}))[:300]}")
                except:
                    pass
        
        page.on("response", handle_response)
        
        # Step 1: Navigate to Omada Cloud
        print("🌐 Navigating to Omada Cloud...")
        await page.goto(OMADA_URL, wait_until="networkidle", timeout=30000)
        print(f"  URL: {page.url}")
        
        # Step 2: Wait for email input and fill it
        print("\n📧 Step 1: Enter email...")
        email_sel = 'input[type="email"], input[name="email"], input[placeholder*="email" i], input[placeholder*="Email" i]'
        await page.wait_for_selector(email_sel, timeout=15000)
        email_input = await page.query_selector(email_sel)
        await email_input.fill(EMAIL)
        print(f"  Email entered: {EMAIL}")
        
        # Step 3: Click Next/Login button
        print("\n🖱️ Clicking Next...")
        # Try various button selectors
        next_btn = await page.query_selector('button[type="submit"]')
        if not next_btn:
            next_btn = await page.query_selector('button:has-text("Next")')
        if not next_btn:
            next_btn = await page.query_selector('button:has-text("Log In")')
        if not next_btn:
            next_btn = await page.query_selector('button:has-text("Sign In")')
        if not next_btn:
            next_btn = await page.query_selector('button:has-text("Continue")')
        if not next_btn:
            # Just press Enter
            await page.keyboard.press('Enter')
            print("  Pressed Enter")
        else:
            btn_text = await next_btn.text_content()
            print(f"  Clicked: '{btn_text}'")
            await next_btn.click()
        
        # Step 4: Wait for password field
        print("\n🔑 Step 2: Enter password...")
        try:
            pwd_sel = 'input[type="password"]'
            await page.wait_for_selector(pwd_sel, state='visible', timeout=10000)
            pwd_input = await page.query_selector(pwd_sel)
            await pwd_input.fill(PASSWORD)
            print("  Password entered")
            
            # Click login button
            login_btn = await page.query_selector('button[type="submit"]')
            if not login_btn:
                login_btn = await page.query_selector('button:has-text("Log In")')
            if not login_btn:
                login_btn = await page.query_selector('button:has-text("Sign In")')
            if not login_btn:
                login_btn = await page.query_selector('button:has-text("Login")')
            
            if login_btn:
                btn_text = await login_btn.text_content()
                print(f"  Clicking: '{btn_text}'")
                await login_btn.click()
            else:
                await page.keyboard.press('Enter')
                print("  Pressed Enter")
        except Exception as e:
            print(f"  Password field issue: {e}")
            # Maybe it's a single-step form, try clicking submit again
            await page.keyboard.press('Enter')
        
        # Step 5: Wait for successful login
        print("\n⏳ Waiting for login to complete...")
        try:
            # Wait for redirect back to Omada Cloud portal
            await page.wait_for_url("**/*omada*cloud*/**", timeout=45000)
            await page.wait_for_timeout(5000)  # Let SPA load
            print(f"  URL: {page.url}")
        except:
            print(f"  Timeout. Current URL: {page.url}")
            await page.screenshot(path="/home/user/omada-telegram-bot/omada_debug.png")
            # Check for error messages
            error_el = await page.query_selector('.error-msg, .error-message, [class*="error"], [class*="Error"]')
            if error_el:
                error_text = await error_el.text_content()
                print(f"  Error on page: {error_text}")
        
        await page.screenshot(path="/home/user/omada-telegram-bot/omada_login.png")
        print("📸 Screenshot saved")
        
        # Get all cookies
        cookies = await context.cookies()
        print(f"\n🍪 All cookies ({len(cookies)}):")
        for c in cookies:
            val = c['value']
            print(f"  {c['name']} = {val[:60]}{'...' if len(val) > 60 else ''} ({c['domain']})")
        
        # Find the csrfToken cookie
        csrf_token = None
        session_cookie = None
        for c in cookies:
            if c['name'] == 'csrfToken':
                csrf_token = c['value']
            if c['name'] == 'SESSION':
                session_cookie = c['value']
        
        print(f"\n🔑 csrfToken: {csrf_token[:80] if csrf_token else 'NOT FOUND'}")
        print(f"🔑 SESSION: {session_cookie[:80] if session_cookie else 'NOT FOUND'}")
        
        # If logged in, test API access
        if csrf_token or session_cookie:
            print("\n🧪 Testing API access...")
            api_result = await page.evaluate("""
                async () => {
                    const hostname = location.hostname;
                    const apiHostname = hostname.replace('omada', 'api-omada').replace('omada-cloud', 'omada').replace('omada', 'omada-cloud-manager').replace('-gray', '');
                    const apiBase = location.origin.replace(hostname, apiHostname);
                    
                    const results = {};
                    
                    // Test account info
                    try {
                        const r = await fetch(apiBase + '/api/v1/central/account', {credentials: 'include'});
                        results.account = await r.json();
                    } catch(e) { results.account = {error: e.message}; }
                    
                    // Test sites
                    try {
                        const r = await fetch(apiBase + '/api/v1/central/sites', {credentials: 'include'});
                        results.sites = await r.json();
                    } catch(e) { results.sites = {error: e.message}; }
                    
                    results.apiBase = apiBase;
                    return results;
                }
            """)
            print(f"  API Base: {api_result.get('apiBase')}")
            print(f"  Account: {json.dumps(api_result.get('account', {}))[:500]}")
            print(f"  Sites: {json.dumps(api_result.get('sites', {}))[:500]}")
            
            # Try to get controllers/vouchers
            if api_result.get('apiBase'):
                voucher_result = await page.evaluate(f"""
                    async () => {{
                        const apiBase = '{api_result["apiBase"]}';
                        const results = {{}};
                        
                        // List controllers
                        try {{
                            const r = await fetch(apiBase + '/api/v1/central/cloudAccessManager/portal/list', {{
                                method: 'POST', credentials: 'include',
                                headers: {{'Content-Type': 'application/json'}},
                                body: '{{}}'
                            }});
                            results.portalList = await r.json();
                        }} catch(e) {{ results.portalList = {{error: e.message}}; }}
                        
                        // List controllers
                        try {{
                            const r = await fetch(apiBase + '/api/v1/central/controllers', {{credentials: 'include'}});
                            results.controllers = await r.json();
                        }} catch(e) {{ results.controllers = {{error: e.message}}; }}
                        
                        return results;
                    }}
                """)
                print(f"\n  Portal List: {json.dumps(voucher_result.get('portalList', {}))[:500]}")
                print(f"  Controllers: {json.dumps(voucher_result.get('controllers', {}))[:500]}")
        
        # Print captured API responses
        print(f"\n📡 Captured {len(api_responses)} API responses:")
        for r in api_responses:
            print(f"  {r['url'][:100]} -> {r['status']}")
            body_str = json.dumps(r['body'])[:300]
            print(f"    {body_str}")
        
        await browser.close()
        print("\n✅ Done!")

asyncio.run(main())
