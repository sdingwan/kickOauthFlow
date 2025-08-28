import base64
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode, urlparse

import requests
from flask import Flask, redirect, request, session, url_for, jsonify, render_template_string
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # trust Railway proxy

# For local HTTP dev; tweak if you run HTTPS in prod
_is_https = (os.getenv("KICK_REDIRECT_URI", "").lower().startswith("https"))
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_is_https,
)

CLIENT_ID = os.getenv("KICK_CLIENT_ID")
CLIENT_SECRET = os.getenv("KICK_CLIENT_SECRET")
REDIRECT_URI = os.getenv("KICK_REDIRECT_URI")

# Set scopes from .env like: KICK_SCOPES="user:read channel:read chat:write"
SCOPES = os.getenv("KICK_SCOPES", "user:read").strip()
# Use Kick's public Pusher key and cluster
PUSHER_KEY = "32cbd69e4b950bf97679"  # Kick's public Pusher key
PUSHER_CLUSTER = "us2"  # Kick's Pusher cluster (us2 = Ohio)
CHANNEL_INFO_URL = "https://kick.com/api/v2/channels/{slug}"

OAUTH_AUTHORIZE_URL = "https://id.kick.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://id.kick.com/oauth/token"

# When called without ?id=..., this returns the current authorized user
API_ME_URL = "https://api.kick.com/public/v1/users"
API_CHANNELS_URL = "https://api.kick.com/public/v1/channels"
API_SEARCH_CHANNELS_URL = "https://api.kick.com/public/v1/channels/search"
CHAT_POST_URL = "https://api.kick.com/public/v1/chat"


def _new_pkce():
    code_verifier = base64.urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return code_verifier, challenge


def _store_tokens(token_json):
    session["access_token"] = token_json["access_token"]
    session["refresh_token"] = token_json.get("refresh_token")
    session["token_type"] = token_json.get("token_type", "Bearer")
    session["expires_at"] = int(time.time()) + int(token_json.get("expires_in", 0))


def _is_token_expired():
    return not session.get("access_token") or time.time() >= session.get("expires_at", 0) - 30


def _refresh_if_needed():
    if not _is_token_expired():
        return
    refresh_token = session.get("refresh_token")
    if not refresh_token:
        return
    data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(OAUTH_TOKEN_URL, data=data, headers=headers, timeout=20)
    r.raise_for_status()
    _store_tokens(r.json())


def _normalize_host_redirect():
    """
    If the current request host/scheme/port doesn't match REDIRECT_URI, redirect to the same path
    on the correct host. This prevents 'state mismatch' caused by cookies on localhost vs 127.0.0.1.
    """
    if not REDIRECT_URI:
        return None
    target = urlparse(REDIRECT_URI)
    cur = urlparse(request.host_url)

    target_port = target.port or (443 if target.scheme == "https" else 80)
    cur_port = cur.port or (443 if cur.scheme == "https" else 80)

    if (cur.hostname != target.hostname) or (cur.scheme != target.scheme) or (cur_port != target_port):
        # Rebuild same path/query on correct host
        new_url = f"{target.scheme}://{target.hostname}"
        if (target.scheme == "http" and target_port != 80) or (target.scheme == "https" and target_port != 443):
            new_url += f":{target_port}"
        new_url += request.full_path if request.query_string else request.path
        return redirect(new_url, code=302)
    return None


def _is_logged_in():
    return "access_token" in session and not _is_token_expired()


