import os
from functools import wraps
from urllib.parse import unquote
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

app.secret_key = os.environ.get("FLASK_SECRET_KEY") or "watchers-hub-secret-key-2026-kuat"
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

ADMIN_USERNAME = os.environ.get("HUB_ADMIN_USER") or "admin"
ADMIN_PASSWORD = os.environ.get("HUB_ADMIN_PASS") or "watchers123"

# =====================================================================
# DECORATOR PROTEKSI LOGIN ADMIN
# =====================================================================
def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get("hub_logged_in"):
            return redirect(url_for("login_page"))
        return view_func(*args, **kwargs)
    return wrapped_view

import traceback


# =====================================================================
# PROTEKSI ERROR HANDLER
# =====================================================================
@app.errorhandler(500)
def handle_500(e):
    return f"<pre>{traceback.format_exc()}</pre>", 500

@app.errorhandler(400)
def handle_400(e):
    return f"<pre>{traceback.format_exc()}</pre>", 400

# =====================================================================
# RUTE UTAMA & HALAMAN 1: LOGIN (/login)
# =====================================================================
@app.route("/", strict_slashes=False)
def root_redirect():
    if session.get("hub_logged_in"):
        return redirect(url_for("activity_page"))
    return redirect(url_for("login_page"))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if session.get("hub_logged_in"):
        return redirect("/activity")

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session.clear()
            session.permanent = True
            session["hub_logged_in"] = True
            session["hub_user"] = username
            return redirect("/activity")

        flash("Username atau kata sandi admin tidak sesuai.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout_action():
    session.clear()
    return redirect(url_for("login_page"))


# =====================================================================
# HALAMAN 2: DAILY ACTIVITY USER (/activity)
# =====================================================================
@app.route("/activity")
@login_required
def activity_page():
    q = request.args.get("q", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")

    activities = data.get_daily_activities(
        search_query=q,
        start_date=start_date,
        end_date=end_date,
    )
    stats = data.get_summary_stats()

    return render_template(
        "activity.html",
        active_page="activity",
        activities=activities,
        stats=stats,
        q=q,
        start_date=start_date,
        end_date=end_date,
    )


# =====================================================================
# HALAMAN 3: CREDENTIALS (/credentials)
# =====================================================================
@app.route("/credentials", methods=["GET", "POST"])
@login_required
def credentials_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            tier = request.form.get("tier", "free")
            duration = request.form.get("duration", "1m")
            max_domains = max(1, int(request.form.get("max_domains") or 1))
            max_devices = max(1, int(request.form.get("max_devices") or 50))
            res = data.create_credential(
                tier=tier,
                duration_code=duration,
                max_domains=max_domains,
                max_devices=max_devices,
            )
            if res["success"]:
                flash(
                    f"Kredensial {res['credential_key']} ({res['tier'].upper()}) berhasil dibuat — Masa aktif: {res['expired_at']}.",
                    "success",
                )

        elif action == "edit":
            cred_id = int(request.form.get("credential_id") or 0)
            tier = request.form.get("tier", "free")
            duration = request.form.get("duration", "keep")
            max_domains = max(1, int(request.form.get("max_domains") or 1))
            max_devices = max(1, int(request.form.get("max_devices") or 50))
            if data.update_credential(cred_id, tier, duration, max_domains, max_devices):
                flash("Data kredensial berhasil diperbarui.", "success")
            else:
                flash("Gagal memperbarui kredensial.", "error")

        elif action == "toggle":
            cred_id = int(request.form.get("credential_id") or 0)
            if data.toggle_credential_status(cred_id):
                flash("Status aktif kredensial berhasil diubah.", "success")

        elif action == "delete":
            cred_id = int(request.form.get("credential_id") or 0)
            if data.delete_credential(cred_id):
                flash("Kredensial beserta data domain dan perangkat terikatnya telah dihapus.", "success")

        return redirect(url_for("credentials_page"))

    q = request.args.get("q", "")
    credentials = data.get_all_credentials(search_query=q)
    stats = data.get_summary_stats()

    return render_template(
        "credentials.html",
        active_page="credentials",
        credentials=credentials,
        stats=stats,
        q=q,
    )


@app.route("/api/generate", methods=["POST"])
def api_generate():
    body = request.get_json(silent=True) or {}
    res = data.create_credential(
        tier=body.get("tier", "free"),
        duration_code=body.get("duration", "1m"),
        max_domains=int(body.get("max_domains") or 1),
        max_devices=int(body.get("max_devices") or 50),
    )
    status_code = res.pop("status", 200)
    return jsonify(res), status_code

# =====================================================================
# HALAMAN 4: CREDENTIAL DOMAINS (/domains)
# =====================================================================
@app.route("/domains")
@login_required
def domains_page():
    q = request.args.get("q", "")
    domains = data.get_all_domains(search_query=q)
    stats = data.get_summary_stats()

    return render_template(
        "credential_domains.html",
        active_page="domains",
        domains=domains,
        stats=stats,
        q=q,
    )


# =====================================================================
# HALAMAN 5: CREDENTIAL USERS (/users)
# =====================================================================
@app.route("/users")
@login_required
def users_page():
    q = request.args.get("q", "")
    cred_filter = request.args.get("credential_id", "")
    users = data.get_all_users(search_query=q, cred_filter=cred_filter)
    credentials = data.get_all_credentials()
    stats = data.get_summary_stats()

    return render_template(
        "credential_users.html",
        active_page="users",
        users=users,
        credentials=credentials,
        stats=stats,
        q=q,
        cred_filter=cred_filter,
    )


@app.route("/api/verify", methods=["POST"])
def api_verify():
    body = request.get_json(silent=True) or {}
    raw_city = request.headers.get("x-vercel-ip-city") or body.get("city") or "Unknown"
    city_name = unquote(raw_city)

    res = data.verify_and_log_device(
        cred_key=body.get("credential_key", ""),
        raw_domain=body.get("domain", ""),
        device_id=body.get("device_id", ""),
        city=city_name,
    )
    status_code = res.pop("status", 200)
    return jsonify(res), status_code

@app.route("/api/public/telemetry", methods=["GET"])
def api_public_telemetry():
    payload = data.get_public_telemetry_14d()
    response = jsonify(payload)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = "public, max-age=60"
    return response

@app.route("/api/bind-domain", methods=["POST", "OPTIONS"])
def api_bind_domain():
    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
    else:
        body = request.get_json(silent=True) or {}
        res = data.bind_domain_to_credential(
            cred_key=body.get("credential_key", ""),
            raw_domain=body.get("domain", ""),
            email=body.get("email", ""),
        )
        status_code = res.pop("status", 200)
        resp = jsonify(res)
        resp.status_code = status_code

    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp

@app.route("/api/transfer-domain", methods=["POST", "OPTIONS"])
def api_transfer_domain():
    if request.method == "OPTIONS":
        resp = jsonify({"ok": True})
    else:
        body = request.get_json(silent=True) or {}
        res = data.transfer_domain_with_email(
            cred_key=body.get("credential_key", ""),
            raw_domain=body.get("domain", ""),
            email=body.get("email", ""),
        )
        status_code = res.pop("status", 200)
        resp = jsonify(res)
        resp.status_code = status_code

    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8003, debug=True)