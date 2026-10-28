# Instagram API with Unified Login

Small Flask app for Instagram API with Unified Login. Login is Facebook Login for Business (`config_id`). Profile and media are read from `graph.facebook.com/v26.0/{instagram-user-id}`, including media insights in the same request.

Do not commit `.env`. Do not paste access tokens into source files.

## Meta app setup

1. Use a Business Meta app with **Facebook Login for Business** and a login configuration whose token type can access the Instagram professional account (Unified Login). Copy that configuration id into `FACEBOOK_LOGIN_CONFIG_ID`.
2. The configuration needs `instagram_basic` and `instagram_manage_insights`.
3. Add this redirect URI, exactly as `REDIRECT_URI` in `.env`, under Facebook Login for Business → Settings → Valid OAuth Redirect URIs:

   `https://YOUR_USERNAME.pythonanywhere.com/instagram/callback`

## PythonAnywhere

1. Upload this folder to `/home/YOUR_USERNAME/instagram_login`.
2. Open a Bash console and install dependencies:

   ```bash
   cd ~/instagram_login
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in `META_APP_ID`, `META_APP_SECRET`, `FACEBOOK_LOGIN_CONFIG_ID`, `REDIRECT_URI`, and a long `SECRET_KEY`. Set `COOKIE_SECURE=1`.
4. Web tab → Add a new web app → Manual configuration → Python 3.10 (or the version you used for the virtualenv).
5. Virtualenv path: `/home/YOUR_USERNAME/instagram_login/venv`
6. WSGI configuration file, replace the file contents with:

   ```python
   import sys
   path = "/home/YOUR_USERNAME/instagram_login"
   if path not in sys.path:
       sys.path.insert(0, path)
   from wsgi import application
   ```

7. Reload the web app and open the site.

## Local check

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
flask --app app run --debug --cert=adhoc
```

Open `https://lvh.me:5000` and accept the browser certificate warning. `lvh.me` points at this machine, and Facebook App Domains accepts it. A raw IP such as `127.0.0.1` cannot be added there.

In the Meta app:

- Settings → Basic → App Domains: `lvh.me`
- Facebook Login for Business → Settings → Valid OAuth Redirect URIs: `https://lvh.me:5000/instagram/callback`

`REDIRECT_URI` must be that same https address, and `COOKIE_SECURE=1`. Facebook rejects an `http://` redirect with “isn't using a secure connection”.
