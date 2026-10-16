# Python login backend — MongoDB Atlas + Render

Flask API for registration, login, sessions, logout, and session verification. Uses PyMongo for Atlas and Werkzeug scrypt for password hashing. Optional SMTP supports password reset. The frontend now uses this API instead of Supabase.

## Prepare your MongoDB connection

Use your existing cluster. Create a **database user** in Atlas Database Access; it is separate from your Atlas account. Give this user read/write access to the `olga_portal` database. The backend creates its collections and indexes inside that database.

In Atlas Network Access, allow your current public IP for local testing. When deploying, also allow your Render service's outbound IP addresses listed in Render. Use those addresses rather than opening access to every IP.

Choose **Connect → Drivers → Python** and copy the connection-string template into `backend/.env`. Replace the database username/password and cluster host. URL-encode special characters in the username/password. Do not put this connection string in `config.js` or commit it to GitHub.

## Local setup on Windows

Use Python 3.12 or newer. In PowerShell, from the website root folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
Copy-Item backend/.env.example backend/.env
```

Edit `backend/.env` locally. Set `MONGODB_URI` to your real Atlas connection string. Keep these settings for local testing:

```dotenv
MONGODB_DB=olga_portal
ALLOWED_ORIGINS=http://localhost:4173,http://127.0.0.1:4173
FRONTEND_URL=http://localhost:4173/
SESSION_HOURS=8
```

Start the backend:

```powershell
.\.venv\Scripts\python.exe backend/app.py
```

It listens on http://localhost:5000. Open http://localhost:5000/health: `{"status":"ok"}` confirms database connectivity. If startup fails, check credentials, Atlas's IP access list, and cluster status. A real MongoDB connection is required; there is no default in-memory account store.

In another terminal, run `node tools/serve.cjs` from the website root and open http://localhost:4173. Register with a name, email, and password, then sign in. Ctrl+C stops each server.

## Connection check

From the website root, run `.\.venv\Scripts\python.exe backend/check_connection.py` to send a read-only MongoDB ping.

## Project cards

The public website file `projects.json` contains the project cards. The frontend loads it after validating the visitor session with `/api/me`. The backend does not read or write project records. Update and publish the website file to add or edit projects.

An old `applications` collection from the previous implementation may still exist in Atlas. It is no longer used; this change does not delete existing database data.

## Deploy a separate Render Web Service

Connect Render to your GitHub repository. Create a new **Web Service**, separate from your game's service:

| Setting | Value |
| --- | --- |
| Runtime | Python 3 (3.12 or newer) |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 60` |
| Health Check Path | `/health` |

Set these values in Render **Environment**:

| Variable | Value |
| --- | --- |
| `MONGODB_URI` | Your private Atlas connection string |
| `MONGODB_DB` | `olga_portal` |
| `ALLOWED_ORIGINS` | `https://YOUR-USERNAME.github.io` |
| `FRONTEND_URL` | `https://YOUR-USERNAME.github.io/YOUR-REPOSITORY/` |
| `SESSION_HOURS` | `8` |

For a custom domain, substitute your domain. Multiple origins are comma-separated. Origins contain no path or trailing slash; `FRONTEND_URL` includes your repository path and trailing slash. Do not use `*`.

Add Render's outbound IP addresses to Atlas Network Access. After deploying, open `https://YOUR-LOGIN-SERVICE.onrender.com/health`, then set that base URL in `config.js` and publish the frontend on GitHub Pages. A free Render service may need time to wake up; the browser waits up to 45 seconds per request, and a slow wakeup may require retrying.

## Optional password-reset email

Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, and any required `SMTP_USERNAME` / `SMTP_PASSWORD`. Default is STARTTLS on port 587; for port 465 set `SMTP_USE_SSL=true`. Check whether your Render plan permits outgoing SMTP connections; some plans restrict them. An HTTPS email-provider integration can be added if needed.

