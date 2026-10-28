"""Instagram Login (graph.instagram.com) helpers.

Facebook Page login stays on graph.facebook.com. This module is the
Instagram Login path: authorize on instagram.com, exchange the code,
then call graph.instagram.com with the user token.
"""

import os
from urllib.parse import urlencode

import requests

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
LONG_LIVED_URL = "https://graph.instagram.com/access_token"

SCOPES = "instagram_business_basic,instagram_business_manage_insights"

PROFILE_FIELDS = ",".join([
    "user_id",
    "username",
    "name",
    "biography",
    "profile_picture_url",
    "followers_count",
    "follows_count",
    "account_type",
])

MEDIA_FIELDS = ",".join([
    "id",
    "caption",
    "timestamp",
    "permalink",
    "comments_count",
    "like_count",
    "media_product_type",
    "media_type",
    "collaborators",
])

INSIGHT_METRICS = ",".join([
    "total_interactions",
    "saved",
    "reach",
    "shares",
    "views",
    "total_views",
    "total_likes",
    "total_comments",
    "reposts",
    "reels_skip_rate",
    "crossposted_views",
    "facebook_views",
])

FALLBACK_METRICS = ",".join([
    "total_interactions",
    "saved",
    "reach",
    "shares",
    "views",
    "likes",
    "comments",
])


class InstagramError(Exception):

    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _config():
    app_id = (os.getenv("INSTAGRAM_APP_ID") or "").strip()
    app_secret = (os.getenv("INSTAGRAM_APP_SECRET") or "").strip()
    redirect_uri = (os.getenv("REDIRECT_URI") or "").strip()
    version = (os.getenv("GRAPH_VERSION") or "v26.0").strip()
    missing = [
        name for name, value in (
            ("INSTAGRAM_APP_ID", app_id),
            ("INSTAGRAM_APP_SECRET", app_secret),
            ("REDIRECT_URI", redirect_uri),
        ) if not value
    ]
    if missing:
        raise InstagramError("Missing " + ", ".join(missing))
    base = f"https://graph.instagram.com/{version}/"
    return app_id, app_secret, redirect_uri, base


def authorize_url(state):
    app_id, _, redirect_uri, _ = _config()
    query = urlencode({
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "enable_fb_login": "0",
        "force_authentication": "1",
    })
    return f"{AUTHORIZE_URL}?{query}"


def _error_message(payload, status_code):
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return error["message"]
        if payload.get("error_message"):
            return payload["error_message"]
    return f"Instagram returned HTTP {status_code}"


def _get(url, token, params=None):
    response = requests.get(
        url,
        params=params or {},
        headers={"Authorization": f"Bearer {token}"},
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
    """Short-lived code exchange, then a 60-day token."""
    app_id, app_secret, redirect_uri, _ = _config()
    code = (code or "").split("#")[0].strip()
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=45,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code != 200:
        raise InstagramError(_error_message(payload, response.status_code),
                             response.status_code, payload)

    token = payload.get("access_token")
    user_id = payload.get("user_id")
    data = payload.get("data")
    if not token and isinstance(data, list) and data:
        token = data[0].get("access_token")
        user_id = data[0].get("user_id")
    if not token:
        raise InstagramError("Token response had no access_token",
                             response.status_code, payload)

    long_lived = requests.get(
        LONG_LIVED_URL,
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": app_secret,
            "access_token": token,
        },
        timeout=45,
    )
    try:
        long_payload = long_lived.json()
    except ValueError:
        long_payload = {}
    if long_lived.status_code == 200 and long_payload.get("access_token"):
        return {
            "access_token": long_payload["access_token"],
            "user_id": str(user_id or ""),
            "expires_in": long_payload.get("expires_in"),
        }
    return {
        "access_token": token,
        "user_id": str(user_id or ""),
        "expires_in": None,
    }


def fetch_profile(token):
    _, _, _, base = _config()
    return _get(f"{base}me", token, {"fields": PROFILE_FIELDS})


def _insight_rows(payload):
    rows = []
    for item in (payload or {}).get("data") or []:
        values = item.get("values") or []
        value = values[0].get("value") if values else None
        rows.append({"name": item.get("name"), "value": value})
    return rows


def _insights(token, base, media_id, metrics):
    return _get(
        f"{base}{media_id}/insights",
        token,
        {"metric": metrics},
    )


def _media_page(token, base, user_id, after, limit):
    params = {"fields": MEDIA_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    try:
        return _get(f"{base}{user_id}/media", token, params)
    except InstagramError:
        basic = ",".join(part for part in MEDIA_FIELDS.split(",") if part != "collaborators")
        params["fields"] = basic
        return _get(f"{base}{user_id}/media", token, params)


def fetch_media(token, user_id, after=None, limit=10):
    _, _, _, base = _config()
    payload = _media_page(token, base, user_id, after, limit)
    items = []
    for media in payload.get("data") or []:
        media_id = media.get("id")
        insight_error = None
        insights = []
        if media_id:
            try:
                insights = _insight_rows(
                    _insights(token, base, media_id, INSIGHT_METRICS))
            except InstagramError as exc:
                try:
                    insights = _insight_rows(
                        _insights(token, base, media_id, FALLBACK_METRICS))
                    insight_error = exc.args[0]
                except InstagramError as fallback_exc:
                    insight_error = fallback_exc.args[0]
        media["insights"] = insights
        media["insight_error"] = insight_error
        items.append(media)
    cursors = (payload.get("paging") or {}).get("cursors") or {}
    return {
        "items": items,
        "after": cursors.get("after") if (payload.get("paging") or {}).get("next") else None,
    }
