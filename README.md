# Instagram Login viewer

Small Flask app for the Instagram Login flow (`graph.instagram.com`). After login it shows the profile and a page of media with insights. It is meant to run on PythonAnywhere.

Do not commit `.env`. Do not paste access tokens into source files.

## Meta app setup

1. In the Meta app, add the Instagram product and use **Instagram Login** (not Facebook Login).
2. Add this redirect URI, exactly as `REDIRECT_URI` in `.env`:

   `https://YOUR_USERNAME.pythonanywhere.com/instagram/callback`

3. The Instagram account must be a professional account. The login asks for `instagram_business_basic` and `instagram_business_manage_insights`.

## PythonAnywhere

1. Upload this folder to `/home/YOUR_USERNAME/instagram_login`.
2. Open a Bash console and install dependencies:

   ```bash
   cd ~/instagram_login
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `REDIRECT_URI`, and a long `SECRET_KEY`. Set `COOKIE_SECURE=1`.
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
python app.py
```

`app.py` does not start a server by itself. For local use:

```bash
flask --app app run --debug
```

Set `REDIRECT_URI=http://127.0.0.1:5000/instagram/callback` and `COOKIE_SECURE=0` for that local URL, and add the same URI on the Meta app.
