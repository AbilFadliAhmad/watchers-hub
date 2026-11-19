import os
from functools import wraps
from urllib.parse import unquote
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "watchers-hub-dev-secret-key-2026")
ADMIN_USERNAME = os.environ.get("HUB_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("HUB_ADMIN_PASS", "watchers123")

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
        return redirect(url_for("activity_page"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["hub_logged_in"] = True
            session["hub_user"] = username
            return redirect(url_for("activity_page"))

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
    filter_date = request.args.get("date", "")
    activities = data.get_daily_activities(search_query=q, filter_date=filter_date)
    stats = data.get_summary_stats()

    return render_template(
        "activity.html",
        active_page="activity",
        activities=activities,
        stats=stats,
        q=q,
        filter_date=filter_date,
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
            domain = request.form.get("domain", "")
            max_devices = int(request.form.get("max_devices") or 50)
            res = data.create_credential_for_domain(raw_domain=domain, max_devices=max_devices)
            if res["success"]:
                flash(f"Kredensial {res['credential_key']} berhasil dibuat untuk {res['domain']}.", "success")
            else:
                flash(res["message"], "error")

        elif action == "toggle":
            cred_id = int(request.form.get("credential_id") or 0)
            if data.toggle_credential_status(cred_id):
                flash("Status kredensial berhasil diperbarui.", "success")

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


# =====================================================================
# ENDPOINT API PUBLIK (UNTUK LANDING PAGE & WATCHERS SERVER CLIENT)
# =====================================================================
@app.route("/api/generate", methods=["POST"])
def api_generate():
    body = request.get_json(silent=True) or {}
    res = data.create_credential_for_domain(raw_domain=body.get("domain", ""))
    status_code = res.pop("status", 200)
    return jsonify(res), status_code


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)