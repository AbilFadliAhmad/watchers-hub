import os
import secrets
from datetime import date, datetime, timedelta, timezone
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import re
from email.message import EmailMessage
import smtplib

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

# ============================================================
# HELPER FUNCTIONS
# ============================================================

# --- Database Connection ---
def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("Environment variable DATABASE_URL belum dikonfigurasi.")
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)

# --- Email & OTP Delivery ---
def _send_otp_via_gmail(to_email: str, otp_code: str, domain: str, cred_key: str) -> None:
    smtp_user = os.environ.get("GMAIL_SMTP_USER", "").strip()
    smtp_pass = os.environ.get("GMAIL_SMTP_APP_PASSWORD", "").strip()

    if not smtp_user or not smtp_pass:
        raise RuntimeError("Konfigurasi GMAIL_SMTP_USER / GMAIL_SMTP_APP_PASSWORD belum diatur di server.")

    msg = EmailMessage()
    msg["Subject"] = f"[Watchers Hub] Kode OTP Pemutusan Domain: {otp_code}"
    msg["From"] = f"Watchers Hub Security <{smtp_user}>"
    msg["To"] = to_email
    msg.set_content(
        f"Halo,\n\n"
        f"Anda meminta pemutusan tautan lama dan pemindahan domain '{domain}' ke Credential Key {cred_key}.\n\n"
        f"Kode Verifikasi OTP Anda: {otp_code}\n"
        f"Kode ini berlaku selama 10 menit dan hanya dapat digunakan satu kali.\n\n"
        f"Jika Anda tidak merasa melakukan permintaan ini, abaikan email ini.\n"
        f"— Watchers Hub"
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)

# --- Credential Validation & Expiration ---
def _validate_credential_record(
    cred: dict | None,
    now_wib: datetime | None = None,
) -> tuple[bool, str, dict]:
    """
    Helper tunggal untuk memvalidasi baris dict `cred` dari tabel `credentials`:
    - Mengecek keberadaan record
    - Mengecek status aktif (`is_active`)
    - Mengecek masa berlaku (`expired_at` berbasis WIB)

    Mengembalikan: (is_valid, expired_str, error_dict)
    """
    if not cred:
        return False, "", {
            "valid": False,
            "allowed": False,
            "status": 404,
            "reason": "NOT_FOUND",
            "message": "Credential Key tidak ditemukan di Watchers Hub.",
        }

    if not cred.get("is_active"):
        return False, "", {
            "valid": False,
            "allowed": False,
            "status": 403,
            "reason": "INACTIVE",
            "message": "Credential Key berstatus nonaktif / diblokir.",
        }

    ref_now = now_wib or datetime.now(WIB)
    if cred.get("expired_at"):
        exp_dt = cred["expired_at"]
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=WIB)
        if exp_dt < ref_now:
            return False, "", {
                "valid": False,
                "allowed": False,
                "status": 403,
                "reason": "EXPIRED",
                "message": f"Masa berlaku Credential Key telah habis pada {_format_ts(exp_dt)}.",
            }
        expired_str = _format_ts(exp_dt)
    else:
        expired_str = "Selamanya"

    return True, expired_str, {}
def _calculate_expired_at(tier: str, duration_code: str):
    if tier == "premium" or duration_code == "lifetime":
        return None
    days = DURATION_DAYS_MAP.get(duration_code, 30)
    return datetime.now() + timedelta(days=days)

# --- Data Formatting & Normalization ---
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

# ============================================================
# DASHBOARD & STATISTIK
# ============================================================
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

# ============================================================
# MANAJEMEN CREDENTIAL
# ============================================================
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
            c.email,
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

# --- Credential Update Status & Information --- 
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

