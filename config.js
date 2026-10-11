// Public website settings. Never put your MongoDB URI or password here.
window.PORTAL_CONFIG = {
  name: "Olga Matskovsky",
  // Local development uses the Python backend on port 5000.
  // Replace the empty string with your Render backend URL before publishing.
  apiBaseUrl: ['localhost', '127.0.0.1'].includes(location.hostname)
    ? 'http://localhost:5000'
    : ''
};
