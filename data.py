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
import html
import json
import os
import urllib.error
import urllib.request
from datetime import datetime


# --- Send Credential And OTP with Gmail (Resend) ---
def _build_watchers_email_html(
    email_type: str,
    domain: str,
    cred_key: str,
    otp_code: str = "",
    max_devices: int | None = None,
    max_domains: int | None = None,
    expires_at: str | None = None,
) -> tuple[str, str, str]:
    """Menyusun (subject, html_body, plain_text_fallback) berdesain profesional
    untuk tipe 'otp' maupun 'credential'.
    """
    safe_domain = html.escape(domain or "-")
    safe_cred = html.escape(cred_key or "-")
    safe_otp = html.escape(otp_code or "")
    current_year = datetime.now().year

    if email_type == "otp":
        subject = f"[Watchers Hub] Kode Verifikasi OTP: {otp_code}"
        badge_text = "VERIFIKASI KEAMANAN DOMAIN"
        badge_bg = "#fef3c7"
        badge_color = "#92400e"
        heading = "Konfirmasi Pemutusan & Pemindahan Domain"
        intro = (
            f"Kami menerima permintaan untuk memutus tautan lama dan memindahkan domain "
            f"<strong style='color:#0f172a;'>{safe_domain}</strong> ke Credential Key berikut:"
        )
        highlight_box = f"""
            <div style="margin:24px 0;padding:20px;background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;text-align:center;">
                <div style="font-size:11px;font-weight:700;letter-spacing:1.2px;color:#64748b;text-transform:uppercase;margin-bottom:8px;">
                    Kode Verifikasi OTP Anda
                </div>
                <div style="font-family:'Courier New',Courier,monospace;font-size:32px;font-weight:800;letter-spacing:8px;color:#0284c7;">
                    {safe_otp}
                </div>
                <div style="font-size:12px;color:#ef4444;font-weight:600;margin-top:10px;">
                    Berlaku selama 10 menit &bull; Hanya untuk 1 kali penggunaan
                </div>
            </div>
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f1f5f9;border-radius:10px;padding:14px;font-size:13px;color:#334155;">
                <tr>
                    <td style="padding:4px 0;color:#64748b;width:140px;">Domain Target</td>
                    <td style="padding:4px 0;font-weight:700;color:#0f172a;">{safe_domain}</td>
                </tr>
                <tr>
                    <td style="padding:4px 0;color:#64748b;">Credential Key</td>
                    <td style="padding:4px 0;font-family:'Courier New',Courier,monospace;font-weight:700;color:#0f172a;">{safe_cred}</td>
                </tr>
            </table>
        """
        footer_note = (
            "Jika Anda tidak merasa mengajukan pemindahan domain ini, segera abaikan email ini. "
            "Jangan pernah membagikan kode OTP kepada siapa pun."
        )
        plain_text = (
            f"Halo,\n\n"
            f"Anda meminta pemutusan tautan lama dan pemindahan domain '{domain}' ke Credential Key {cred_key}.\n\n"
            f"Kode Verifikasi OTP Anda: {otp_code}\n"
            f"Kode ini berlaku selama 10 menit dan hanya dapat digunakan satu kali.\n\n"
            f"Jika Anda tidak merasa melakukan permintaan ini, abaikan email ini.\n"
            f"— Watchers Hub Security"
        )

    elif email_type == "credential":
        subject = f"[Watchers Hub] Credential Key Lisensi Aktif — {domain or 'Watchers Lab'}"
        badge_text = "LISENSI & CREDENTIAL KEY"
        badge_bg = "#dcfce7"
        badge_color = "#166534"
        heading = "Credential Key Watchers Anda Siap Digunakan"
        intro = (
            "Terima kasih telah menggunakan <strong>Watchers</strong>. Berikut adalah "
            "<strong>Credential Key</strong> resmi untuk mengaktifkan dan menghubungkan "
            "server dashboard serta agen PC lab Anda:"
        )

        quota_row = ""
        if max_devices is not None:
            quota_row = f"""
                <tr>
                    <td style="padding:6px 0;color:#64748b;">Kuota Perangkat</td>
                    <td style="padding:6px 0;font-weight:700;color:#0f172a;">Maksimal {int(max_devices)} PC Client</td>
                </tr>
            """

        expiry_row = ""
        if expires_at:
            expiry_row = f"""
                <tr>
                    <td style="padding:6px 0;color:#64748b;">Masa Berlaku</td>
                    <td style="padding:6px 0;font-weight:700;color:#0f172a;">{html.escape(expires_at)}</td>
                </tr>
            """

        max_domains_row = ""
        if max_domain:
            max_domains_row = f"""
                <tr>
                    <td style="padding:6px 0;color:#64748b;">Kuota Domain</td>
                    <td style="padding:6px 0;font-weight:700;color:#0f172a;">Maksimal {int(max_domains)} Domain</td>
                </tr>
            """

        highlight_box = f"""
            <div style="margin:24px 0;padding:20px;background-color:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;text-align:center;">
                <div style="font-size:11px;font-weight:700;letter-spacing:1.2px;color:#15803d;text-transform:uppercase;margin-bottom:8px;">
                    Credential Key Lisensi Anda
                </div>
                <div style="font-family:'Courier New',Courier,monospace;font-size:20px;font-weight:800;letter-spacing:1.5px;color:#0f172a;word-break:break-all;background:#ffffff;padding:12px 16px;border-radius:8px;border:1px dashed #86efac;">
                    {safe_cred}
                </div>
            </div>
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px;font-size:13px;color:#334155;">
                {max_domains_row}
                {quota_row}
                {expiry_row}
                <tr>
                    <td style="padding:6px 0;color:#64748b;width:140px;">Status Lisensi</td>
                    <td style="padding:6px 0;font-weight:700;color:#16a34a;">Aktif & Siap Tautkan</td>
                </tr>
            </table>
            <div style="margin-top:20px;padding:14px 16px;background-color:#eff6ff;border-left:4px solid #0284c7;border-radius:6px;font-size:12.5px;color:#1e3a8a;line-height:1.6;">
                <strong>Langkah Aktivasi Singkat:</strong><br>
                1. Buka halaman <code>/license</code> pada dashboard server Watchers Anda.<br>
                2. Masukkan <strong>Credential Key</strong> di atas untuk menautkan domain server.<br>
                3. Konfigurasikan kunci yang sama pada aplikasi <code>WatchersAgent</code> di PC siswa.
            </div>
        """
        footer_note = (
            "Simpan Credential Key ini di tempat yang aman. Satu Credential Key hanya dapat ditautkan "
            "ke satu domain server aktif pada waktu bersamaan."
        )
        plain_text = (
            f"Halo,\n\n"
            f"Berikut adalah Credential Key lisensi Watchers Anda:\n"
            f"Credential Key: {cred_key}\n"
            f"{f'Kuota Domain: {max_domains} Domain' + chr(10) if max_domains is not None else ''}"
            f"{f'Kuota Perangkat: {max_devices} PC' + chr(10) if max_devices is not None else ''}"
            f"{f'Masa Berlaku: {expires_at}' + chr(10) if expires_at else ''}\n"
            f"Langkah Aktivasi:\n"
            f"1. Buka halaman /license pada dashboard server Watchers Anda.\n"
            f"2. Masukkan Credential Key di atas untuk menautkan domain.\n"
            f"3. Masukkan kunci yang sama pada WatchersAgent di PC siswa.\n\n"
            f"— Watchers Hub"
        )
    else:
        raise ValueError(f"Tipe email tidak didukung: {email_type}")

    html_body = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background-color:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0f172a;padding:32px 16px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background-color:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 20px 25px -5px rgba(0,0,0,0.3);">
          <!-- Header Brand -->
          <tr>
            <td style="background:linear-gradient(135deg,#020617 0%,#0f172a 100%);padding:24px 32px;border-bottom:1px solid #1e293b;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <span style="font-size:18px;font-weight:800;color:#38bdf8;letter-spacing:-0.3px;">Watchers</span>
                    <span style="font-size:18px;font-weight:400;color:#f8fafc;">Hub</span>
                  </td>
                  <td align="right">
                    <span style="display:inline-block;padding:4px 10px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:0.6px;background-color:{badge_bg};color:{badge_color};">
                      {badge_text}
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Content -->
          <tr>
            <td style="padding:32px;">
              <h1 style="margin:0 0 12px 0;font-size:20px;font-weight:700;color:#0f172a;line-height:1.3;">
                {heading}
              </h1>
              <p style="margin:0;font-size:14px;color:#475569;line-height:1.6;">
                Halo,<br><br>{intro}
              </p>

              {highlight_box}

              <p style="margin:24px 0 0 0;font-size:12.5px;color:#64748b;line-height:1.6;">
                {footer_note}
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f8fafc;padding:20px 32px;border-top:1px solid #e2e8f0;text-align:center;">
              <p style="margin:0;font-size:11.5px;color:#94a3b8;">
                &copy; {current_year} Watchers Hub &bull; Sistem Manajemen &amp; Lisensi Lab Komputer
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return subject, html_body, plain_text
def _send_watchers_email(
    to_email: str,
    email_type: str,
    cred_key: str,
    domain: str = "",
    otp_code: str = "",
    max_devices: int | None = None,
    max_domains: int | None = None,
    expires_at: str | None = None,
) -> dict:
    """Mengirimkan email HTML transaksional ('otp' atau 'credential') melalui Resend API."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_email = os.environ.get("RESEND_FROM_EMAIL", "").strip()
    from_name = os.environ.get("RESEND_FROM_NAME", "Watchers Hub").strip()

    if not api_key or not from_email:
        raise RuntimeError("Konfigurasi RESEND_API_KEY atau RESEND_FROM_EMAIL belum diatur di environment.")

    subject, html_body, plain_text = _build_watchers_email_html(
        email_type=email_type,
        domain=domain,
        cred_key=cred_key,
        otp_code=otp_code,
        max_devices=max_devices,
        max_domains = max_domains,
        expires_at=expires_at,
    )

    payload = {
        "from": f"{from_name} <{from_email}>",
        "to": [to_email.strip()],
        "subject": subject,
        "html": html_body,
        "text": plain_text,
    }

    req = urllib.request.Request(
        url="https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "WatchersHub/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode("utf-8")
            return json.loads(resp_body) if resp_body else {"ok": True}
    except urllib.error.HTTPError as e:
        err_detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Resend API gagal ({e.code}): {err_detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Gagal terhubung ke Resend API: {e.reason}") from e

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

        grouped_by_date = {}
        for row in rows:
            d_str = row["act_date"]
            grouped_by_date.setdefault(d_str, []).append({
                "city": row["city"],
                "devices": int(row["device_count"]),
            })

        daily_activity = []
        for i in range(14):
            curr_day = start_date + timedelta(days=i)
            iso_str = curr_day.isoformat()
            raw_regions = grouped_by_date.get(iso_str, [])
            total_dev = sum(r["devices"] for r in raw_regions)
            short_label = f"{curr_day.day:02d} {month_names[curr_day.month]}"

            daily_activity.append({
                "date": short_label,
                "full_date": "Hari Ini" if curr_day == today else f"{curr_day.day} {month_names[curr_day.month]} {curr_day.year}",
                "total_devices": total_dev,
                "regions": raw_regions,
            })

        return {
            "last_updated": datetime.now().strftime("%d %b %Y, %H:%M WIB"),
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
    formatted_expired_at = _format_ts(expired_at) if expired_at else "Selamanya"
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

        email_sent = True
        email_error = None
        try:
            _send_watchers_email(
                to_email=clean_email,
                email_type="credential",
                cred_key=new_key,
                max_devices=max_devices,
                max_domains=max_domains,
                expires_at=formatted_expired_at,
            )
        except Exception as mail_exc:
            email_sent = False
            email_error = str(mail_exc)

        return {
            "success": True,
            "status": 200,
            "id": cred_id,
            "credential_key": new_key,
            "email": clean_email,
            "tier": clean_tier,
            "max_domains": max_domains,
            "max_devices": max_devices,
            "expired_at": formatted_expired_at,
            "email_sent": email_sent,
            "email_error": email_error,
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

# Check Ketersediaan domain
def check_domain_status(raw_domain: str) -> dict:
    """
    Endpoint publik ringan: hanya mengecek apakah domain sudah terdaftar
    pada credential aktif (tanpa mengekspos credential_key maupun device_id).
    """
    domain = normalize_domain(raw_domain)
    if not domain:
        return {
            "bound": False,
            "status": 400,
            "message": "Parameter domain wajib diisi.",
        }

    now_wib = datetime.now(WIB)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id, c.is_active, c.expired_at
                FROM credential_domains cd
                JOIN credentials c ON c.id = cd.credential_id
                WHERE cd.domain_name = %s
                LIMIT 1
                """,
                (domain,),
            )
            cred = cur.fetchone()

            is_ok, _, _ = _validate_credential_record(cred, now_wib)
            if not is_ok:
                return {
                    "bound": False,
                    "status": 200,
                    "domain": domain,
                }

        return {
            "bound": True,
            "status": 200,
            "domain": domain,
        }
    finally:
        conn.close()

