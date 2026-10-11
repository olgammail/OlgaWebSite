# Olga Matskovsky — AI Workflows & Games

A personal website with visitor registration/login and a protected project directory. Plain HTML, CSS, and JavaScript run on GitHub Pages. A separate Python/Flask service runs on Render and stores accounts and projects in MongoDB Atlas. All source files can live in one GitHub repository.

| Part | Where |
| --- | --- |
| Welcome page and browser code | GitHub Pages |
| Registration/login API | Render Web Service |
| Users, password hashes, sessions, projects | MongoDB Atlas |
| Database/email credentials | Local `backend/.env` / Render environment settings |

There is no preview shortcut or fake login. Registration creates an account, then asks the visitor to sign in. The backend verifies the session before returning projects. Each linked application still needs its own authorization if its URL must not be accessible directly; the portal does not automatically log visitors into your game.

## Run locally

Follow [the backend setup guide](backend/README.md) to connect your Atlas cluster and start the Python backend on port 5000.

In a second terminal, from the website root folder:

```powershell
node tools/serve.cjs
```

Open http://localhost:4173. Create an account, then sign in. Local browser configuration automatically calls http://localhost:5000. Use HTTP rather than opening `index.html` as a local file.

## Deploy

1. Commit/upload the project to GitHub. Keep `.env`, `.venv`, and private project JSON files out of GitHub; `.gitignore` is provided. Manual uploads must follow those exclusions too.
2. Deploy the `backend` folder as a separate Render **Web Service**, following [backend/README.md](backend/README.md).
3. Replace the empty production URL in `config.js`:

```javascript
apiBaseUrl: ['localhost', '127.0.0.1'].includes(location.hostname)
  ? 'http://localhost:5000'
  : 'https://YOUR-LOGIN-SERVICE.onrender.com'
```

4. In GitHub **Settings → Pages**, select **Deploy from a branch**, your branch (usually `main`), and `/ (root)`.
5. Set the backend's `ALLOWED_ORIGINS` to `https://YOUR-USERNAME.github.io` (without a repository path). Set `FRONTEND_URL` to your full website URL, such as `https://YOUR-USERNAME.github.io/YOUR-REPOSITORY/`.
6. Test signup, wrong-password rejection, login, reload, project opening, and logout on the published site.

The frontend files are `index.html`, `styles.css`, `landing.css`, `config.js`, `app.js`, and `.nojekyll`. Asset paths are relative for repository URLs. Never put a MongoDB connection string or SMTP password into frontend code.

## Customize

- `index.html`: biography and welcome text.
- `landing.css`: first-page design.
- `styles.css`: shared styling and project-page layout.
- `config.js`: site name, topics, and API URL.
- MongoDB `applications` collection: project names, descriptions, and links. The owner-only `backend/manage.py` command loads a JSON project file.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
node --check app.js
node --check config.js
```

Tests use isolated simulated MongoDB storage and simulated email delivery. They do not touch Atlas or send emails. Real Atlas, SMTP, and Render settings must be tested separately. No Supabase account is required.
