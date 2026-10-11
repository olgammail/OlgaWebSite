// Public website settings. Never put your MongoDB URI or password here.
window.PORTAL_CONFIG = {
  name: "Olga Matskovsky",
  // Local development uses the Python backend on port 5000.
  // Published website uses the Render login backend.
  apiBaseUrl: ['localhost', '127.0.0.1'].includes(location.hostname)
    ? 'http://localhost:5000'
    : 'https://olga-portfolio-api.onrender.com'
};