# Check ketersediaan domain dan kembalikan device_id yang terhubung dengan domain tersebut
def get_domain_device_ids(raw_domain: str) -> dict:
    """
    Endpoint khusus server: mengambil daftar device_id dari credential_users
    yang terhubung pada domain terdaftar.
    """
    domain = normalize_domain(raw_domain)
    if not domain:
        return {
            "bound": False,
            "status": 400,
            "message": "Parameter domain wajib diisi.",
            "device_ids": [],
        }

    now_wib = datetime.now(WIB)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id, c.credential_key, c.tier, c.max_devices, c.is_active, c.expired_at
                FROM credential_domains cd
                JOIN credentials c ON c.id = cd.credential_id
                WHERE cd.domain_name = %s
                LIMIT 1
                """,
                (domain,),
            )
            cred = cur.fetchone()

            is_ok, expired_str, err_resp = _validate_credential_record(cred, now_wib)
            if not is_ok:
                return {
                    "bound": False,
                    "status": 200,
                    "domain": domain,
                    "message": err_resp.get("message", "Domain belum terdaftar pada lisensi aktif."),
                    "device_ids": [],
                }

            cur.execute(
                """
                SELECT device_id
                FROM credential_users
                WHERE credential_id = %s
                ORDER BY id ASC
                """,
                (cred["id"],),
            )
            device_ids = [row["device_id"] for row in cur.fetchall() if row.get("device_id")]

        return {
            "bound": True,
            "status": 200,
            "domain": domain,
            "credential_key": cred["credential_key"],
            "tier": cred["tier"],
            "max_devices": int(cred["max_devices"]),
            "expired_at": expired_str,
            "device_ids": device_ids,
        }
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
        _send_watchers_email(
            to_email=clean_email,
            email_type="otp",
            cred_key=key,
            domain=domain,
            otp_code=otp_code,
        )
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

# Reset MAX device & Putuskan Domain
def execute_credential_domain_action(
    cred_key: str,
    raw_domain: str,
    email: str,
    otp_code: str,
    action: str,  # "reset_devices" atau "unbind_domain"
) -> dict:
    """
    Memverifikasi OTP 6 digit dari email lalu menjalankan aksi manajemen lisensi:
    - 'reset_devices': Menghapus semua device_id di credential_users untuk credential_id ini.
    - 'unbind_domain': Memutuskan tautan domain ini dari credential_domains (sekaligus reset devices).
    """
    key = (cred_key or "").strip().upper()
    domain = normalize_domain(raw_domain)
    clean_email = (email or "").strip().lower()
    clean_otp = (otp_code or "").strip()

    if action not in ("reset_devices", "unbind_domain"):
        return {"success": False, "status": 400, "message": "Aksi tidak dikenali."}
    if not key or not domain or not clean_email or not clean_otp:
        return {"success": False, "status": 400, "message": "Data verifikasi OTP tidak lengkap."}

    now_wib = datetime.now(WIB)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Pastikan domain memang tertaut pada credential_key tersebut
            cur.execute(
                """
                SELECT c.id, c.credential_key
                FROM credential_domains cd
                JOIN credentials c ON c.id = cd.credential_id
                WHERE c.credential_key = %s AND cd.domain_name = %s
                LIMIT 1
                """,
                (key, domain),
            )
            cred = cur.fetchone()
            if not cred:
                return {
                    "success": False,
                    "status": 404,
                    "message": "Kredensial dan domain tidak ditemukan atau sudah tidak tertaut.",
                }

            # 2. Verifikasi OTP 6 digit yang belum terpakai & belum kedaluwarsa
            cur.execute(
                """
                SELECT id, otp_code, expires_at
                FROM domain_transfer_otps
                WHERE credential_key = %s
                  AND domain_name = %s
                  AND email = %s
                  AND used = FALSE
                ORDER BY id DESC
                LIMIT 1
                """,
                (key, domain, clean_email),
            )
            otp_row = cur.fetchone()
            if not otp_row:
                return {
                    "success": False,
                    "status": 400,
                    "message": "Kode OTP tidak ditemukan atau sudah digunakan.",
                }

            expires_at = otp_row["expires_at"]
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=WIB)

            if now_wib > expires_at:
                return {
                    "success": False,
                    "status": 400,
                    "message": "Kode OTP sudah kedaluwarsa (melebihi 10 menit).",
                }

            if otp_row["otp_code"] != clean_otp:
                return {
                    "success": False,
                    "status": 400,
                    "message": "Kode OTP tidak cocok.",
                }

            # 3. Tandai OTP telah terpakai
            cur.execute(
                "UPDATE domain_transfer_otps SET used = TRUE WHERE id = %s",
                (otp_row["id"],),
            )

            # 4. Jalankan aksi sesuai pilihan admin
            if action == "reset_devices":
                cur.execute(
                    "DELETE FROM credential_users WHERE credential_id = %s",
                    (cred["id"],),
                )
                msg = f"Seluruh perangkat terdaftar pada {key} berhasil direset."
            else:
                cur.execute(
                    "DELETE FROM credential_users WHERE credential_id = %s",
                    (cred["id"],),
                )
                cur.execute(
                    "DELETE FROM credential_domains WHERE credential_id = %s AND domain_name = %s",
                    (cred["id"], domain),
                )
                msg = f"Tautan domain {domain} dari {key} berhasil dihapus."

        conn.commit()
        return {"success": True, "status": 200, "action": action, "message": msg}
    except Exception as e:
        conn.rollback()
        return {"success": False, "status": 500, "message": f"Gagal memproses aksi: {e}"}
    finally:
        conn.close()