def _render_page(page_title: str, body_html: str, slug_default: str = ""):
    base = """
    <!doctype html>
    <html lang=\"en\">
    <head>
      <meta charset=\"utf-8\"/>
      <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>
      <title>{{ title }}</title>
      <style>
        :root {
          color-scheme: dark;
          --bg: #0f0f10;
          --panel: #17181b;
          --panel-2: #1d2024;
          --border: #272a30;
          --text: #e5e7eb;
          --muted: #9aa4b2;
          --accent: #53fc18;
        }
        html, body { height: 100%; }
        body { margin:0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height:1.5; }
        a { color: #cbd5e1; text-decoration: none; }
        a:hover { color: #fff; }
        header { position:sticky; top:0; background: rgba(15,15,16,0.9); backdrop-filter: saturate(140%) blur(8px); border-bottom:1px solid var(--border); z-index: 10; }
        .nav { display:flex; gap:16px; align-items:center; height:64px; max-width: 1120px; margin: 0 auto; padding: 0 20px; }
        .brand a { display:flex; align-items:center; gap:10px; color:#fff; font-weight:800; letter-spacing:0.2px; }
        .k-logo { display:inline-block; width:24px; height:24px; border-radius:4px; background: var(--accent); box-shadow: 0 0 24px rgba(83,252,24,0.35); }
        .brand-name { font-size:18px; }
        .search { display:flex; gap:8px; align-items:center; margin-left:auto; }
        .search input[type=text]{ padding:10px 12px; border-radius:10px; border:1px solid var(--border); background: var(--panel); color: var(--text); min-width:280px; outline:none; }
        .search input[type=text]::placeholder{ color: #7a8594; }
        .btn { padding:10px 14px; border-radius:10px; border:1px solid #1f6d12; background: linear-gradient(180deg, var(--accent), #34d215); color:#031b07; font-weight:800; cursor:pointer; }
        .btn:hover { filter:brightness(1.03); }
        .links { display:flex; gap:14px; align-items:center; margin-left: 8px; }
        .container { max-width: 1120px; margin: 24px auto; padding: 0 20px; }
        .card { background: var(--panel); border:1px solid var(--border); border-radius:14px; padding:16px; }
        .grid { display:grid; grid-template-columns: 120px 1fr; gap:16px; }
        img.avatar { width:120px; height:120px; border-radius:12px; object-fit:cover; border:1px solid var(--border); }
        code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; }
        pre.pretty { padding:12px; border:1px solid var(--border); border-radius:10px; background: var(--panel-2); color: var(--text); overflow:auto; }
        .k-badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; background: var(--accent); color:#031b07; margin-left:8px; font-weight:800; }
        .muted { color: var(--muted); }
        a.clean { color:#9fe870; }
        a.clean:hover { color:#c5f6a1; }
        .banner { width:100%; max-height:220px; object-fit:cover; border-radius:12px; border:1px solid var(--border); }
        #search-suggestions { position:absolute; left:0; right:0; top:44px; background: var(--panel); border:1px solid var(--border); border-radius:12px; display:none; max-height:320px; overflow:auto; padding:6px; z-index:9999; }
        .sg-item { transition: background 120ms ease; }
        .sg-item:hover { background: #1a1d22; }
        mark { background: rgba(83,252,24,0.3); color: inherit; border-radius: 3px; padding: 0 2px; }
      </style>
    </head>
    <body>
      <header>
        <div class=\"nav\">
          <div class=\"brand\"><a href=\"/\"><span class=\"k-logo\"></span><span class=\"brand-name\">KICK</span></a></div>
          <div style=\"position:relative; flex:1; max-width:540px;\">
            <form class=\"search\" action=\"/channels/search\" method=\"get\" autocomplete=\"off\">
              <input id=\"global-search\" type=\"text\" name=\"slug\" placeholder=\"Search channels\" value=\"{{ slug or '' }}\"/>
              <button class=\"btn\" type=\"submit\">Search</button>
            </form>
            <div id=\"search-suggestions\"></div>
          </div>
          <nav class=\"links\">
            <a href=\"/\">Home</a>
            {% if is_logged_in %}
              <a href=\"/me\">Me</a>
              <a href=\"/live-chat\">Live Chat</a>
              <a href=\"/logout\">Logout</a>
            {% else %}
              <a href=\"/login\">Login</a>
            {% endif %}
          </nav>
        </div>
      </header>
      <main class=\"container\">
        {{ body|safe }}
      </main>
      <script>
        (function(){
          const input = document.getElementById('global-search');
          const box = document.getElementById('search-suggestions');
          if(!input || !box) return;

          let aborter = null;
          let activeIndex = -1;
          const state = { items: [] };

          function hide(){ box.style.display = 'none'; activeIndex = -1; state.items = []; box.innerHTML=''; }
          function show(){ if (box.innerHTML.trim()) box.style.display = 'block'; }
          function highlight(str, q){ try{ const re = new RegExp('('+q.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\$&')+')','ig'); return str.replace(re,'<mark>$1</mark>'); }catch(e){ return str; } }

          function render(){
            if(!state.items.length){ hide(); return; }
            const html = state.items.map((it, idx) => `
              <a href=\"/channels/${it.slug}\" data-idx=\"${idx}\" style=\"display:flex;align-items:center;gap:10px;padding:8px;border-radius:8px;color:#e5e7eb;text-decoration:none;\" class=\"sg-item\">
                ${it.banner_picture ? `<img src=\"${it.banner_picture}\" style=\"width:44px;height:28px;object-fit:cover;border-radius:6px;border:1px solid #334155;\"/>` : '<div style=\"width:44px;height:28px;\"></div>'}
                <div style=\"display:flex;flex-direction:column;\">
                  <span style=\"font-weight:600;\">${highlight(it.slug || '', input.value.trim())}</span>
                  ${it.category_name ? `<span style=\"font-size:12px;color:#94a3b8;\">${it.category_name}</span>` : ''}
                </div>
                ${it.is_live ? '<span class=\"k-badge\" style=\"margin-left:auto;\">LIVE</span>' : ''}
              </a>
            `).join('');
            box.innerHTML = html;
            show();
          }

          function setActive(i){
            const items = box.querySelectorAll('.sg-item');
            items.forEach(el => el.style.background='transparent');
            if(i>=0 && i<items.length){ items[i].style.background = 'rgba(59,130,246,0.15)'; items[i].scrollIntoView({block:'nearest'}); }
          }

          const debounce = (fn, ms) => { let t; return (...args)=>{ clearTimeout(t); t=setTimeout(()=>fn(...args), ms); }; };

          const fetchSuggest = debounce(async () => {
            const q = input.value.trim();
            if(q.length < 2){ hide(); return; }
            try{
              aborter?.abort?.();
              aborter = new AbortController();
              const res = await fetch(`/channels/suggest?q=${encodeURIComponent(q)}`, { signal: aborter.signal });
              if(!res.ok){ hide(); return; }
              const json = await res.json();
              const items = (json?.data || []).slice(0, 8).map(ch => ({
                slug: ch.slug,
                banner_picture: ch.banner_picture,
                is_live: ch.stream?.is_live,
                category_name: ch.category?.name
              }));
              state.items = items;
              activeIndex = -1;
              render();
            }catch(e){ /* ignore */ hide(); }
          }, 250);

          input.addEventListener('input', fetchSuggest);
          input.addEventListener('focus', ()=>{ if(state.items.length) show(); });
          document.addEventListener('click', (e)=>{ if(!box.contains(e.target) && e.target !== input){ hide(); } });
          input.addEventListener('keydown', (e)=>{
            if(box.style.display === 'none') return;
            const max = state.items.length;
            if(e.key === 'ArrowDown'){ e.preventDefault(); activeIndex = Math.min(max-1, activeIndex+1); setActive(activeIndex); }
            else if(e.key === 'ArrowUp'){ e.preventDefault(); activeIndex = Math.max(0, activeIndex-1); setActive(activeIndex); }
            else if(e.key === 'Enter'){ if(activeIndex>=0 && activeIndex<max){ e.preventDefault(); const a = box.querySelectorAll('.sg-item')[activeIndex]; if(a) window.location.href = a.getAttribute('href'); } }
            else if(e.key === 'Escape'){ hide(); }
          });
        })();
      </script>
    </body>
    </html>
    """
    return render_template_string(
        base,
        title=page_title,
        body=body_html,
        is_logged_in=_is_logged_in(),
        slug=slug_default,
    )


