import os
import secrets
from datetime import date, datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

VALID_TIERS = {"free", "pro", "premium"}

DURATION_DAYS_MAP = {
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
}

def _calculate_expired_at(tier: str, duration_code: str):
    if tier == "premium" or duration_code == "lifetime":
        return None
    days = DURATION_DAYS_MAP.get(duration_code, 30)
    return datetime.now() + timedelta(days=days)

def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("Environment variable DATABASE_URL belum dikonfigurasi.")
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)

def normalize_domain(raw_domain: str) -> str:
    d = (raw_domain or "").strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.split("/")[0].strip()

def _format_ts(val) -> str:
    if val is None:
        return "-"
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return str(val)

# =====================================================================
# FUNGSI PEMROSESAN UNTUK HALAMAN DASBOR
# =====================================================================
def get_summary_stats() -> dict:
    today_str = date.today().isoformat()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN is_active THEN 1 ELSE 0 END), 0) AS active FROM credentials")
            cred_row = cur.fetchone() 

            cur.execute("SELECT COUNT(*) AS total FROM credential_domains")
            dom_row = cur.fetchone()

            cur.execute("SELECT COUNT(*) AS total FROM credential_users")
            usr_row = cur.fetchone()

            cur.execute("SELECT COUNT(*) AS total FROM daily_activity_user WHERE activity_date = %s", (today_str,))
            act_row = cur.fetchone()

            return {
                "total_credentials": cred_row["total"],
                "active_credentials": cred_row["active"],
                "total_domains": dom_row["total"],
                "total_users": usr_row["total"],
                "today_active_devices": act_row["total"],
            }
    finally:
        conn.close()

