import os
import secrets
from datetime import date, datetime, timedelta, timezone
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import re

# Load environment variables from .env file
load_dotenv()

VALID_TIERS = {"free", "pro", "premium"}
WIB = timezone(timedelta(hours=7))
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

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

def get_public_telemetry_14d() -> dict:
    today = date.today()
    start_date = today - timedelta(days=13)

    sql = """
        SELECT
            activity_date::text AS act_date,
            COALESCE(NULLIF(TRIM(city), ''), 'Unknown') AS city,
            COUNT(*) AS device_count
        FROM daily_activity_user
        WHERE activity_date BETWEEN %s AND %s
        GROUP BY activity_date, COALESCE(NULLIF(TRIM(city), ''), 'Unknown')
        ORDER BY activity_date ASC, device_count DESC
    """

    month_names = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (start_date.isoformat(), today.isoformat()))
            rows = cur.fetchall()

        # Agregasi statistik per kota selama 14 hari terakhir
        city_totals = {}
        grouped_by_date = {}

        for row in rows:
            d_str = row["act_date"]
            city_name = row["city"]
            count = int(row["device_count"])

            grouped_by_date.setdefault(d_str, []).append({
                "city": city_name,
                "devices": count,
            })

            if city_name not in city_totals:
                city_totals[city_name] = {"city": city_name, "total_devices": 0, "active_days": 0}
            city_totals[city_name]["total_devices"] += count
            city_totals[city_name]["active_days"] += 1

        # Tahap 1: Ambil Top 5 kota dengan total aktivitas terbanyak
        top_5_most_active = sorted(
            city_totals.values(),
            key=lambda x: x["total_devices"],
            reverse=True,
        )[:5]

        # Hitung rata-rata harian untuk masing-masing kandidat Top 5
        for item in top_5_most_active:
            item["avg_devices"] = round(item["total_devices"] / max(item["active_days"], 1), 2)

        # Tahap 2: Filter dari Top 5 menjadi Top 3 berdasarkan rata-rata tertinggi
        top_3_highest_avg = sorted(
            top_5_most_active,
            key=lambda x: (x["avg_devices"], x["total_devices"]),
            reverse=True,
        )[:3]
        allowed_top_3_names = {item["city"] for item in top_3_highest_avg}

        # Susun data 14 hari dengan regions difilter khusus Top 3 kota terpilih
        daily_activity = []
        for i in range(14):
            curr_day = start_date + timedelta(days=i)
            iso_str = curr_day.isoformat()
            raw_regions = grouped_by_date.get(iso_str, [])
            filtered_regions = [r for r in raw_regions if r["city"] in allowed_top_3_names]
            total_dev = sum(r["devices"] for r in raw_regions)
            short_label = f"{curr_day.day:02d} {month_names[curr_day.month]}"

            daily_activity.append({
                "date": short_label,
                "full_date": "Hari Ini" if curr_day == today else f"{curr_day.day} {month_names[curr_day.month]} {curr_day.year}",
                "total_devices": total_dev,
                "regions": filtered_regions,
            })

        return {
            "last_updated": datetime.now().strftime("%d %b %Y, %H:%M WIB"),
            "top_3_cities": top_3_highest_avg,
            "daily_activity": daily_activity,
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
# FUNGSI CRUD Credential
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

# =====================================================================
# FUNGSI PEMROSESAN DOMAIN
# =====================================================================
def bind_domain_to_credential(cred_key: str, raw_domain: str, email: str = "") -> dict:
    key = (cred_key or "").strip().upper()
    domain = normalize_domain(raw_domain)
    clean_email = (email or "").strip().lower()

    if not key or not domain:
        return {"success": False, "status": 400, "message": "Credential Key dan Domain wajib diisi."}

    if clean_email and not EMAIL_REGEX.match(clean_email):
        return {"success": False, "status": 400, "message": "Format alamat email tidak valid."}

    now_wib = datetime.now(WIB)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Kunci & ambil detail credential tujuan
            cur.execute(
                """
                SELECT id, credential_key, tier, max_domains, is_active, expired_at, email
                FROM credentials
                WHERE credential_key = %s
                FOR UPDATE
                """,
                (key,),
            )
            cred = cur.fetchone()
            if not cred:
                conn.rollback()
                return {"success": False, "status": 404, "message": "Credential Key tidak ditemukan."}

            if not cred["is_active"]:
                conn.rollback()
                return {"success": False, "status": 403, "message": "Credential Key berstatus nonaktif / diblokir."}

            if cred["expired_at"]:
                exp_dt = cred["expired_at"]
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=WIB)
                if exp_dt < now_wib:
                    conn.rollback()
                    return {"success": False, "status": 403, "message": "Masa berlaku Credential Key sudah habis."}

            # 2. Cek apakah domain sudah terdaftar di credential_domains
            cur.execute(
                """
                SELECT cd.id, cd.credential_id, c.credential_key AS owner_key
                FROM credential_domains cd
                JOIN credentials c ON c.id = cd.credential_id
                WHERE cd.domain_name = %s
                FOR UPDATE
                """,
                (domain,),
            )
            existing_dom = cur.fetchone()

            if existing_dom:
                # Jika sudah terdaftar di credential yang sama
                if existing_dom["credential_id"] == cred["id"]:
                    if clean_email:
                        cur.execute(
                            "UPDATE credentials SET email = %s WHERE id = %s",
                            (clean_email, cred["id"]),
                        )
                    conn.commit()
                    return {
                        "success": True,
                        "status": 200,
                        "already_bound": True,
                        "domain": domain,
                        "credential_key": cred["credential_key"],
                        "message": f"Domain '{domain}' sudah aktif pada Credential Key ini.",
                    }

                # Jika domain sudah didaftarkan oleh orang/lisensi lain -> kirim sinyal conflict
                conn.rollback()
                masked_owner = existing_dom["owner_key"][:8] + "****"
                return {
                    "success": False,
                    "status": 409,
                    "conflict": True,
                    "domain": domain,
                    "owner_hint": masked_owner,
                    "message": f"Domain '{domain}' sudah terikat pada lisensi lain ({masked_owner}). Apakah Anda ingin memutuskan tautan lama dan memindahkannya?",
                }

            # 3. Domain belum terdaftar -> cek kuota max_domains milik credential
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM credential_domains WHERE credential_id = %s",
                (cred["id"],),
            )
            used_domains = int(cur.fetchone()["cnt"])
            max_domains = int(cred["max_domains"])

            if used_domains >= max_domains:
                conn.rollback()
                return {
                    "success": False,
                    "status": 403,
                    "message": f"Kuota domain penuh ({used_domains}/{max_domains} domain).",
                }

            # 4. Simpan domain baru (dan email jika disertakan)
            cur.execute(
                """
                INSERT INTO credential_domains (credential_id, domain_name)
                VALUES (%s, %s)
                """,
                (cred["id"], domain),
            )
            if clean_email:
                cur.execute(
                    "UPDATE credentials SET email = %s WHERE id = %s",
                    (clean_email, cred["id"]),
                )

        conn.commit()
        return {
            "success": True,
            "status": 200,
            "domain": domain,
            "credential_key": cred["credential_key"],
            "used_domains": used_domains + 1,
            "max_domains": max_domains,
            "message": f"Domain '{domain}' berhasil didaftarkan ke lisensi.",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def transfer_domain_with_email(cred_key: str, raw_domain: str, email: str) -> dict:
    """Memutuskan domain dari lisensi lama, menyimpan email pemilik baru ke credentials, dan menautkan domain."""
    key = (cred_key or "").strip().upper()
    domain = normalize_domain(raw_domain)
    clean_email = (email or "").strip().lower()

    if not key or not domain:
        return {"success": False, "status": 400, "message": "Credential Key dan Domain wajib diisi."}

    if not clean_email or not EMAIL_REGEX.match(clean_email):
        return {
            "success": False,
            "status": 400,
            "message": "Masukkan alamat email yang valid untuk mengonfirmasi pemutusan domain.",
        }

    now_wib = datetime.now(WIB)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Validasi & kunci credential baru
            cur.execute(
                """
                SELECT id, credential_key, max_domains, is_active, expired_at
                FROM credentials
                WHERE credential_key = %s
                FOR UPDATE
                """,
                (key,),
            )
            cred = cur.fetchone()
            if not cred or not cred["is_active"]:
                conn.rollback()
                return {"success": False, "status": 403, "message": "Credential Key tujuan tidak valid atau nonaktif."}

            if cred["expired_at"]:
                exp_dt = cred["expired_at"]
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=WIB)
                if exp_dt < now_wib:
                    conn.rollback()
                    return {"success": False, "status": 403, "message": "Credential Key tujuan sudah kedaluwarsa."}

            # 2. Cek kuota domain di credential baru (kecuali domain memang sudah ada di credential ini)
            cur.execute(
                "SELECT id, credential_id FROM credential_domains WHERE domain_name = %s FOR UPDATE",
                (domain,),
            )
            existing_dom = cur.fetchone()

            if not existing_dom or existing_dom["credential_id"] != cred["id"]:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM credential_domains WHERE credential_id = %s",
                    (cred["id"],),
                )
                used_domains = int(cur.fetchone()["cnt"])
                if used_domains >= int(cred["max_domains"]):
                    conn.rollback()
                    return {
                        "success": False,
                        "status": 403,
                        "message": f"Kuota domain pada lisensi baru sudah penuh ({used_domains}/{cred['max_domains']}).",
                    }

            # 3. Simpan alamat email valid ke baris credentials tujuan
            cur.execute(
                "UPDATE credentials SET email = %s WHERE id = %s",
                (clean_email, cred["id"]),
            )

            # 4. Putuskan domain dari lisensi lama dan tautkan ke lisensi baru
            if existing_dom:
                cur.execute(
                    "UPDATE credential_domains SET credential_id = %s WHERE id = %s",
                    (cred["id"], existing_dom["id"]),
                )
            else:
                cur.execute(
                    "INSERT INTO credential_domains (credential_id, domain_name) VALUES (%s, %s)",
                    (cred["id"], domain),
                )

        conn.commit()
        return {
            "success": True,
            "status": 200,
            "domain": domain,
            "credential_key": cred["credential_key"],
            "email": clean_email,
            "message": f"Tautan domain lama diputus dan '{domain}' resmi terhubung ke lisensi Anda.",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# =====================================================================
#  FUNGSI VERIFIKASI
# =====================================================================
def verify_and_log_device(cred_key: str, raw_domain: str, device_id: str, city: str) -> dict:
    # Gunakan timezone Asia/Jakarta untuk semua perhitungan tanggal/waktu
    from zoneinfo import ZoneInfo
    WIB = ZoneInfo("Asia/Jakarta")

    key = (cred_key or "").strip().upper()
    domain = normalize_domain(raw_domain)
    dev_id = (device_id or "").strip()

    if not key or not domain or not dev_id:
        return {
            "allowed": False,
            "status": 400,
            "reason": "MISSING_PARAMETERS",
            "message": "Parameter credential_key, domain, dan device_id wajib diisi.",
        }

    now_wib = datetime.now(WIB)
    today_wib = now_wib.date().isoformat()

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Ambil detail credential_key + kunci baris (FOR UPDATE) cegah race condition
            cur.execute(
                """
                SELECT id, credential_key, tier, max_domains, max_devices, is_active, expired_at
                FROM credentials
                WHERE credential_key = %s
                FOR UPDATE
                """,
                (key,),
            )
            cred = cur.fetchone()

            if not cred:
                conn.rollback()
                return {
                    "allowed": False,
                    "status": 404,
                    "reason": "CREDENTIAL_NOT_FOUND",
                    "message": "Credential key tidak ditemukan di server lisensi.",
                }

            if not cred["is_active"]:
                conn.rollback()
                return {
                    "allowed": False,
                    "status": 403,
                    "reason": "CREDENTIAL_INACTIVE",
                    "message": "Credential key berstatus nonaktif / diblokir.",
                }

            if cred["expired_at"]:
                exp_dt = cred["expired_at"]
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=WIB)
                if exp_dt < now_wib:
                    conn.rollback()
                    return {
                        "allowed": False,
                        "status": 403,
                        "reason": "CREDENTIAL_EXPIRED",
                        "message": "Masa berlaku credential key telah habis (Expired).",
                    }

            # 2. Verifikasi apakah domain sudah terdaftar pada credential_key ini
            cur.execute(
                """
                SELECT id, credential_id
                FROM credential_domains
                WHERE domain_name = %s
                """,
                (domain,),
            )
            dom_row = cur.fetchone()

            if not dom_row:
                conn.rollback()
                return {
                    "allowed": False,
                    "status": 403,
                    "reason": "DOMAIN_NOT_REGISTERED",
                    "message": f"Domain '{domain}' belum terdaftar pada credential key ini.",
                }

            if dom_row["credential_id"] != cred["id"]:
                conn.rollback()
                return {
                    "allowed": False,
                    "status": 403,
                    "reason": "DOMAIN_MISMATCH",
                    "message": f"Domain '{domain}' terdaftar pada credential key lain.",
                }

            # 3. Cek apakah pasangan (credential_id, device_id) sudah ada di credential_users
            cur.execute(
                """
                SELECT id
                FROM credential_users
                WHERE credential_id = %s AND device_id = %s
                """,
                (cred["id"], dev_id),
            )
            existing_device = cur.fetchone()

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM credential_users
                WHERE credential_id = %s
                """,
                (cred["id"],),
            )
            used_devices = int(cur.fetchone()["cnt"])
            max_devices = int(cred["max_devices"])

            if not existing_device:
                # Bandingkan jumlah count dengan kuota max_devices
                if used_devices >= max_devices:
                    conn.rollback()
                    return {
                        "allowed": False,
                        "status": 403,
                        "reason": "DEVICE_QUOTA_EXCEEDED",
                        "message": f"Kuota perangkat penuh ({used_devices}/{max_devices} PC).",
                        "used_devices": used_devices,
                        "max_devices": max_devices,
                    }

                cur.execute(
                    """
                    INSERT INTO credential_users (credential_id, device_id)
                    VALUES (%s, %s)
                    """,
                    (cred["id"], dev_id),
                )
                used_devices += 1

            # 4. Semua lolos -> catat absen harian di daily_activity_user (1x per hari WIB)
            clean_city = (city or "").strip() or "Unknown"
            cur.execute(
                """
                INSERT INTO daily_activity_user (device_id, activity_date, city)
                VALUES (%s, %s, %s)
                ON CONFLICT (device_id, activity_date) DO NOTHING
                """,
                (dev_id, today_wib, clean_city),
            )

        conn.commit()
        return {
            "allowed": True,
            "status": 200,
            "tier": cred["tier"],
            "domain": domain,
            "device_id": dev_id,
            "used_devices": used_devices,
            "max_devices": max_devices,
            "activity_date": today_wib,
            "city": clean_city,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()