import secrets
from datetime import datetime, date

# =====================================================================
# DATA DUMMY 4 TABEL UTAMA (NANTI DIGANTI QUERY NEON POSTGRESQL)
# =====================================================================
CREDENTIALS = [
    {
        "id": 1,
        "credential_key": "WCH-8F92-41BC-990A",
        "max_domains": 1,
        "max_devices": 50,
        "is_active": True,
        "created_at": "2026-11-10 08:15:00",
    },
    {
        "id": 2,
        "credential_key": "WCH-3D19-77EA-204F",
        "max_domains": 1,
        "max_devices": 50,
        "is_active": True,
        "created_at": "2026-11-14 13:40:22",
    },
    {
        "id": 3,
        "credential_key": "WCH-99A1-00BC-512E",
        "max_domains": 1,
        "max_devices": 50,
        "is_active": False,
        "created_at": "2026-11-01 09:00:11",
    },
]

CREDENTIAL_DOMAINS = [
    {"id": 1, "credential_id": 1, "domain_name": "lab.petikjombang.ac.id", "created_at": "2026-11-10 08:15:00"},
    {"id": 2, "credential_id": 2, "domain_name": "monitoring.smkn1kediri.sch.id", "created_at": "2026-11-14 13:40:22"},
    {"id": 3, "credential_id": 3, "domain_name": "lab-rpl.example.id", "created_at": "2026-11-01 09:00:11"},
]

CREDENTIAL_USERS = [
    {"id": 1, "credential_id": 1, "device_id": "1dda30e4-503c-430b-92ce-261979af1657", "created_at": "2026-11-10 08:20:10"},
    {"id": 2, "credential_id": 1, "device_id": "8b21f90c-112a-498d-81aa-9012bc441102", "created_at": "2026-11-10 08:21:05"},
    {"id": 3, "credential_id": 1, "device_id": "c4410e9a-773b-4c01-b519-3301de882910", "created_at": "2026-11-11 07:30:44"},
    {"id": 4, "credential_id": 2, "device_id": "f9012a11-882c-411e-9001-7712aa901234", "created_at": "2026-11-14 14:02:18"},
]

_today = date.today().isoformat()
DAILY_ACTIVITY_USER = [
    {"id": 1, "device_id": "1dda30e4-503c-430b-92ce-261979af1657", "activity_date": _today, "city": "Jombang", "created_at": f"{_today} 07:15:12"},
    {"id": 2, "device_id": "8b21f90c-112a-498d-81aa-9012bc441102", "activity_date": _today, "city": "Jombang", "created_at": f"{_today} 07:16:04"},
    {"id": 3, "device_id": "c4410e9a-773b-4c01-b519-3301de882910", "activity_date": _today, "city": "Surabaya", "created_at": f"{_today} 08:02:51"},
    {"id": 4, "device_id": "f9012a11-882c-411e-9001-7712aa901234", "activity_date": _today, "city": "Kediri", "created_at": f"{_today} 08:11:30"},
]


def normalize_domain(raw_domain: str) -> str:
    d = (raw_domain or "").strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.split("/")[0].strip()


# =====================================================================
# FUNGSI PEMROSESAN UNTUK HALAMAN DASBOR
# =====================================================================
def get_summary_stats() -> dict:
    today_str = date.today().isoformat()
    return {
        "total_credentials": len(CREDENTIALS),
        "active_credentials": sum(1 for c in CREDENTIALS if c["is_active"]),
        "total_domains": len(CREDENTIAL_DOMAINS),
        "total_users": len(CREDENTIAL_USERS),
        "today_active_devices": sum(1 for a in DAILY_ACTIVITY_USER if a["activity_date"] == today_str),
    }


def get_daily_activities(search_query: str = "", filter_date: str = "") -> list:
    q = search_query.strip().lower()
    results = []
    for item in reversed(DAILY_ACTIVITY_USER):
        if filter_date and item["activity_date"] != filter_date:
            continue
        if q and q not in item["device_id"].lower() and q not in (item["city"] or "").lower():
            continue
        results.append(item)
    return results


def get_all_credentials(search_query: str = "") -> list:
    q = search_query.strip().lower()
    enriched = []
    for cred in reversed(CREDENTIALS):
        domains = [d["domain_name"] for d in CREDENTIAL_DOMAINS if d["credential_id"] == cred["id"]]
        used_devices = sum(1 for u in CREDENTIAL_USERS if u["credential_id"] == cred["id"])

        if q:
            match_key = q in cred["credential_key"].lower()
            match_dom = any(q in d.lower() for d in domains)
            if not (match_key or match_dom):
                continue

        enriched.append({
            **cred,
            "domains": domains,
            "used_devices": used_devices,
        })
    return enriched