@app.route("/")
def index():
    # Removed _normalize_host_redirect() here to avoid redirect loops behind proxies
    if "access_token" in session and not _is_token_expired():
        return redirect(url_for("me"))

    cur_host = urlparse(request.host_url).hostname
    redir_host = urlparse(REDIRECT_URI).hostname if REDIRECT_URI else None
    warn = ""
    if redir_host and cur_host != redir_host:
        warn = f"<p style='color:red'>Warning: You are on <b>{cur_host}</b> but REDIRECT_URI is <b>{redir_host}</b>. We'll auto-switch hosts for login.</p>"

    body = f"""
      <div class=\"card\">
        <h2 style=\"margin-top:0\">Welcome</h2>
    {warn}
        <p class=\"muted\">Configured scopes</p>
        <pre class=\"pretty\"><code>{SCOPES or '(none)'}\n</code></pre>
        <p><a class=\"btn\" href=\"/login\">Log in with Kick</a></p>
        <p class=\"muted\">Tip: Use the search bar above to look up channels by slug.</p>
      </div>
    """
    return _render_page("Kick OAuth Demo", body)


@app.route("/login")
def login():
    fix = _normalize_host_redirect()
    if fix:
        return fix

    if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
        return ("Missing CLIENT_ID/CLIENT_SECRET/REDIRECT_URI env vars.", 500)

    # Generate state + PKCE
    code_verifier, code_challenge = _new_pkce()
    state = secrets.token_urlsafe(24)

    session["pkce_verifier"] = code_verifier
    session["oauth_state"] = state

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,  # space-separated scopes
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return redirect(f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


@app.route("/callback")
def callback():
    fix = _normalize_host_redirect()
    if fix:
        return fix
    # Validate state (if you still hit mismatch, ensure you started login on the same host as REDIRECT_URI)
    state = request.args.get("state")
    if not state or state != session.get("oauth_state"):
        cur_host = urlparse(request.host_url).hostname
        redir_host = urlparse(REDIRECT_URI).hostname if REDIRECT_URI else "?"
        return (
            f"State mismatch. You may have started the flow on '{cur_host}' but REDIRECT_URI is '{redir_host}'. "
            "Use the same host for /login and in your REDIRECT_URI, then try again. "
            "<a href='/logout'>Clear session</a>",
            400,
        )

    code = request.args.get("code")
    if not code:
        return "Missing authorization code.", 400

    code_verifier = session.get("pkce_verifier")
    if not code_verifier:
        return "Missing code_verifier in session.", 400

    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
        "code": code,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    token_resp = requests.post(OAUTH_TOKEN_URL, data=data, headers=headers, timeout=20)
    if token_resp.status_code != 200:
        return f"Token exchange failed ({token_resp.status_code})<pre>{token_resp.text}</pre>", 400

    _store_tokens(token_resp.json())
    session.pop("pkce_verifier", None)
    session.pop("oauth_state", None)

    return redirect(url_for("me"))


@app.route("/me")
def me():
    _refresh_if_needed()
    if _is_token_expired():
        return redirect(url_for("login"))

    headers = {
        "Authorization": f"Bearer {session['access_token']}",
        "Accept": "application/json",
    }
    r = requests.get(API_ME_URL, headers=headers, timeout=20)
    if r.status_code != 200:
        return f"Failed to fetch user info ({r.status_code})<pre>{r.text}</pre>", 400

    data = r.json().get("data", [])
    user = data[0] if isinstance(data, list) and data else data

    avatar = user.get("profile_picture") or ""
    name = user.get("name") or user.get("username") or "User"
    user_id = user.get("user_id") or user.get("id")

    body = """
      <div class=\"card\">
        <h2 style=\"margin-top:0\">Signed in!{% if name %} — {{ name }}{% endif %}</h2>
        <div class=\"grid\">
          {% if avatar %}<img class=\"avatar\" src=\"{{ avatar }}\" alt=\"avatar\"/>{% else %}<div></div>{% endif %}
          <div>
            {% if user_id %}<p><b>User ID</b>: {{ user_id }}</p>{% endif %}
            <p class=\"muted\">Scopes requested</p>
            <pre class=\"pretty\"><code>{{ scopes }}\n</code></pre>
          </div>
        </div>
      </div>
      <div style=\"height:12px\"></div>
      <details class=\"card\"><summary>Raw user payload</summary>
        <pre class=\"pretty\">{{ pretty }}</pre>
      </details>
    """
    return _render_page(
        "Your Account",
        render_template_string(
            body,
            name=name,
            avatar=avatar,
            user_id=user_id,
        scopes=SCOPES or "(none)",
        pretty=jsonify(user).get_data(as_text=True),
        ),
    )


@app.route("/channels/search")
def channels_search():
    fix = _normalize_host_redirect()
    if fix:
        return fix

    slug = (request.args.get("slug") or "").strip()
    if not slug:
        body = """
          <div class=\"card\">
            <h2 style=\"margin-top:0\">Search a channel</h2>
            <p class=\"muted\">Use the top search bar or submit a slug below.</p>
            <form action=\"/channels/search\" method=\"get\" style=\"display:flex;gap:8px;align-items:center;\">
              <input type=\"text\" name=\"slug\" placeholder=\"e.g. gmhikaru\" required style=\"padding:8px;border-radius:8px;border:1px solid #334155;\"/>
              <button class=\"btn\" type=\"submit\">Search</button>
            </form>
          </div>
        """
        return _render_page("Channel Search", body)

    # Try with token if available; endpoint supports public access as well
    headers = {"Accept": "application/json"}
    _refresh_if_needed()
    if not _is_token_expired():
        headers["Authorization"] = f"Bearer {session['access_token']}"

    r = requests.get(API_CHANNELS_URL, headers=headers, params={"slug": slug}, timeout=20)
    if r.status_code != 200:
        body = render_template_string(
            """
            <div class=\"card\">
              <h2 style=\"margin-top:0\">Channel Lookup</h2>
              <p>Query slug: <code>{{ slug }}</code></p>
              <pre class=\"pretty\">Failed ({{ status }})\n{{ text }}</pre>
            </div>
            """,
            slug=slug,
            status=r.status_code,
            text=r.text,
        )
        return _render_page("Channel Lookup", body, slug_default=slug)

    payload = r.json()
    data = payload.get("data", [])
    channel = data[0] if isinstance(data, list) and data else data

    if not channel:
        body = render_template_string(
            """
            <div class=\"card\">
              <h2 style=\"margin-top:0\">No channel found</h2>
              <p>Query slug: <code>{{ slug }}</code></p>
            </div>
            """,
            slug=slug,
        )
        return _render_page("Channel Lookup", body, slug_default=slug)

    slug_val = channel.get("slug") or slug
    desc = channel.get("channel_description") or ""
    banner = channel.get("banner_picture") or ""
    stream = channel.get("stream") or {}
    is_live = stream.get("is_live")
    viewer_count = stream.get("viewer_count")
    language = stream.get("language") or ""
    stream_title = channel.get("stream_title") or ""
    category = channel.get("category") or {}
    category_name = category.get("name") or ""

    body = render_template_string(
        """
        <div class=\"card\">
          {% if banner %}<img class=\"banner\" src=\"{{ banner }}\" alt=\"banner\"/>{% endif %}
          <h2 style=\"margin:12px 0 6px 0\">{{ slug_val }}
            {% if is_live %}<span class=\"k-badge\">LIVE</span>{% endif %}
          </h2>
          {% if stream_title %}<p><b>Title</b>: {{ stream_title }}</p>{% endif %}
          {% if desc %}<p class=\"muted\">{{ desc }}</p>{% endif %}
          <p>
            {% if category_name %}<b>Category</b>: {{ category_name }} &nbsp;{% endif %}
            {% if language %}<b>Language</b>: {{ language }} &nbsp;{% endif %}
            {% if viewer_count is not none %}<b>Viewers</b>: {{ viewer_count }}{% endif %}
          </p>
          <p><a class=\"clean\" href=\"https://kick.com/{{ slug_val }}\" target=\"_blank\" rel=\"noreferrer noopener\">Open on Kick →</a></p>
        </div>
        <div style=\"height:12px\"></div>
        <details class=\"card\"><summary>Raw channel payload</summary>
          <pre class=\"pretty\">{{ pretty }}</pre>
        </details>
        """,
        slug_val=slug_val,
        banner=banner,
        is_live=is_live,
        stream_title=stream_title,
        desc=desc,
        category_name=category_name,
        language=language,
        viewer_count=viewer_count,
        pretty=jsonify(channel).get_data(as_text=True),
    )
    return _render_page("Channel Lookup", body, slug_default=slug)


@app.route("/channels/<slug>")
def channel_detail(slug: str):
    # Convenience path to link directly to a channel by slug
    request_args = request.args.to_dict() if request.args else {}
    request_args["slug"] = slug
    return redirect(url_for("channels_search", **request_args))


@app.route("/channels/suggest")
def channels_suggest():
    """Return lightweight channel suggestions for autocomplete.
    Tries the public search endpoint and falls back to prefix slug lookup.
    """
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"data": []})

    headers = {"Accept": "application/json"}
    _refresh_if_needed()
    if not _is_token_expired():
        headers["Authorization"] = f"Bearer {session['access_token']}"

    # Strategy 1: use public search endpoint (if present/allowed)
    items = []
    try:
        r = requests.get(API_SEARCH_CHANNELS_URL, headers=headers, params={"query": q}, timeout=10)
        if r.status_code == 200:
            payload = r.json() or {}
            items = payload.get("data") or payload.get("channels") or []
    except Exception:
        items = []

    # Strategy 2 fallback: try slug exact only if search not available
    if not items and len(q) >= 2:
        try:
            r2 = requests.get(API_CHANNELS_URL, headers=headers, params={"slug": q}, timeout=10)
            if r2.status_code == 200:
                p2 = r2.json(); d2 = p2.get("data", [])
                ch = d2[0] if isinstance(d2, list) and d2 else None
                if ch:
                    items = [ch]
        except Exception:
            pass

    # Normalize minimal fields for client
    normalized = []
    for ch in items:
        if not isinstance(ch, dict):
            continue
        normalized.append({
            "slug": ch.get("slug") or ch.get("username") or "",
            "banner_picture": ch.get("banner_picture") or "",
            "stream": ch.get("stream") or {},
            "category": ch.get("category") or {},
        })

    return jsonify({"data": normalized})


