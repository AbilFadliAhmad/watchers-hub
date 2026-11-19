import os
import secrets
from datetime import date
import psycopg2
from psycopg2.extras import RealDictCursor


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


def get_daily_activities(search_query: str = "", filter_date: str = "") -> list:
    q = search_query.strip().lower()
    conditions = []
    params = []

    if filter_date:
        conditions.append("activity_date = %s")
        params.append(filter_date)

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


def get_all_credentials(search_query: str = "") -> list:
    q = search_query.strip().lower()
    params = []
    where_clause = ""

    if q:
        where_clause = """
            WHERE LOWER(c.credential_key) LIKE %s
               OR EXISTS (
                   SELECT 1 FROM credential_domains cd2
                   WHERE cd2.credential_id = c.id AND LOWER(cd2.domain_name) LIKE %s
               )
        """
        params.extend([f"%{q}%", f"%{q}%"])

    sql = f"""
        SELECT
            c.id,
            c.credential_key,
            c.max_domains,
            c.max_devices,
            c.is_active,
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

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            return [
                {
                    **row,
                    "domains": list(row["domains"] or []),
                    "created_at": _format_ts(row["created_at"]),
                }
                for row in rows
            ]
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
def create_credential_for_domain(raw_domain: str, max_domains: int = 1, max_devices: int = 50) -> dict:
    domain = normalize_domain(raw_domain)
    if not domain or "." not in domain:
        return {"success": False, "status": 400, "message": "Nama domain atau IP server tidak valid."}

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM credential_domains WHERE domain_name = %s", (domain,))
            if cur.fetchone():
                return {
                    "success": False,
                    "status": 409,
                    "message": f"Domain '{domain}' sudah terdaftar. Satu domain hanya berhak atas 1 kredensial.",
                }

            new_key = f"WCH-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
            cur.execute(
                """
                INSERT INTO credentials (credential_key, max_domains, max_devices, is_active)
                VALUES (%s, %s, %s, TRUE)
                RETURNING id
                """,
                (new_key, max_domains, max_devices),
            )
            cred_id = cur.fetchone()["id"]

            cur.execute(
                """
                INSERT INTO credential_domains (credential_id, domain_name)
                VALUES (%s, %s)
                """,
                (cred_id, domain),
            )

        conn.commit()
        return {
            "success": True,
            "status": 200,
            "credential_key": new_key,
            "domain": domain,
            "max_devices": max_devices,
        }
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