**Forgot your password?** appears only when SMTP host/from settings exist. Reset links expire in 30 minutes, work once, and invalidate existing login sessions. Delivery errors are logged without passwords or tokens; responses stay generic to avoid disclosing account existence. Test actual delivery with your provider.

This version does not verify email ownership during registration. All registered visitors see the same directory. Administrator approval, email verification, and per-user permissions are not included.

## Session and access behavior

- Passwords are stored as scrypt hashes.
- Sessions use random tokens; MongoDB stores only token hashes. Tokens expire after `SESSION_HOURS`, without automatic refresh.
- The browser keeps its token in tab-scoped `sessionStorage`, not `localStorage`. Bearer tokens avoid third-party cookie restrictions between GitHub Pages and Render. Keep the website free of untrusted scripts, since same-origin JavaScript can read session storage.
- Every protected request checks expiry directly; logout revokes the token. MongoDB TTL cleanup is only background housekeeping.
- MongoDB-backed fixed-window rate limits apply to login, registration, and resets across workers. Origin checks allow only your configured frontend in browsers.
- Accounts and sessions survive Render restarts because they live in MongoDB.
- The directory requires login. Linked applications need their own authorization to prevent direct access to their URLs; this portal does not automatically authenticate your game.

Collections: `users`, `sessions`, `password_resets`, `rate_limits`, `oauth_attempts`, `provider_links`. No database credentials go to the browser.

## API

| Route | Purpose |
| --- | --- |
| `GET /health` | Database connectivity check |
| `GET /api/config` | Password-reset availability |
| `POST /api/register` | `{name,email,password}` → create account |
| `POST /api/login` | `{email,password}` → token, user, expiry |
| `GET /api/me` | Check session |
| `POST /api/logout` | Revoke session; send `{}` |
| `POST /api/password-reset/request` | `{email}` → send link |
| `POST /api/password-reset/confirm` | `{token,password}` → reset password |

Protected routes require `Authorization: Bearer <token>`. POSTs require JSON. Unauthorized requests return 401; throttled attempts return 429.

## Tests

From the website root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

Tests use isolated `mongomock` storage and simulated email delivery, without modifying Atlas or sending emails. Verify real Atlas connectivity and your Render/SMTP configuration separately.

Official references: [Render Flask deployment](https://render.com/docs/deploy-flask), [PyMongo connections](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/mongoclient/), [Atlas connection setup](https://www.mongodb.com/docs/atlas/connect-to-database-deployment/).

## Google sign-in

GOOGLE_CLIENT_ID is the public OAuth Web application client ID. The Render Blueprint supplies it; no client secret is used. Configure https://olgammail.github.io in Google's Authorized JavaScript origins. For local testing add http://localhost:4173 and set GOOGLE_CLIENT_ID in backend/.env.

The browser uses the official Google Identity Services button and posts the ID token as JSON to /api/google-login. The backend verifies signature, audience, issuer, expiry, and verified email using google-auth, then creates its own expiring session. Accounts are identified by Google's sub claim. No Google tokens or Google passwords are stored. Existing email/password accounts require their website password before linking to Google. Existing accounts remain available via email/password.

Google Auth Platform Audience controls testing/public availability. Complete a real browser sign-in test with your own Google account after deployment; automated tests mock Google's verifier and never authenticate a real person.

## GitHub sign-in

Create an OAuth App at https://github.com/settings/developers with Homepage URL and Authorization callback URL both set to https://olgammail.github.io/OlgaWebSite/. Add GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET privately in Render Environment after approving deployment. Do not put the secret in source files or the browser. The button stays hidden until both backend settings exist.

The backend requests read:user and user:email only, verifies the user with GitHub's API, and uses the stable GitHub user ID plus a verified email. It uses a short-lived one-use state bound to the initiating browser tab and PKCE S256. Access tokens are never stored. Email collisions require the existing website password before linking; Google-only accounts without a website password aren't linked automatically. Account-link tickets expire after five minutes. Login still requires a real provider verification.
