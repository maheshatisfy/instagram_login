"""Instagram API with Unified Login.

Login uses Facebook Login for Business (config id). A Unified Login
token without a Facebook Page carries the Instagram professional account
id as user_id. Data calls try graph.instagram.com, then graph.facebook.com:

    GET /v26.0/{ig-user-id}?fields=followers_count,follows_count,...
    GET /v26.0/{ig-user-id}/media?fields=...,insights.metric(...)
"""

import os
from urllib.parse import urlencode

import requests

PROFILE_FIELDS = "followers_count,follows_count,username,biography,profile_picture_url"

MEDIA_FIELDS = (
    "id,caption,timestamp,permalink,comments_count,like_count,"
    "media_product_type,media_type,collaborators,"
    "insights.metric(total_interactions,saved,reach,shares,views,total_views,"
    "total_likes,total_comments,reposts,reels_skip_rate,crossposted_views,"
    "facebook_views).fields(name,values)"
)

MEDIA_FIELDS_WITHOUT_INSIGHTS = (
    "id,caption,timestamp,permalink,comments_count,like_count,"
    "media_product_type,media_type,collaborators"
)


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
        "expires_in": long_lived.get("expires_in"),
    }


def _user_id(payload):
    """Instagram professional account id. Not the app-scoped id field."""
    if not isinstance(payload, dict):
        return None
    if payload.get("user_id"):
        return payload.get("user_id")
    data = payload.get("data")
    if isinstance(data, dict):
        return data.get("user_id")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("user_id"):
                return item.get("user_id")
    return None


def instagram_account_ids(token):
    """Instagram professional account ids granted on this unified-login token.

    Page-linked logins expose the id on a Page or on a scope target.
    Unified Login without a Page exposes it as user_id on /me.
    """
    app_id, app_secret, _, _, base = _config()
    version = (os.getenv("GRAPH_VERSION") or "v26.0").strip()
    found = []

    def add(value):
        text = str(value or "").strip()
        if text and text not in found:
            found.append(text)

    debug = _request(
        "GET",
        f"{base}debug_token",
        token=f"{app_id}|{app_secret}",
        params={"input_token": token},
    )
    debug_data = debug.get("data") or {}
    scopes = debug_data.get("granular_scopes") or []
    for scope in scopes:
        for target in scope.get("target_ids") or []:
            add(target)

    for url in (
        f"https://graph.instagram.com/{version}/me",
        f"{base}me",
    ):
        try:
            me = _request(
                "GET",
                url,
                token,
                params={"fields": "user_id,username"},
            )
        except InstagramError:
            continue
        add(_user_id(me))

    if not found and any(
            str(scope.get("scope") or "").startswith("instagram_business_")
            for scope in scopes):
        add(debug_data.get("user_id"))

    try:
        pages = _request(
            "GET",
            f"{base}me/accounts",
            token,
            params={"fields": "instagram_business_account{id,username}"},
        )
        for page in pages.get("data") or []:
            account = page.get("instagram_business_account") or {}
            add(account.get("id"))
    except InstagramError:
        pass
    return found


def _get_user_node(token, path, params):
    """Unified Login tokens are served by graph.instagram.com. Page-linked tokens stay on graph.facebook.com."""
    _, _, _, _, facebook = _config()
    version = (os.getenv("GRAPH_VERSION") or "v26.0").strip()
    last_error = None
    for base in (f"https://graph.instagram.com/{version}/", facebook):
        try:
            return _request("GET", f"{base}{path}", token, params=params)
        except InstagramError as exc:
            last_error = exc
    raise last_error


def fetch_profile(token, instagram_id):
    profile = _get_user_node(
        token,
        instagram_id,
        {"fields": PROFILE_FIELDS},
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
    params = {"fields": MEDIA_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    insight_error = None
    try:
        payload = _get_user_node(token, f"{instagram_id}/media", params)
    except InstagramError as exc:
        insight_error = exc.args[0]
        params["fields"] = MEDIA_FIELDS_WITHOUT_INSIGHTS
        payload = _get_user_node(token, f"{instagram_id}/media", params)
    items = []
    for media in payload.get("data") or []:
        media["insights"] = _insight_rows(media.get("insights"))
        media["insight_error"] = insight_error
        items.append(media)
    paging = payload.get("paging") or {}
    cursors = paging.get("cursors") or {}
    return {
        "items": items,
        "after": cursors.get("after") if paging.get("next") else None,
    }
