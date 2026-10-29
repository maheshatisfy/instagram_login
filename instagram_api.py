"""Instagram API with Unified Login.

Login uses Facebook Login for Business (config id). Every data call
uses https://graph.facebook.com/v26.0/. /me is the business integration
system user, not the Instagram account. Account ids come from
/me/assigned_instagram_accounts.

    GET /v26.0/{ig-user-id}?fields=followers_count,follows_count,...
    GET /v26.0/{ig-user-id}/media?fields=...,insights.metric(...)
"""

import copy
import os
from urllib.parse import urlencode

import requests

PROFILE_FIELDS = "followers_count,follows_count,username,biography,profile_picture_url"

MEDIA_FIELDS = (
    "id,caption,timestamp,permalink,media_url,thumbnail_url,comments_count,like_count,"
    "media_product_type,media_type,collaborators,"
    "insights.metric(total_interactions,saved,reach,shares,views,total_views,"
    "total_likes,total_comments,reposts,reels_skip_rate,crossposted_views,"
    "facebook_views).fields(name,values)"
)

MEDIA_FIELDS_WITHOUT_INSIGHTS = (
    "id,caption,timestamp,permalink,media_url,thumbnail_url,comments_count,like_count,"
    "media_product_type,media_type,collaborators"
)

INSTAGRAM_SCOPES = {
    "instagram_basic",
    "instagram_manage_comments",
    "instagram_manage_insights",
    "instagram_content_publish",
    "instagram_manage_messages",
    "instagram_manage_events",
}


class InstagramError(Exception):

    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _config():
    app_id = (os.getenv("META_APP_ID") or os.getenv("INSTAGRAM_APP_ID") or "").strip()
    app_secret = (os.getenv("META_APP_SECRET") or os.getenv("INSTAGRAM_APP_SECRET") or "").strip()
    redirect_uri = (os.getenv("REDIRECT_URI") or "").strip()
    config_id = (os.getenv("FACEBOOK_LOGIN_CONFIG_ID") or "").strip()
    version = (os.getenv("GRAPH_VERSION") or "v26.0").strip()
    missing = [
        name for name, value in (
            ("META_APP_ID", app_id),
            ("META_APP_SECRET", app_secret),
            ("REDIRECT_URI", redirect_uri),
            ("FACEBOOK_LOGIN_CONFIG_ID", config_id),
        ) if not value
    ]
    if missing:
        raise InstagramError("Missing " + ", ".join(missing))
    if not redirect_uri.lower().startswith("https://"):
        raise InstagramError(
            "REDIRECT_URI must start with https://. Facebook blocks this app on http."
        )
    return app_id, app_secret, redirect_uri, config_id, f"https://graph.facebook.com/{version}/"


def authorize_url(state):
    app_id, _, redirect_uri, config_id, _ = _config()
    version = (os.getenv("GRAPH_VERSION") or "v26.0").strip()
    query = urlencode({
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "override_default_response_type": "true",
        "config_id": config_id,
        "prompt": "login",
    })
    return f"https://www.facebook.com/{version}/dialog/oauth?{query}"


def _error_message(payload, status_code):
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return error["message"]
        if payload.get("error_message"):
            return str(payload["error_message"])
    return f"Graph API returned HTTP {status_code}"


def _request(method, url, token, params=None, data=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.request(
        method,
        url,
        params=params or {},
        data=data,
        headers=headers,
        timeout=45,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:500]}
    if response.status_code != 200:
        raise InstagramError(_error_message(payload, response.status_code),
                             response.status_code, payload)
    return payload


def exchange_code(code):
    """Authorization code to a long-lived Facebook user or system-user token."""
    app_id, app_secret, redirect_uri, _, base = _config()
    code = (code or "").split("#")[0].strip()
    short = _request(
        "GET",
        f"{base}oauth/access_token",
        token="",
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )
    token = short.get("access_token")
    if not token:
        raise InstagramError("Token response had no access_token", payload=short)
    try:
        long_lived = _request(
            "GET",
            f"{base}oauth/access_token",
            token="",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": token,
            },
        )
    except InstagramError:
        long_lived = short
    return {
        "access_token": long_lived.get("access_token") or token,
        "short_token": token,
        "expires_in": long_lived.get("expires_in"),
    }


def _paged(token, url, params):
    rows = []
    while url:
        payload = _request("GET", url, token, params=params)
        rows.extend(payload.get("data") or [])
        url = ((payload.get("paging") or {}).get("next"))
        params = None
    return rows


def _remember(found, account_id, username=""):
    account_id = str(account_id or "").strip()
    if not account_id or account_id in {item["id"] for item in found}:
        return
    found.append({"id": account_id, "username": username or ""})


def _assigned_accounts(token):
    _, _, _, _, base = _config()
    found = []
    try:
        rows = _paged(
            token,
            f"{base}me/assigned_instagram_accounts",
            {"fields": "id,username", "limit": 100},
        )
    except InstagramError:
        return found
    for account in rows:
        if isinstance(account, dict):
            _remember(found, account.get("id"), account.get("username") or "")
    return found


