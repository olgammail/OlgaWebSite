# Publish Olga's portfolio

The frontend goes to GitHub Pages. The login API goes to a separate Render Python Web Service. Existing accounts stay in MongoDB Atlas. Project cards live in the public projects.json website file.

1. Push this folder to your chosen GitHub repository on the main branch. The .gitignore excludes backend/.env, virtual environments, and local design previews.
2. In Render, create a Blueprint from that repository using render.yaml (or create a Web Service with the settings in backend/README.md).
3. Enter MONGODB_URI privately in Render. Set ALLOWED_ORIGINS to https://YOUR-USERNAME.github.io (no path or trailing slash), and FRONTEND_URL to https://YOUR-USERNAME.github.io/YOUR-REPOSITORY/.
4. Add the Render service's outbound IP ranges to Atlas's IP Access List. These are different from your computer's home or hotspot IP.
5. Once Render deploys, check its public /health URL. Then put its public base URL in the production branch of config.js in place of the empty string, and push the change.
6. In GitHub Settings > Pages, choose GitHub Actions. The supplied workflow publishes only the public frontend files, including projects.json.
7. Test registration, login, opening a project, refreshing while signed in, and signing out on the public website.

Official references: https://render.com/docs/blueprint-spec and https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages

The local workspace-preview.local.html is a design preview with a sample project card. It is ignored by Git and excluded from the published site. It does not grant access to the API.
