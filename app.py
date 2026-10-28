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

from instagram_api import (
    InstagramError,
    authorize_url,
    exchange_code,
    fetch_media,
    fetch_profile,
    instagram_account_ids,
)

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
    ig_id = session.get("ig_id")
    accounts = session.get("ig_accounts") or []
    if not ig_id:
        if len(accounts) > 1:
            return render_template("accounts.html", accounts=accounts)
        if len(accounts) == 1:
            ig_id = accounts[0]
            session["ig_id"] = ig_id
        else:
            flash("Login finished, but the token has no Instagram account id.")
            return render_template("login.html")
    try:
        profile = fetch_profile(_token(), ig_id)
    except InstagramError as exc:
        flash(str(exc))
        return render_template("login.html")
    after = (request.args.get("after") or "").strip() or None
    media = {"items": [], "after": None}
    media_error = None
    try:
        media = fetch_media(_token(), ig_id, after=after)
    except InstagramError as exc:
        media_error = str(exc)
    return render_template(
        "dashboard.html",
        profile=profile,
        media=media["items"],
        next_after=media["after"],
        media_error=media_error,
    )


@app.post("/account")
def choose_account():
    chosen = (request.form.get("ig_id") or "").strip()
    allowed = session.get("ig_accounts") or []
    if chosen not in allowed:
        flash("Choose one of the Instagram accounts on this login.")
        return redirect(url_for("home"))
    session["ig_id"] = chosen
    return redirect(url_for("home"))


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
        flash("Meta did not return a code.")
        return redirect(url_for("home"))
    try:
        token = exchange_code(code)
    except InstagramError as exc:
        flash(str(exc))
        return redirect(url_for("home"))
    accounts = []
    lookup_error = None
    chosen_token = token["access_token"]
    tried = set()
    for candidate in (token["access_token"], token.get("short_token")):
        if not candidate or candidate in tried:
            continue
        tried.add(candidate)
        try:
            accounts = instagram_account_ids(candidate)
            chosen_token = candidate
            break
        except InstagramError as exc:
            lookup_error = exc
    if not accounts and token.get("user_id"):
        accounts = [str(token["user_id"])]
        chosen_token = token.get("short_token") or token["access_token"]
    if not accounts:
        flash(str(lookup_error or "Login finished, but the token has no Instagram account id."))
        return redirect(url_for("home"))
    session["access_token"] = chosen_token
    session["ig_accounts"] = accounts
    session["ig_id"] = accounts[0] if len(accounts) == 1 else ""
    session.pop("oauth_state", None)
    return redirect(url_for("home"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))