# --- Credential CRUD ---
def create_credential(
    email: str,
    tier: str = "free",
    duration_code: str = "1m",
    max_domains: int = 1,
    max_devices: int = 50,
) -> dict:
    clean_email = (email or "").strip().lower()
    if not clean_email or not EMAIL_REGEX.match(clean_email):
        return {
            "success": False,
            "status": 400,
            "message": "Alamat email wajib diisi dengan format yang valid.",
        }

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
                INSERT INTO credentials (credential_key, email, tier, max_domains, max_devices, is_active, expired_at)
                VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                RETURNING id
                """,
                (new_key, clean_email, clean_tier, max_domains, max_devices, expired_at),
            )
            cred_id = cur.fetchone()["id"]  # type: ignore
        conn.commit()
        return {
            "success": True,
            "status": 200,
            "id": cred_id,
            "credential_key": new_key,
            "email": clean_email,
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
    email: str,
    tier: str,
    duration_code: str,
    max_domains: int,
    max_devices: int,
) -> bool:
    clean_email = (email or "").strip().lower()
    if not clean_email or not EMAIL_REGEX.match(clean_email):
        return False

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
                    SET email = %s, tier = %s, max_domains = %s, max_devices = %s, expired_at = NULL
                    WHERE id = %s
                    RETURNING id
                    """,
                    (clean_email, clean_tier, max_domains, max_devices, cred_id),
                )
            elif duration_code == "keep":
                cur.execute(
                    """
                    UPDATE credentials
                    SET email = %s, tier = %s, max_domains = %s, max_devices = %s
                    WHERE id = %s
                    RETURNING id
                    """,
                    (clean_email, clean_tier, max_domains, max_devices, cred_id),
                )
            else:
                new_exp = _calculate_expired_at(clean_tier, duration_code)
                cur.execute(
                    """
                    UPDATE credentials
                    SET email = %s, tier = %s, max_domains = %s, max_devices = %s, expired_at = %s
                    WHERE id = %s
                    RETURNING id
                    """,
                    (clean_email, clean_tier, max_domains, max_devices, new_exp, cred_id),
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
# MANAJEMEN DOMAIN
# =====================================================================
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

def bind_domain_to_credential(cred_key: str, raw_domain: str) -> dict:
    key = (cred_key or "").strip().upper()
    domain = normalize_domain(raw_domain)

    if not key or not domain:
        return {"success": False, "status": 400, "message": "Credential Key dan Domain wajib diisi."}

    now_wib = datetime.now(WIB)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
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

            is_ok, _, err_resp = _validate_credential_record(cred, now_wib)
            if not is_ok:
                conn.rollback()
                return {
                    "success": False,
                    "status": err_resp.get("status", 403),
                    "message": err_resp.get("message", "Credential Key tidak valid."),
                }

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
                if existing_dom["credential_id"] == cred["id"]:
                    conn.commit()
                    return {
                        "success": True,
                        "status": 200,
                        "already_bound": True,
                        "domain": domain,
                        "credential_key": cred["credential_key"],
                        "message": f"Domain '{domain}' sudah terhubung dengan Credential Key ini.",
                    }

                conn.rollback()
                masked_owner = existing_dom["owner_key"][:8] + "****"
                return {
                    "success": False,
                    "status": 409,
                    "conflict": True,
                    "domain": domain,
                    "message": f"Domain '{domain}' sudah tertaut pada lisensi lain ({masked_owner}). Masukkan alamat email valid untuk mengirim kode OTP pemutusan tautan.",
                }

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
# DOMAIN TRANSFER & OTP VERIFICATION
# =====================================================================
def request_domain_transfer_otp(cred_key: str, raw_domain: str, email: str) -> dict:
    key = (cred_key or "").strip().upper()
    domain = normalize_domain(raw_domain)
    clean_email = (email or "").strip().lower()

    if not key or not domain:
        return {"success": False, "status": 400, "message": "Credential Key dan Domain wajib diisi."}

    if not clean_email or not EMAIL_REGEX.match(clean_email):
        return {"success": False, "status": 400, "message": "Alamat email tidak valid."}

    now_wib = datetime.now(WIB)
    expired_at = now_wib + timedelta(minutes=10)
    otp_code = f"{secrets.randbelow(1000000):06d}"

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, credential_key, email, is_active, expired_at
                FROM credentials
                WHERE credential_key = %s
                """,
                (key,),
            )
            target_cred = cur.fetchone()

            is_ok, _, err_resp = _validate_credential_record(target_cred, now_wib)
            if not is_ok:
                conn.rollback()
                return {
                    "success": False,
                    "status": err_resp.get("status", 403),
                    "message": err_resp.get("message", "Credential Key tujuan tidak valid."),
                }

            # Nonaktifkan OTP lama yang belum terpakai untuk kombinasi yang sama
            cur.execute(
                """
                UPDATE domain_transfer_otps
                SET is_used = TRUE
                WHERE credential_key = %s AND domain_name = %s AND email = %s AND is_used = FALSE
                """,
                (key, domain, clean_email),
            )

            # Simpan OTP baru (berlaku 10 menit)
            cur.execute(
                """
                INSERT INTO domain_transfer_otps (credential_key, domain_name, email, otp_code, expired_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (key, domain, clean_email, otp_code, expired_at),
            )

        # Kirim OTP lewat Gmail SMTP sebelum commit transaksi
        _send_otp_via_gmail(clean_email, otp_code, domain, key)
        conn.commit()

        return {
            "success": True,
            "status": 200,
            "message": f"Kode OTP 6 digit telah dikirim ke {clean_email} (berlaku 10 menit).",
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "status": 500, "message": f"Gagal mengirim OTP: {e}"}
    finally:
        conn.close()

def verify_otp_and_transfer_domain(cred_key: str, raw_domain: str, email: str, otp_code: str) -> dict:
    key = (cred_key or "").strip().upper()
    domain = normalize_domain(raw_domain)
    clean_email = (email or "").strip().lower()
    clean_otp = (otp_code or "").strip()

    if not key or not domain or not clean_email or len(clean_otp) != 6:
        return {"success": False, "status": 400, "message": "Data verifikasi OTP tidak lengkap."}

    now_wib = datetime.now(WIB)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Kunci & cek OTP terakhir yang valid
            cur.execute(
                """
                SELECT id, otp_code, expired_at
                FROM domain_transfer_otps
                WHERE credential_key = %s
                  AND domain_name = %s
                  AND email = %s
                  AND is_used = FALSE
                ORDER BY id DESC
                LIMIT 1
                FOR UPDATE
                """,
                (key, domain, clean_email),
            )
            otp_row = cur.fetchone()
            if not otp_row:
                conn.rollback()
                return {"success": False, "status": 400, "message": "Kode OTP tidak ditemukan atau sudah digunakan."}

            otp_exp = otp_row["expired_at"]
            if otp_exp.tzinfo is None:
                otp_exp = otp_exp.replace(tzinfo=WIB)
            if otp_exp < now_wib:
                conn.rollback()
                return {"success": False, "status": 400, "message": "Kode OTP sudah kedaluwarsa. Silakan kirim ulang OTP."}

            if otp_row["otp_code"] != clean_otp:
                conn.rollback()
                return {"success": False, "status": 400, "message": "Kode OTP salah."}

            cur.execute("UPDATE domain_transfer_otps SET is_used = TRUE WHERE id = %s", (otp_row["id"],))

            # 2. Kunci & validasi credential tujuan menggunakan helper tunggal
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

            is_ok, _, err_resp = _validate_credential_record(cred, now_wib)
            if not is_ok:
                conn.rollback()
                return {
                    "success": False,
                    "status": err_resp.get("status", 403),
                    "message": err_resp.get("message", "Credential Key tujuan tidak valid."),
                }

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
                        "message": f"Kuota domain pada lisensi ini penuh ({used_domains}/{cred['max_domains']}).",
                    }

            # 3. Putuskan dari lisensi lama, simpan email terverifikasi ke credentials, dan tautkan domain
            cur.execute("UPDATE credentials SET email = %s WHERE id = %s", (clean_email, cred["id"]))

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
            "message": f"Verifikasi OTP berhasil! Domain '{domain}' kini terhubung ke lisensi Anda.",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ============================================================
