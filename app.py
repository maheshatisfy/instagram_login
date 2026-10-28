import os
import secrets

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from instagram_api import InstagramError, authorize_url, exchange_code, fetch_media, fetch_profile

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or "dev-only-change-me"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("COOKIE_SECURE", "0") == "1"


def _token():
    return session.get("access_token")


@app.get("/")
def home():
    if not _token():
        return render_template("login.html")
    try:
        profile = fetch_profile(_token())
    except InstagramError as exc:
        flash(str(exc))
        return render_template("login.html")
    user_id = str(profile.get("user_id") or profile.get("id") or session.get("user_id") or "")
    session["user_id"] = user_id
    after = (request.args.get("after") or "").strip() or None
    media = {"items": [], "after": None}
    media_error = None
    if user_id:
        try:
            media = fetch_media(_token(), user_id, after=after)
        except InstagramError as exc:
            media_error = str(exc)
    return render_template(
        "dashboard.html",
        profile=profile,
        media=media["items"],
        next_after=media["after"],
        media_error=media_error,
    )


@app.get("/instagram/login")
def instagram_login():
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    try:
        return redirect(authorize_url(state))
    except InstagramError as exc:
        flash(str(exc))
        return redirect(url_for("home"))


@app.get("/instagram/callback")
def instagram_callback():
    error = request.args.get("error_description") or request.args.get("error")
    if error:
        flash(error)
        return redirect(url_for("home"))
    state = request.args.get("state")
    if not state or state != session.get("oauth_state"):
        flash("Login state did not match. Start the login again.")
        return redirect(url_for("home"))
    code = request.args.get("code")
    if not code:
        flash("Instagram did not return a code.")
        return redirect(url_for("home"))
    try:
        token = exchange_code(code)
    except InstagramError as exc:
        flash(str(exc))
        return redirect(url_for("home"))
    session["access_token"] = token["access_token"]
    session["user_id"] = token.get("user_id") or ""
    session.pop("oauth_state", None)
    return redirect(url_for("home"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))
