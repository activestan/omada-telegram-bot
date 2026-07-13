"""
Quick test script to verify Omada Controller connection.
Run: python test_omada.py
"""
import asyncio
from omada_fetcher import OmadaController, sync_codes_from_omada
from database import init_db, get_code_stats


async def test_connection():
    print("=" * 50)
    print("🧪 Testing Omada Controller Connection")
    print("=" * 50)

    # Init DB
    await init_db()
    print("✅ Database initialized")

    # Test connection
    controller = OmadaController()
    print(f"🔗 Controller URL: {controller.base_url}")
    print(f"👤 Username: {controller.username}")
    print(f"🏢 Site ID: {controller.site_id}")

    logged_in = await controller.login()

    if logged_in:
        print("✅ Login successful!")

        # Try listing vouchers
        print("\n📋 Fetching unused vouchers...")
        vouchers = await controller.list_all_unused_vouchers()
        print(f"   Found {len(vouchers)} unused vouchers")

        for v in vouchers[:5]:
            print(f"   - {v['code']} ({v['duration']} minutes)")

        if len(vouchers) > 5:
            print(f"   ... and {len(vouchers) - 5} more")
    else:
        print("❌ Login failed! Check your credentials in .env")

    await controller.close()

    # Show current DB stats
    stats = await get_code_stats()
    if stats:
        print("\n📊 Current database stats:")
        for dtype, info in stats.items():
            print(f"   {dtype}: {info['unused']} available, {info['used']} used")
    else:
        print("\n📊 Database is empty - use Admin Panel to sync codes")

    print("\n" + "=" * 50)


if __name__ == "__main__":
    asyncio.run(test_connection())