# MANAJEMEN USER / DEVICE
# ============================================================
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

# ============================================================
# CREDENTIAL & LICENSE VERIFICATION
# ============================================================
def check_credential_status(cred_key: str) -> dict:
    """
    Memvalidasi apakah credential_key terdaftar, berstatus aktif,
    dan belum melewati masa berlaku (WIB).
    """
    key = (cred_key or "").strip().upper()
    if not key:
        return {
            "valid": False,
            "allowed": False,
            "status": 400,
            "reason": "MISSING_KEY",
            "message": "Credential Key wajib diisi.",
        }

    now_wib = datetime.now(WIB)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, credential_key, tier, max_domains, max_devices, is_active, expired_at
                FROM credentials
                WHERE credential_key = %s
                """,
                (key,),
            )
            cred = cur.fetchone()

            is_ok, expired_str, err_resp = _validate_credential_record(cred, now_wib)
            if not is_ok:
                return err_resp

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM credential_domains WHERE credential_id = %s",
                (cred["id"],),
            )
            used_domains = int(cur.fetchone()["cnt"])

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM credential_users WHERE credential_id = %s",
                (cred["id"],),
            )
            used_devices = int(cur.fetchone()["cnt"])

        return {
            "valid": True,
            "allowed": True,
            "status": 200,
            "credential_key": cred["credential_key"],
            "tier": cred["tier"],
            "used_domains": used_domains,
            "max_domains": int(cred["max_domains"]),
            "used_devices": used_devices,
            "max_devices": int(cred["max_devices"]),
            "expired_at": expired_str,
            "message": f"Credential Key valid (Paket: {str(cred['tier']).upper()}, Berlaku s/d: {expired_str}).",
        }
    finally:
        conn.close()

def verify_and_log_device(cred_key: str, raw_domain: str, device_id: str, city: str) -> dict:
    """
    Memvalidasi lisensi penuh (Key + Domain + Kuota PC) dan mencatat absensi harian unik WIB.
    """
    key = (cred_key or "").strip().upper()
    domain = normalize_domain(raw_domain)
    dev_id = (device_id or "").strip()
    clean_city = (city or "Unknown").strip() or "Unknown"

    if not key or not domain or not dev_id:
        return {
            "valid": False,
            "allowed": False,
            "status": 400,
            "reason": "MISSING_PARAMS",
            "message": "Credential Key, domain, dan device_id wajib diisi.",
        }

    now_wib = datetime.now(WIB)
    today_wib = now_wib.date()

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
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

            is_ok, expired_str, err_resp = _validate_credential_record(cred, now_wib)
            if not is_ok:
                conn.rollback()
                return err_resp

            # 1. Validasi strict domain binding
            cur.execute(
                """
                SELECT id FROM credential_domains
                WHERE credential_id = %s AND domain_name = %s
                """,
                (cred["id"], domain),
            )
            if not cur.fetchone():
                conn.rollback()
                return {
                    "valid": True,
                    "allowed": False,
                    "status": 403,
                    "reason": "DOMAIN_NOT_BOUND",
                    "message": f"Domain '{domain}' belum didaftarkan pada Credential Key ini.",
                }

            # 2. Cek & daftarkan perangkat unik dalam batas kuota max_devices
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM credential_users WHERE credential_id = %s",
                (cred["id"],),
            )
            used_devices = int(cur.fetchone()["cnt"])

            cur.execute(
                """
                SELECT id FROM credential_users
                WHERE credential_id = %s AND device_id = %s
                """,
                (cred["id"], dev_id),
            )
            user_row = cur.fetchone()

            if not user_row:
                if used_devices >= int(cred["max_devices"]):
                    conn.rollback()
                    return {
                        "valid": True,
                        "allowed": False,
                        "status": 403,
                        "reason": "DEVICE_QUOTA_EXCEEDED",
                        "message": f"Kuota perangkat penuh ({used_devices}/{cred['max_devices']} PC).",
                    }
                cur.execute(
                    """
                    INSERT INTO credential_users (credential_id, device_id)
                    VALUES (%s, %s)
                    """,
                    (cred["id"], dev_id),
                )
                used_devices += 1

            # 3. Catat absen harian unik WIB
            cur.execute(
                """
                INSERT INTO daily_activity_user (device_id, activity_date, city)
                VALUES (%s, %s, %s)
                ON CONFLICT (device_id, activity_date)
                DO UPDATE SET city = EXCLUDED.city
                """,
                (dev_id, today_wib, clean_city),
            )

        conn.commit()
        return {
            "valid": True,
            "allowed": True,
            "status": 200,
            "credential_key": cred["credential_key"],
            "tier": cred["tier"],
            "domain": domain,
            "used_devices": used_devices,
            "max_devices": int(cred["max_devices"]),
            "expired_at": expired_str,
            "message": "Lisensi valid dan aktivitas harian tercatat.",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()