def _debug_token(token):
    app_id, app_secret, _, _, base = _config()
    try:
        payload = _request(
            "GET",
            f"{base}debug_token",
            token="",
            params={
                "input_token": token,
                "access_token": f"{app_id}|{app_secret}",
            },
        )
    except InstagramError:
        return {}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def _readable_instagram_account(token, account_id, username=""):
    """Confirm a candidate id is an Instagram professional account on graph.facebook.com."""
    _, _, _, _, base = _config()
    try:
        profile = _request(
            "GET",
            f"{base}{account_id}",
            token,
            params={"fields": "id,username"},
        )
    except InstagramError:
        return None
    if not profile.get("username") and not username:
        return None
    return {
        "id": str(profile.get("id") or account_id),
        "username": profile.get("username") or username or "",
    }


def _accounts_from_token_targets(token, debug):
    """Instagram ids Meta stored on the token when the assigned-accounts edge is empty."""
    _, _, _, _, base = _config()
    found = []
    seen = []
    for item in debug.get("granular_scopes") or []:
        if not isinstance(item, dict) or item.get("scope") not in INSTAGRAM_SCOPES:
            continue
        for target in item.get("target_ids") or []:
            target = str(target).strip()
            if target and target not in seen:
                seen.append(target)
    for account_id in seen:
        account = _readable_instagram_account(token, account_id)
        if account:
            _remember(found, account["id"], account["username"])
    if found:
        return found
    business_id = None
    try:
        me = _request(
            "GET",
            f"{base}me",
            token,
            params={"fields": "client_business_id"},
        )
        business_id = me.get("client_business_id")
    except InstagramError:
        business_id = None
    if not business_id:
        return found
    for edge in ("owned_instagram_assets", "client_instagram_assets"):
        try:
            rows = _paged(
                token,
                f"{base}{business_id}/{edge}",
                {"fields": "id,username", "limit": 100},
            )
        except InstagramError:
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            account = _readable_instagram_account(
                token,
                row.get("id"),
                row.get("username") or "",
            )
            if account:
                _remember(found, account["id"], account["username"])
    return found


def instagram_account_ids(token):
    """Instagram professional account ids shared with this Unified Login token.

    /me is the business integration system user and has no user_id.
    https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/get-started
    """
    found = _assigned_accounts(token)
    debug = {}
    if not found:
        debug = _debug_token(token)
        found = _accounts_from_token_targets(token, debug)
    if found:
        return found
    if not debug:
        debug = _debug_token(token)
    scopes = debug.get("scopes") or []
    scope_text = ", ".join(str(scope) for scope in scopes) if scopes else "none"
    target_count = 0
    for item in debug.get("granular_scopes") or []:
        if isinstance(item, dict) and item.get("scope") in INSTAGRAM_SCOPES:
            target_count += len(item.get("target_ids") or [])
    raise InstagramError(
        "Login finished, but no Instagram professional account was shared. "
        f"Scopes: {scope_text}. Instagram accounts on the token: {target_count}. "
        "In the Meta dialog, open the account switcher, log in with Instagram, "
        "select the business portfolio, select the Instagram professional account, and confirm."
    )


def client_business_id(token):
    """Business id stored with the token so it can be reused later."""
    _, _, _, _, base = _config()
    try:
        me = _request(
            "GET",
            f"{base}me",
            token,
            params={"fields": "client_business_id"},
        )
    except InstagramError:
        return None
    return me.get("client_business_id")


def fetch_profile(token, instagram_id):
    _, _, _, _, base = _config()
    profile = _request(
        "GET",
        f"{base}{instagram_id}",
        token,
        params={"fields": PROFILE_FIELDS},
    )
    profile["id"] = str(profile.get("user_id") or profile.get("id") or instagram_id)
    return profile


def _insight_rows(insights):
    rows = []
    for item in (insights or {}).get("data") or []:
        values = item.get("values") or []
        value = values[0].get("value") if values else None
        rows.append({"name": item.get("name"), "value": value})
    return rows


def fetch_media(token, instagram_id, after=None, limit=10):
    _, _, _, _, base = _config()
    params = {"fields": MEDIA_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    insight_error = None
    try:
        payload = _request("GET", f"{base}{instagram_id}/media", token, params=params)
    except InstagramError as exc:
        insight_error = exc.args[0]
        params["fields"] = MEDIA_FIELDS_WITHOUT_INSIGHTS
        payload = _request("GET", f"{base}{instagram_id}/media", token, params=params)
    items = []
    for media in payload.get("data") or []:
        raw = copy.deepcopy(media)
        media["raw"] = raw
        media["insights"] = _insight_rows(raw.get("insights"))
        media["insight_error"] = insight_error
        items.append(media)
    paging = payload.get("paging") or {}
    cursors = paging.get("cursors") or {}
    return {
        "items": items,
        "after": cursors.get("after") if paging.get("next") else None,
    }