def get_daily_activities(
    search_query: str = "",
    start_date: str = "",
    end_date: str = "",
) -> list:
    q = (search_query or "").strip().lower()
    s_date = (start_date or "").strip()
    e_date = (end_date or "").strip()

    # Tukar otomatis jika pengguna memilih start_date > end_date
    if s_date and e_date and s_date > e_date:
        s_date, e_date = e_date, s_date

    conditions = []
    params = []

    if s_date and e_date:
        conditions.append("activity_date BETWEEN %s AND %s")
        params.extend([s_date, e_date])
    elif s_date:
        conditions.append("activity_date >= %s")
        params.append(s_date)
    elif e_date:
        conditions.append("activity_date <= %s")
        params.append(e_date)

    if q:
        conditions.append("(LOWER(device_id) LIKE %s OR LOWER(COALESCE(city, '')) LIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT id, device_id, activity_date::text AS activity_date, city, created_at
        FROM daily_activity_user
        {where_clause}
        ORDER BY activity_date DESC, id DESC
        LIMIT 500
    """

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            return [
                {
                    **row,
                    "created_at": _format_ts(row["created_at"]),
                }
                for row in rows
            ]
    finally:
        conn.close()

def get_top_cities_last_30_days() -> dict:
    """
    Mengambil data 30 hari terakhir (termasuk hari ini), mengelompokkan berdasarkan kota,
    mengambil Top 5 kota dengan rata-rata harian tertinggi, dan menentukan #1 tertinggi.
    """
    today = date.today()
    start_30d = today - timedelta(days=29)

    sql = """
        SELECT
            COALESCE(NULLIF(TRIM(city), ''), 'Unknown') AS city,
            COUNT(*) AS total_activities,
            COUNT(DISTINCT device_id) AS unique_devices,
            COUNT(DISTINCT activity_date) AS active_days,
            ROUND(COUNT(*)::numeric / 30.0, 2) AS avg_daily_30d,
            ROUND(COUNT(*)::numeric / NULLIF(COUNT(DISTINCT activity_date), 0), 2) AS avg_per_active_day
        FROM daily_activity_user
        WHERE activity_date BETWEEN %s AND %s
        GROUP BY COALESCE(NULLIF(TRIM(city), ''), 'Unknown')
        ORDER BY avg_daily_30d DESC, total_activities DESC
        LIMIT 5
    """

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (start_30d.isoformat(), today.isoformat()))
            rows = cur.fetchall()

            top_5 = []
            for idx, row in enumerate(rows, start=1):
                top_5.append({
                    "rank": idx,
                    "city": row["city"],
                    "total_activities": int(row["total_activities"]),
                    "unique_devices": int(row["unique_devices"]),
                    "active_days": int(row["active_days"]),
                    "avg_daily_30d": float(row["avg_daily_30d"]),
                    "avg_per_active_day": float(row["avg_per_active_day"] or 0),
                })

            highest_city = top_5[0] if top_5 else None
            return {
                "period_start": start_30d.isoformat(),
                "period_end": today.isoformat(),
                "top_5": top_5,
                "highest_avg_city": highest_city,
            }
    finally:
        conn.close()

def get_all_credentials(search_query: str = "") -> list:
    q = search_query.strip().lower()
    params = []
    where_clause = ""

    if q:
        where_clause = """
            WHERE LOWER(c.credential_key) LIKE %s
               OR LOWER(c.tier) LIKE %s
               OR EXISTS (
                   SELECT 1 FROM credential_domains cd2
                   WHERE cd2.credential_id = c.id AND LOWER(cd2.domain_name) LIKE %s
               )
        """
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    sql = f"""
        SELECT
            c.id,
            c.credential_key,
            c.tier,
            c.max_domains,
            c.max_devices,
            c.is_active,
            c.expired_at,
            c.created_at,
            COALESCE(ARRAY_AGG(DISTINCT cd.domain_name) FILTER (WHERE cd.domain_name IS NOT NULL), '{{}}') AS domains,
            COUNT(DISTINCT cu.id) AS used_devices
        FROM credentials c
        LEFT JOIN credential_domains cd ON cd.credential_id = c.id
        LEFT JOIN credential_users cu ON cu.credential_id = c.id
        {where_clause}
        GROUP BY c.id
        ORDER BY c.id DESC
    """

    now = datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            results = []
            for row in rows:
                exp_dt = row["expired_at"]
                is_expired = bool(exp_dt and exp_dt < now)
                results.append({
                    **row,
                    "domains": list(row["domains"] or []),
                    "is_expired": is_expired,
                    "expired_at_str": _format_ts(exp_dt) if exp_dt else "Selamanya",
                    "created_at": _format_ts(row["created_at"]),
                })
            return results
    finally:
        conn.close()

def toggle_credential_status(cred_id: int) -> bool:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE credentials SET is_active = NOT is_active WHERE id = %s RETURNING id",
                (cred_id,),
            )
            updated = cur.fetchone()
        conn.commit()
        return updated is not None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def update_credential_limits(cred_id: int, max_domains: int, max_devices: int) -> bool:
    if max_domains < 1 or max_devices < 1:
        return False

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE credentials
                SET max_domains = %s, max_devices = %s
                WHERE id = %s
                RETURNING id
                """,
                (max_domains, max_devices, cred_id),
            )
            updated = cur.fetchone()
        conn.commit()
        return updated is not None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_all_domains(search_query: str = "") -> list:
    q = search_query.strip().lower()
    params = []
    where_clause = ""

    if q:
        where_clause = "WHERE LOWER(cd.domain_name) LIKE %s OR LOWER(c.credential_key) LIKE %s"
        params.extend([f"%{q}%", f"%{q}%"])

    sql = f"""
        SELECT
            cd.id,
            cd.credential_id,
            cd.domain_name,
            cd.created_at,
            c.credential_key
        FROM credential_domains cd
        JOIN credentials c ON c.id = cd.credential_id
        {where_clause}
        ORDER BY cd.id DESC
    """

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            return [
                {
                    **row,
                    "created_at": _format_ts(row["created_at"]),
                }
                for row in rows
            ]
    finally:
        conn.close()