@app.route("/send-chat", methods=["POST"])
def send_chat():
    """Backend endpoint to send chat messages with proper OAuth authentication."""
    fix = _normalize_host_redirect()
    if fix:
        return fix
    
    # Require login to send chat
    _refresh_if_needed()
    if _is_token_expired():
        return jsonify({"error": "Unauthorized - please log in"}), 401
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        content = data.get("content", "").strip()
        slug = data.get("slug", "").strip()
        
        if not content:
            return jsonify({"error": "Message content is required"}), 400
        if not slug:
            return jsonify({"error": "Channel slug is required"}), 400
        
        # Get broadcaster_user_id from the slug
        headers = {
            "Authorization": f"Bearer {session['access_token']}",
            "Accept": "application/json",
        }
        
        r = requests.get(API_CHANNELS_URL, headers=headers, params={"slug": slug}, timeout=15)
        if r.status_code != 200:
            return jsonify({"error": f"Failed to resolve channel: {r.status_code}"}), 400
        
        payload = r.json()
        data_list = payload.get("data", [])
        channel = data_list[0] if isinstance(data_list, list) and data_list else None
        
        if not channel:
            return jsonify({"error": "Channel not found"}), 404
        
        # Try to get broadcaster_user_id from various possible fields
        broadcaster_user_id = (
            channel.get("broadcaster_user_id")
            or channel.get("user_id")
            or channel.get("id")
            or (channel.get("user", {}).get("id") if isinstance(channel.get("user"), dict) else None)
        )
        
        if not broadcaster_user_id:
            return jsonify({"error": "Could not resolve broadcaster user ID"}), 400
        
        # Send the chat message
        chat_headers = {
            "Authorization": f"Bearer {session['access_token']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        chat_body = {
            "type": "user",
            "content": content,
            "broadcaster_user_id": broadcaster_user_id,
        }
        
        resp = requests.post(CHAT_POST_URL, headers=chat_headers, json=chat_body, timeout=20)
        
        if resp.status_code == 200:
            return jsonify({"success": True, "message": "Message sent successfully"})
        else:
            return jsonify({"error": f"Send failed: {resp.status_code}", "details": resp.text}), resp.status_code
            
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@app.route("/live-chat")
def live_chat():
    fix = _normalize_host_redirect()
    if fix:
        return fix

    slug = (request.args.get("slug") or "").strip()

    body = render_template_string(
        """
        <div class=\"card\">
          <h2 style=\"margin-top:0\">Live Chat</h2>
          <form method=\"get\" style=\"display:flex;gap:8px;align-items:center;margin-bottom:12px;\">
            <input name=\"slug\" value=\"{{ slug }}\" placeholder=\"channel slug\" style=\"padding:8px;border-radius:8px;border:1px solid #334155;\"/>
            <button class=\"btn\" type=\"submit\">Join</button>
          </form>
          <div id=\"chatbox\" style=\"height:380px;overflow:auto;border:1px solid #334155;border-radius:8px;padding:8px;background:rgba(255,255,255,0.04);\"></div>
          <form id=\"sendForm\" style=\"display:flex;gap:8px;margin-top:8px;\">
            <input id=\"msg\" placeholder=\"Message\" style=\"flex:1;padding:8px;border-radius:8px;border:1px solid #334155;\"/>
            <button class=\"btn\" type=\"submit\">Send</button>
          </form>
          <p class=\"muted\" style=\"margin-top:6px;\">Requires <code>chat:write</code> scope to send.</p>
        </div>

        <script src=\"https://js.pusher.com/8.2.0/pusher.min.js\"></script>
        <script>
          const slug = {{ slug|tojson }};
          const chatbox = document.getElementById('chatbox');
          const form = document.getElementById('sendForm');
          const msg = document.getElementById('msg');

          function appendLine(html){
            const div = document.createElement('div');
            div.innerHTML = html;
            chatbox.appendChild(div);
            chatbox.scrollTop = chatbox.scrollHeight;
          }

          if(slug){
            // Use Kick's public Pusher key and cluster
            const pusherKey = '32cbd69e4b950bf97679';
            const cluster = 'us2';
            
            Pusher.logToConsole = false;
            const pusher = new Pusher(pusherKey, { cluster });
            
            // First, get the chatroom ID from Kick's API
            (async () => {
              try {
                const res = await fetch(`/resolve/chatroom-id?slug=${encodeURIComponent(slug)}`);
                const j = await res.json();
                const chatroomId = j?.chatroom_id;
                if(!chatroomId) {
                  appendLine('<em>Could not resolve chatroom ID for this slug.</em>');
                  return;
                }
                
                // Subscribe to the v2 chatroom format used by Kick
                const channelName = `chatrooms.${chatroomId}.v2`;
                appendLine(`<em>Connecting to ${channelName}...</em>`);
                
                const channel = pusher.subscribe(channelName);
                
                // Handle chat message events
                channel.bind('App\\\\Events\\\\ChatMessageEvent', function(data) {
                  try {
                    const username = data?.sender?.username || 'user';
                    const content = data?.content || '';
                    if(username && content) {
                      appendLine(`<strong>${username}:</strong> ${content}`);
                    }
                  } catch(e) {
                    console.error('Error parsing message:', e);
                  }
                });
                
                // Handle other events for debugging
                channel.bind_global((event, data) => {
                  if(event && event !== 'App\\\\Events\\\\ChatMessageEvent') {
                    console.log('Other event:', event, data);
                  }
                });
                
                appendLine('<em>Connected to live chat!</em>');
              } catch(e) {
                appendLine('<em>Failed to connect to chat.</em>');
                console.error('Connection error:', e);
              }
            })();
          }

          form?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const text = msg.value.trim();
            if(!text) return;
            try{
              const res = await fetch('/send-chat', { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify({ slug, content: text }) 
              });
              if(res.ok){ 
                msg.value=''; 
                appendLine(`<em style="color:#22c55e">Message sent!</em>`);
              } else {
                const errorData = await res.json();
                appendLine(`<em style="color:#ef4444">Send failed: ${errorData.error || 'Unknown error'}</em>`);
              }
            }catch(e){ 
              appendLine(`<em style="color:#ef4444">Error sending: ${e.message}</em>`);
            }
          });
        </script>
        """,
        slug=slug
    )
    return _render_page("Live Chat", body, slug_default=slug)


