"""
Database module - manages codes and usage tracking with SQLite
Ensures codes are NEVER repeated and properly tracked.
"""
import aiosqlite
import logging
from datetime import datetime
from config import DATABASE_PATH

logger = logging.getLogger(__name__)


async def init_db():
    """Initialize the database with required tables."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Table for all available codes (pool of codes)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                duration_type TEXT NOT NULL,  -- 'daily', '3days', 'weekly', 'monthly'
                duration_minutes INTEGER NOT NULL,
                status TEXT DEFAULT 'unused',  -- 'unused' or 'used'
                omada_voucher_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_at TIMESTAMP,
                used_by TEXT,
                UNIQUE(code, duration_type)
            )
        """)

        # Table for detailed usage log (audit trail)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                duration_type TEXT NOT NULL,
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                requested_by TEXT,
                status TEXT DEFAULT 'delivered'  -- 'delivered', 'failed'
            )
        """)

        # Table for tracking request cooldowns (prevent abuse)
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
    logger.info("Database initialized successfully")


async def add_code(code: str, duration_type: str, duration_minutes: int, omada_voucher_id: str = None):
    """Add a new code to the pool."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                """INSERT OR IGNORE INTO codes (code, duration_type, duration_minutes, omada_voucher_id)
                   VALUES (?, ?, ?, ?)""",
                (code, duration_type, duration_minutes, omada_voucher_id)
            )
            await db.commit()
            logger.info(f"Added code: {code} ({duration_type})")
        except Exception as e:
            logger.error(f"Error adding code {code}: {e}")
            raise


async def add_codes_bulk(codes_data: list):
    """
    Add multiple codes at once.
    codes_data: list of tuples (code, duration_type, duration_minutes, omada_voucher_id)
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.executemany(
                """INSERT OR IGNORE INTO codes (code, duration_type, duration_minutes, omada_voucher_id)
                   VALUES (?, ?, ?, ?)""",
                codes_data
            )
            await db.commit()
            logger.info(f"Bulk added {len(codes_data)} codes")
        except Exception as e:
            logger.error(f"Error bulk adding codes: {e}")
            raise


async def get_unused_code(duration_type: str, user_id: str):
    """
    Get an unused code for the specified duration type.
    Marks it as used atomically to prevent race conditions.
    Returns the code string or None if no codes available.
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Use a transaction to ensure atomicity
        cursor = await db.execute(
            """SELECT id, code FROM codes
               WHERE duration_type = ? AND status = 'unused'
               ORDER BY created_at ASC
               LIMIT 1""",
            (duration_type,)
        )
        row = await cursor.fetchone()

        if row is None:
            logger.warning(f"No unused codes available for type: {duration_type}")
            return None

        code_id, code = row

        # Mark as used immediately
        await db.execute(
            """UPDATE codes SET status = 'used', used_at = ?, used_by = ?
               WHERE id = ?""",
            (datetime.now().isoformat(), str(user_id), code_id)
        )

        # Log the usage
        await db.execute(
            """INSERT INTO usage_log (code, duration_type, requested_by)
               VALUES (?, ?, ?)""",
            (code, duration_type, str(user_id))
        )

        await db.commit()
        logger.info(f"Code {code} ({duration_type}) issued to user {user_id}")
        return code


async def is_code_used(code: str) -> bool:
    """Check if a code has been used."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT status FROM codes WHERE code = ?", (code,)
        )
        row = await cursor.fetchone()
        return row is not None and row[0] == 'used'


async def get_code_stats():
    """Get statistics about code usage."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT duration_type,
                   COUNT(*) as total,
                   SUM(CASE WHEN status = 'unused' THEN 1 ELSE 0 END) as unused,
                   SUM(CASE WHEN status = 'used' THEN 1 ELSE 0 END) as used
            FROM codes
            GROUP BY duration_type
        """)
        rows = await cursor.fetchall()
        return {row[0]: {"total": row[1], "unused": row[2], "used": row[3]} for row in rows}


async def check_request_cooldown(user_id: str, duration_type: str) -> tuple:
    """
    Check if user can request a code based on cooldown periods.
    Returns (allowed: bool, message: str)
    
    Cooldowns:
    - daily: 20 hours
    - 3days: 68 hours
    - weekly: 6 days
    - monthly: 28 days
    """
    cooldown_hours = {
        "daily": 20,
        "3days": 68,
        "weekly": 144,   # 6 days
        "monthly": 672   # 28 days
    }

    cooldown = cooldown_hours.get(duration_type, 20)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """SELECT last_requested FROM request_tracker
               WHERE user_id = ? AND duration_type = ?""",
            (str(user_id), duration_type)
        )
        row = await cursor.fetchone()

        if row is None:
            # First request - record it
            await db.execute(
                """INSERT OR REPLACE INTO request_tracker (user_id, duration_type, last_requested)
                   VALUES (?, ?, ?)""",
                (str(user_id), duration_type, datetime.now().isoformat())
            )
            await db.commit()
            return True, ""

        last_requested = datetime.fromisoformat(row[0])
        hours_since = (datetime.now() - last_requested).total_seconds() / 3600

        if hours_since < cooldown:
            remaining = cooldown - hours_since
            if remaining > 24:
                time_str = f"{remaining/24:.1f} days"
            else:
                time_str = f"{remaining:.1f} hours"
            return False, f"⏰ Please wait {time_str} before requesting another {duration_type} code."

        # Update the timestamp
        await db.execute(
            """UPDATE request_tracker SET last_requested = ?
               WHERE user_id = ? AND duration_type = ?""",
            (datetime.now().isoformat(), str(user_id), duration_type)
        )
        await db.commit()
        return True, ""


async def get_recent_usage(user_id: str, limit: int = 10):
    """Get recent code usage for a user."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """SELECT code, duration_type, requested_at
               FROM usage_log
               WHERE requested_by = ?
               ORDER BY requested_at DESC
               LIMIT ?""",
            (str(user_id), limit)
        )
        return await cursor.fetchall()