def toggle_credential_status(cred_id: int) -> bool:
    for cred in CREDENTIALS:
        if cred["id"] == cred_id:
            cred["is_active"] = not cred["is_active"]
            return True
    return False


def get_all_domains(search_query: str = "") -> list:
    q = search_query.strip().lower()
    cred_map = {c["id"]: c["credential_key"] for c in CREDENTIALS}
    results = []
    for dom in reversed(CREDENTIAL_DOMAINS):
        cred_key = cred_map.get(dom["credential_id"], "-")
        if q and q not in dom["domain_name"].lower() and q not in cred_key.lower():
            continue
        results.append({
            **dom,
            "credential_key": cred_key,
        })
    return results


def get_all_users(search_query: str = "", cred_filter: str = "") -> list:
    q = search_query.strip().lower()
    cred_map = {c["id"]: c["credential_key"] for c in CREDENTIALS}
    results = []
    for usr in reversed(CREDENTIAL_USERS):
        cred_key = cred_map.get(usr["credential_id"], "-")
        if cred_filter and str(usr["credential_id"]) != str(cred_filter):
            continue
        if q and q not in usr["device_id"].lower() and q not in cred_key.lower():
            continue
        results.append({
            **usr,
            "credential_key": cred_key,
        })
    return results


# =====================================================================
# FUNGSI PEMROSESAN UNTUK API (/api/generate & /api/verify)
# =====================================================================
def create_credential_for_domain(raw_domain: str, max_domains: int = 1, max_devices: int = 50) -> dict:
    domain = normalize_domain(raw_domain)
    if not domain or "." not in domain:
        return {"success": False, "status": 400, "message": "Nama domain atau IP server tidak valid."}

    existing = next((d for d in CREDENTIAL_DOMAINS if d["domain_name"] == domain), None)
    if existing:
        return {
            "success": False,
            "status": 409,
            "message": f"Domain '{domain}' sudah terdaftar. Satu domain hanya berhak atas 1 kredensial.",
        }

    new_id = max([c["id"] for c in CREDENTIALS], default=0) + 1
    new_key = f"WCH-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    CREDENTIALS.append({
        "id": new_id,
        "credential_key": new_key,
        "max_domains": max_domains,
        "max_devices": max_devices,
        "is_active": True,
        "created_at": now_str,
    })

    CREDENTIAL_DOMAINS.append({
        "id": max([d["id"] for d in CREDENTIAL_DOMAINS], default=0) + 1,
        "credential_id": new_id,
        "domain_name": domain,
        "created_at": now_str,
    })

    return {
        "success": True,
        "status": 200,
        "credential_key": new_key,
        "domain": domain,
        "max_devices": max_devices,
    }


def verify_and_log_device(cred_key: str, raw_domain: str, device_id: str, city: str) -> dict:
    key = (cred_key or "").strip().upper()
    domain = normalize_domain(raw_domain)
    dev_id = (device_id or "").strip()

    if not key or not domain or not dev_id:
        return {"allowed": False, "status": 400, "reason": "MISSING_PARAMETERS"}

    cred = next((c for c in CREDENTIALS if c["credential_key"] == key), None)
    if not cred or not cred["is_active"]:
        return {"allowed": False, "status": 403, "reason": "INVALID_OR_INACTIVE_CREDENTIAL"}

    bound_domains = [d["domain_name"] for d in CREDENTIAL_DOMAINS if d["credential_id"] == cred["id"]]
    if domain not in bound_domains:
        return {"allowed": False, "status": 403, "reason": "DOMAIN_MISMATCH"}

    registered_devices = [u["device_id"] for u in CREDENTIAL_USERS if u["credential_id"] == cred["id"]]
    if dev_id not in registered_devices:
        if len(registered_devices) >= cred["max_devices"]:
            return {
                "allowed": False,
                "status": 403,
                "reason": "DEVICE_QUOTA_EXCEEDED",
                "used": len(registered_devices),
                "max": cred["max_devices"],
            }

        CREDENTIAL_USERS.append({
            "id": max([u["id"] for u in CREDENTIAL_USERS], default=0) + 1,
            "credential_id": cred["id"],
            "device_id": dev_id,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        registered_devices.append(dev_id)

    today_str = date.today().isoformat()
    already_logged = any(
        a["device_id"] == dev_id and a["activity_date"] == today_str
        for a in DAILY_ACTIVITY_USER
    )
    if not already_logged:
        DAILY_ACTIVITY_USER.append({
            "id": max([a["id"] for a in DAILY_ACTIVITY_USER], default=0) + 1,
            "device_id": dev_id,
            "activity_date": today_str,
            "city": city or "Unknown",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    return {
        "allowed": True,
        "status": 200,
        "used_devices": len(registered_devices),
        "max_devices": cred["max_devices"],
        "city": city,
    }