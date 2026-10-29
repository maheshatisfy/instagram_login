import os
import secrets
from datetime import timedelta

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
    client_business_id,
    exchange_code,
    fetch_media,
    fetch_profile,
    instagram_account_ids,
)
import token_store

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or "dev-only-change-me"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("COOKIE_SECURE", "0") == "1"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=60)


def _open_account():
    ig_id = session.get("ig_id")
    if not ig_id:
        return None
    return token_store.get_account(ig_id)


def _refresh_account(account, after=None):
    token = account["access_token"]
    ig_id = account["ig_id"]
    profile = fetch_profile(token, ig_id)
    media = {"items": [], "after": None}
    media_error = None
    try:
        media = fetch_media(token, ig_id, after=after)
    except InstagramError as exc:
        media_error = str(exc)
    token_store.save_snapshot(
        ig_id,
        profile,
        media["items"],
        media["after"],
        media_error,
    )
    saved = token_store.get_account(ig_id)
    return saved


def _boards():
    boards = token_store.list_boards()
    changed = False
    for account in boards:
        if account.get("profile") and account.get("media") is not None:
            continue
        try:
            _refresh_account(account)
            changed = True
        except InstagramError as exc:
            flash("@{}: {}".format(account.get("username") or account["ig_id"], exc))
    if changed:
        boards = token_store.list_boards()
    return boards


@app.get("/")
def home():
    session.permanent = True
    pending = session.get("pending_accounts") or []
    if len(pending) > 1 and not session.get("ig_id"):
        return render_template("accounts.html", accounts=pending)
    boards = _boards()
    if not boards:
        return render_template("login.html", saved=token_store.list_accounts())
    return render_template("board.html", boards=boards)


@app.post("/continue")
def continue_account():
    ig_id = (request.form.get("ig_id") or "").strip()
    if not token_store.get_account(ig_id):
        flash("That saved login is no longer on this server.")
        return redirect(url_for("home"))
    session.permanent = True
    session["ig_id"] = ig_id
    session.pop("pending_accounts", None)
    return redirect(url_for("home"))


@app.post("/account")
def choose_account():
    chosen = (request.form.get("ig_id") or "").strip()
    allowed = {item["id"] for item in (session.get("pending_accounts") or [])}
    if chosen not in allowed or not token_store.get_account(chosen):
        flash("Choose one of the Instagram accounts on this login.")
        return redirect(url_for("home"))
    session.permanent = True
    session["ig_id"] = chosen
    session.pop("pending_accounts", None)
    return redirect(url_for("home"))


@app.post("/media/refresh")
def refresh_media():
    ig_id = (request.form.get("ig_id") or session.get("ig_id") or "").strip()
    account = token_store.get_account(ig_id)
    if not account:
        return redirect(url_for("home"))
    after = (request.form.get("after") or "").strip() or None
    try:
        _refresh_account(account, after=after)
    except InstagramError as exc:
        flash(str(exc))
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
    for candidate in (token.get("short_token"), token["access_token"]):
        if not candidate or candidate in tried:
            continue
        tried.add(candidate)
        try:
            accounts = instagram_account_ids(candidate)
            chosen_token = candidate
            break
        except InstagramError as exc:
            lookup_error = exc
    if not accounts:
        flash(str(lookup_error or "Login finished, but the token has no Instagram account id."))
        return redirect(url_for("home"))
    token_store.save_login(
        accounts,
        chosen_token,
        client_business_id(chosen_token),
    )
    session.permanent = True
    session.pop("oauth_state", None)
    session.pop("pending_accounts", None)
    if len(accounts) == 1:
        session["ig_id"] = accounts[0]["id"]
    else:
        session.pop("ig_id", None)
        names = ", ".join("@" + (a.get("username") or a["id"]) for a in accounts)
        flash("Connected {} accounts: {}.".format(len(accounts), names), "success")
    return redirect(url_for("home"))


@app.post("/logout")
def logout():
    session.pop("ig_id", None)
    session.pop("pending_accounts", None)
    return redirect(url_for("home"))


@app.post("/forget")
def forget():
    ig_id = (request.form.get("ig_id") or session.get("ig_id") or "").strip()
    if ig_id:
        token_store.delete_account(ig_id)
    if session.get("ig_id") == ig_id:
        session.pop("ig_id", None)
    return redirect(url_for("home"))