def get_all_users(search_query: str = "", cred_filter: str = "") -> list:
    q = search_query.strip().lower()
    conditions = []
    params = []

    if cred_filter:
        conditions.append("cu.credential_id = %s")
        params.append(int(cred_filter))

    if q:
        conditions.append("(LOWER(cu.device_id) LIKE %s OR LOWER(c.credential_key) LIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT
            cu.id,
            cu.credential_id,
            cu.device_id,
            cu.created_at,
            c.credential_key
        FROM credential_users cu
        JOIN credentials c ON c.id = cu.credential_id
        {where_clause}
        ORDER BY cu.id DESC
    """

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            return [
                {
                    **row,
                    "created_at": _format_ts(row["created_at"]),
                }
                for row in rows
            ]
    finally:
        conn.close()

# =====================================================================
# FUNGSI PEMROSESAN UNTUK API (/api/generate & /api/verify)
# =====================================================================
def create_credential(
    tier: str = "free",
    duration_code: str = "1m",
    max_domains: int = 1,
    max_devices: int = 50,
) -> dict:
    clean_tier = (tier or "free").strip().lower()
    if clean_tier not in VALID_TIERS:
        clean_tier = "free"

    expired_at = _calculate_expired_at(clean_tier, duration_code)
    new_key = f"WCH-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO credentials (credential_key, tier, max_domains, max_devices, is_active, expired_at)
                VALUES (%s, %s, %s, %s, TRUE, %s)
                RETURNING id
                """,
                (new_key, clean_tier, max_domains, max_devices, expired_at),
            )
            cred_id = cur.fetchone()["id"] # type: ignore
        conn.commit()
        return {
            "success": True,
            "status": 200,
            "id": cred_id,
            "credential_key": new_key,
            "tier": clean_tier,
            "max_domains": max_domains,
            "max_devices": max_devices,
            "expired_at": _format_ts(expired_at) if expired_at else "Selamanya",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def update_credential(
    cred_id: int,
    tier: str,
    duration_code: str,
    max_domains: int,
    max_devices: int,
) -> bool:
    if max_domains < 1 or max_devices < 1:
        return False

    clean_tier = (tier or "free").strip().lower()
    if clean_tier not in VALID_TIERS:
        clean_tier = "free"

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if clean_tier == "premium" or duration_code == "lifetime":
                cur.execute(
                    """
                    UPDATE credentials
                    SET tier = %s, max_domains = %s, max_devices = %s, expired_at = NULL
                    WHERE id = %s
                    RETURNING id
                    """,
                    (clean_tier, max_domains, max_devices, cred_id),
                )
            elif duration_code == "keep":
                cur.execute(
                    """
                    UPDATE credentials
                    SET tier = %s, max_domains = %s, max_devices = %s
                    WHERE id = %s
                    RETURNING id
                    """,
                    (clean_tier, max_domains, max_devices, cred_id),
                )
            else:
                new_exp = _calculate_expired_at(clean_tier, duration_code)
                cur.execute(
                    """
                    UPDATE credentials
                    SET tier = %s, max_domains = %s, max_devices = %s, expired_at = %s
                    WHERE id = %s
                    RETURNING id
                    """,
                    (clean_tier, max_domains, max_devices, new_exp, cred_id),
                )
            updated = cur.fetchone()
        conn.commit()
        return updated is not None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def delete_credential(cred_id: int) -> bool:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM credentials WHERE id = %s RETURNING id", (cred_id,))
            deleted = cur.fetchone()
        conn.commit()
        return deleted is not None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def verify_and_log_device(cred_key: str, raw_domain: str, device_id: str, city: str) -> dict:
    key = (cred_key or "").strip().upper()
    domain = normalize_domain(raw_domain)
    dev_id = (device_id or "").strip()

    if not key or not domain or not dev_id:
        return {"allowed": False, "status": 400, "reason": "MISSING_PARAMETERS"}

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tier, max_domains, max_devices, is_active, expired_at
                FROM credentials
                WHERE credential_key = %s
                FOR UPDATE
                """,
                (key,),
            )
            cred = cur.fetchone()
            if not cred or not cred["is_active"]:
                conn.rollback()
                return {"allowed": False, "status": 403, "reason": "INVALID_OR_INACTIVE_CREDENTIAL"}

            if cred["expired_at"] and cred["expired_at"] < datetime.now():
                conn.rollback()
                return {"allowed": False, "status": 403, "reason": "CREDENTIAL_EXPIRED"}

            # Cek apakah domain sudah terdaftar di credential_domains
            cur.execute(
                "SELECT credential_id FROM credential_domains WHERE domain_name = %s",
                (domain,),
            )
            dom_row = cur.fetchone()

            if dom_row:
                if dom_row["credential_id"] != cred["id"]:
                    conn.rollback()
                    return {"allowed": False, "status": 403, "reason": "DOMAIN_BOUND_TO_OTHER_CREDENTIAL"}
            else:
                # Domain baru dari client: daftarkan otomatis jika kuota max_domains masih cukup
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM credential_domains WHERE credential_id = %s",
                    (cred["id"],),
                )
                bound_dom_count = cur.fetchone()["cnt"]
                if bound_dom_count >= cred["max_domains"]:
                    conn.rollback()
                    return {
                        "allowed": False,
                        "status": 403,
                        "reason": "DOMAIN_QUOTA_EXCEEDED",
                        "used_domains": bound_dom_count,
                        "max_domains": cred["max_domains"],
                    }

                cur.execute(
                    "INSERT INTO credential_domains (credential_id, domain_name) VALUES (%s, %s)",
                    (cred["id"], domain),
                )

            # Cek slot device_id pada credential_users
            cur.execute(
                "SELECT id FROM credential_users WHERE credential_id = %s AND device_id = %s",
                (cred["id"], dev_id),
            )
            existing_user = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM credential_users WHERE credential_id = %s",
                (cred["id"],),
            )
            used_count = cur.fetchone()["cnt"]

            if not existing_user:
                if used_count >= cred["max_devices"]:
                    conn.rollback()
                    return {
                        "allowed": False,
                        "status": 403,
                        "reason": "DEVICE_QUOTA_EXCEEDED",
                        "used": used_count,
                        "max": cred["max_devices"],
                    }

                cur.execute(
                    "INSERT INTO credential_users (credential_id, device_id) VALUES (%s, %s)",
                    (cred["id"], dev_id),
                )
                used_count += 1

            today_str = date.today().isoformat()
            cur.execute(
                """
                INSERT INTO daily_activity_user (device_id, activity_date, city)
                VALUES (%s, %s, %s)
                ON CONFLICT (device_id, activity_date) DO NOTHING
                """,
                (dev_id, today_str, city or "Unknown"),
            )

        conn.commit()
        return {
            "allowed": True,
            "status": 200,
            "tier": cred["tier"],
            "used_devices": used_count,
            "max_devices": cred["max_devices"],
            "city": city or "Unknown",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    key = (cred_key or "").strip().upper()
    domain = normalize_domain(raw_domain)
    dev_id = (device_id or "").strip()

    if not key or not domain or not dev_id:
        return {"allowed": False, "status": 400, "reason": "MISSING_PARAMETERS"}

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Kunci baris kredensial (FOR UPDATE) agar aman dari race condition saat 50 PC menyala serentak
            cur.execute(
                "SELECT id, max_devices, is_active FROM credentials WHERE credential_key = %s FOR UPDATE",
                (key,),
            )
            cred = cur.fetchone()
            if not cred or not cred["is_active"]:
                conn.rollback()
                return {"allowed": False, "status": 403, "reason": "INVALID_OR_INACTIVE_CREDENTIAL"}

            cur.execute(
                "SELECT 1 FROM credential_domains WHERE credential_id = %s AND domain_name = %s",
                (cred["id"], domain),
            )
            if not cur.fetchone():
                conn.rollback()
                return {"allowed": False, "status": 403, "reason": "DOMAIN_MISMATCH"}

            cur.execute(
                "SELECT id FROM credential_users WHERE credential_id = %s AND device_id = %s",
                (cred["id"], dev_id),
            )
            existing_user = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM credential_users WHERE credential_id = %s",
                (cred["id"],),
            )
            used_count = cur.fetchone()["cnt"]

            if not existing_user:
                if used_count >= cred["max_devices"]:
                    conn.rollback()
                    return {
                        "allowed": False,
                        "status": 403,
                        "reason": "DEVICE_QUOTA_EXCEEDED",
                        "used": used_count,
                        "max": cred["max_devices"],
                    }

                cur.execute(
                    "INSERT INTO credential_users (credential_id, device_id) VALUES (%s, %s)",
                    (cred["id"], dev_id),
                )
                used_count += 1

            today_str = date.today().isoformat()
            cur.execute(
                """
                INSERT INTO daily_activity_user (device_id, activity_date, city)
                VALUES (%s, %s, %s)
                ON CONFLICT (device_id, activity_date) DO NOTHING
                """,
                (dev_id, today_str, city or "Unknown"),
            )

        conn.commit()
        return {
            "allowed": True,
            "status": 200,
            "used_devices": used_count,
            "max_devices": cred["max_devices"],
            "city": city or "Unknown",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()