@app.route("/resolve/broadcaster-id")
def resolve_broadcaster_id():
    slug = (request.args.get("slug") or "").strip()
    if not slug:
        return jsonify({}), 400
    headers = {"Accept": "application/json"}
    _refresh_if_needed()
    if not _is_token_expired():
        headers["Authorization"] = f"Bearer {session['access_token']}"
    try:
        r = requests.get(API_CHANNELS_URL, headers=headers, params={"slug": slug}, timeout=15)
        if r.status_code != 200:
            return jsonify({}), 404
        payload = r.json(); data = payload.get("data", [])
        ch = data[0] if isinstance(data, list) and data else None
        if not ch:
            return jsonify({}), 404
        bid = ch.get("broadcaster_user_id") or ch.get("user_id") or ch.get("id") or (ch.get("user", {}).get("id") if isinstance(ch.get("user"), dict) else None)
        return jsonify({"broadcaster_user_id": bid or None})
    except Exception:
        return jsonify({}), 500


@app.route("/resolve/chatroom-id")
def resolve_chatroom_id():
    slug = (request.args.get("slug") or "").strip()
    if not slug:
        return jsonify({}), 400
    try:
        # Use Kick's site API to get chatroom ID (same as the working Python code)
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://kick.com/",
            "Origin": "https://kick.com"
        }
        
        url = CHANNEL_INFO_URL.format(slug=slug)
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 403:
            error_data = resp.json() if resp.content else {}
            if "security policy" in error_data.get("error", "").lower():
                return jsonify({"error": "Blocked by security policy"}), 403
            else:
                return jsonify({"error": "Access forbidden"}), 403
        elif resp.status_code == 404:
            return jsonify({"error": "Channel not found"}), 404
        elif resp.status_code == 429:
            return jsonify({"error": "Rate limited"}), 429
        
        resp.raise_for_status()
        data = resp.json()
        
        if "chatroom" not in data or "user" not in data:
            return jsonify({"error": "Unexpected API response structure"}), 400
        
        chatroom_id = data["chatroom"]["id"]
        return jsonify({"chatroom_id": chatroom_id})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/login/debug")
def login_debug():
    fix = _normalize_host_redirect()
    if fix:
        return fix

    code_verifier, code_challenge = _new_pkce()
    state = secrets.token_urlsafe(24)

    session["pkce_verifier"] = code_verifier
    session["oauth_state"] = state

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    auth_url = f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
    return f"""
    <h3>Auth URL your app will use</h3>
    <p><code>{auth_url}</code></p>
    <h3>redirect_uri value being sent</h3>
    <p><code>{REDIRECT_URI!r}</code></p>
    <p><a href="/login">Proceed to /login</a></p>
    """


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


if __name__ == "__main__":
    # IMPORTANT: visit using the SAME host (localhost OR 127.0.0.1) as in KICK_REDIRECT_URI.
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
