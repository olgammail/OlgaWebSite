const config = window.PORTAL_CONFIG;
const $ = (id) => document.getElementById(id);
let mode = 'login', applications = [], loadVersion = 0, expiryTimer;
let resetToken = new URLSearchParams(location.search).get('reset_token'), passwordResetAvailable = false;
// Session tokens are tab-scoped. Database credentials never reach the browser.
let token = '';
try { token = sessionStorage.getItem('olga-portal-session') || ''; } catch {}
const apiBase = (config.apiBaseUrl || '').replace(/\/$/, '');
if (resetToken) {
  const cleanUrl = new URL(location.href);
  cleanUrl.searchParams.delete('reset_token');
  history.replaceState(null, '', cleanUrl);
}

function saveToken(value) {
  token = value;
  try {
    if (value) sessionStorage.setItem('olga-portal-session', value);
    else sessionStorage.removeItem('olga-portal-session');
  } catch {}
}
async function api(path, { method = 'GET', data, authenticated = false } = {}) {
  if (!apiBase) throw new Error('The login service is not connected yet. Please return after setup is complete.');
  const headers = {};
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  if (authenticated && token) headers.Authorization = `Bearer ${token}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch(`${apiBase}${path}`, { method, headers, body: data === undefined ? undefined : JSON.stringify(data), signal: controller.signal, credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer' });
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(result.error || 'The request could not be completed.');
      error.status = response.status;
      error.code = result.code;
      throw error;
    }
    return result;
  } catch (error) {
    if (error instanceof TypeError || error.name === 'AbortError') throw new Error('The login service could not be reached. Please try again shortly.');
    throw error;
  } finally { clearTimeout(timeout); }
}
document.querySelectorAll('[data-brand]').forEach(el => { el.textContent = config.name; });
document.title = `${config.name} — AI Workflows & Games`;

function message(id, text = '', error = false) {
  $(id).textContent = text;
  $(id).classList.toggle('error', error);
}
function setMode(next) {
  mode = next;
  const signup = mode === 'signup', reset = mode === 'reset', update = mode === 'update';
  $('auth-title').textContent = signup ? 'Come explore with me.' : reset ? 'Reset your password' : update ? 'Choose a new password' : 'Explore what I’m building.';
  $('auth-copy').textContent = signup ? 'Create an account to explore my games and follow my work in AI automation.' : reset ? 'We’ll email you a password reset link.' : update ? 'Use at least 8 characters for your new password.' : 'Sign in to browse my projects, from games to an evolving collection of AI workflows.';
  $('name-field').hidden = !signup;
  $('name').required = signup;
  $('email-field').hidden = update;
  $('email').required = !update;
  $('password-field').hidden = reset;
  $('password').required = !reset;
  $('password').value = '';
  $('password').type = 'password';
  $('toggle-password').textContent = 'Show';
  $('toggle-password').setAttribute('aria-pressed', 'false');
  $('password').autocomplete = signup || update ? 'new-password' : 'current-password';
  $('password-hint').hidden = !(signup || update);
  $('auth-tabs').hidden = update;
  $('google-access').hidden = reset || update || !googleReady;
  $('forgot').hidden = reset || update || !passwordResetAvailable;
  $('login-tab').classList.toggle('active', mode === 'login');
  $('signup-tab').classList.toggle('active', signup);
  $('login-tab').setAttribute('aria-pressed', String(mode === 'login'));
  $('signup-tab').setAttribute('aria-pressed', String(signup));
  $('submit-auth').textContent = signup ? 'Create account →' : reset ? 'Send reset link →' : update ? 'Save password →' : 'Sign in & explore →';
  message('auth-message');
}
$('login-tab').onclick = () => setMode('login');
$('signup-tab').onclick = () => setMode('signup');
$('forgot').onclick = () => setMode('reset');
$('toggle-password').onclick = () => {
  const show = $('password').type === 'password';
  $('password').type = show ? 'text' : 'password';
  $('toggle-password').textContent = show ? 'Hide' : 'Show';
  $('toggle-password').setAttribute('aria-pressed', String(show));
};

$('auth-form').onsubmit = async (event) => {
  event.preventDefault();
  const controls = [...document.querySelectorAll('.auth-card button, .auth-card input')];
  controls.forEach(button => { button.disabled = true; });
  message('auth-message', 'Please wait…');
  const email = $('email').value.trim(), password = $('password').value;
  try {
    if (mode === 'signup') {
      const result = await api('/api/register', { method: 'POST', data: { email, password, name: $('name').value.trim() } });
      setMode('login');
      message('auth-message', result.message);
    } else if (mode === 'reset') {
      const result = await api('/api/password-reset/request', { method: 'POST', data: { email } });
      message('auth-message', result.message);
    } else if (mode === 'update') {
      const result = await api('/api/password-reset/confirm', { method: 'POST', data: { token: resetToken, password } });
      resetToken = null;
      saveToken('');
      showLoggedOut();
      setMode('login');
      message('auth-message', result.message);
    } else {
      const result = await api('/api/login', { method: 'POST', data: { email, password } });
      saveToken(result.token);
      $('password').value = '';
      await showUser(result);
    }
  } catch (error) {
    message('auth-message', error.message || 'Unable to connect. Please try again.', true);
  } finally {
    controls.forEach(button => { button.disabled = false; });
  }
};

function safeUrl(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
  catch { return null; }
}
function resetDirectory() {
  applications = [];
  $('search').value = '';
  $('app-grid').replaceChildren();
  $('app-count').textContent = '0';
  $('empty-state').hidden = true;
  $('retry').hidden = true;
  message('directory-message');
}
function render() {
  const query = $('search').value.trim().toLowerCase();
  const visible = applications.filter(app => `${app.name} ${app.description}`.toLowerCase().includes(query));
  $('app-count').textContent = String(visible.length);
  $('app-grid').replaceChildren();
  for (const app of visible) {
    const card = document.createElement('article'); card.className = 'app-card';
    const icon = document.createElement('span'); icon.className = 'app-icon'; icon.textContent = app.icon || '↗'; icon.setAttribute('aria-hidden', 'true');
    const title = document.createElement('h3'); title.textContent = app.name;
    const description = document.createElement('p'); description.textContent = app.description;
    const url = safeUrl(app.url);
    const link = document.createElement(url ? 'a' : 'span'); link.className = 'app-link';
    link.textContent = url ? 'Explore project ↗' : 'Project link coming soon';
    if (url) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.setAttribute('aria-label', `Open ${app.name} in a new tab`); }
    card.append(icon, title, description, link);
    $('app-grid').append(card);
  }
  $('empty-state').hidden = visible.length > 0;
  $('empty-title').textContent = query ? 'No matching projects' : 'Projects are on their way';
  $('empty-copy').textContent = query ? 'Try another search.' : 'New projects will appear here when published.';
}
$('search').oninput = render;

function showLoggedOut() {
  ++loadVersion;
  clearTimeout(expiryTimer);
  resetDirectory();
  $('auth-view').hidden = false;
  $('workspace-view').hidden = true;
  $('logout').hidden = true;
}
async function showUser(session) {
  const version = ++loadVersion;
  resetDirectory();
  $('auth-view').hidden = true;
  $('workspace-view').hidden = false;
  $('logout').hidden = false;
  clearTimeout(expiryTimer);
  const remaining = Date.parse(session.expires_at) - Date.now();
  expiryTimer = setTimeout(() => {
    saveToken(''); showLoggedOut(); setMode('login');
    message('auth-message', 'Your session has expired. Please sign in again.');
  }, Math.max(0, remaining));
  $('greeting').textContent = `Signed in as ${session.user.email || 'a registered visitor'}.`;
  message('directory-message', 'Loading Olga’s projects…');
  try {
    const result = await api('/api/applications', { authenticated: true });
    if (version !== loadVersion) return;
    applications = result.applications || [];
    message('directory-message');
    render();
  } catch (error) {
    if (version !== loadVersion) return;
    if (error.status === 401) {
      saveToken(''); showLoggedOut(); setMode('login');
      message('auth-message', 'Your session has expired. Please sign in again.');
      return;
    }
    message('directory-message', 'The projects couldn’t be loaded. Please try again shortly.', true);
    $('retry').hidden = false;
  }
}
$('retry').onclick = async () => {
  try { await showUser(await api('/api/me', { authenticated: true })); }
  catch (error) {
    if (error.status === 401) { saveToken(''); showLoggedOut(); setMode('login'); message('auth-message', error.message, true); }
    else message('directory-message', error.message, true);
  }
};
$('logout').onclick = async () => {
  $('logout').disabled = true;
  try {
    await api('/api/logout', { method: 'POST', data: {}, authenticated: true });
    saveToken(''); showLoggedOut(); setMode('login');
  } catch (error) {
    if (error.status === 401) { saveToken(''); showLoggedOut(); setMode('login'); }
    else message('directory-message', error.message, true);
  } finally { $('logout').disabled = false; }
};
async function initialize() {
  $('forgot').hidden = true;
  if (resetToken) setMode('update');
  if (!apiBase) {
    message('auth-message', 'Visitor accounts are being set up. Registration and login will be available soon.');
    return;
  }
  try {
    const capabilities = await api('/api/config');
    if (capabilities.google_client_id) setupGoogle(capabilities.google_client_id);
    passwordResetAvailable = capabilities.password_reset_available;
    $('forgot').hidden = !passwordResetAvailable || mode === 'update';
    if (token && !resetToken) await showUser(await api('/api/me', { authenticated: true }));
  } catch (error) {
    if (error.status === 401) { saveToken(''); showLoggedOut(); }
    else message('auth-message', error.message, true);
  }
}
let googleReady = false, googleBusy = false;
function setupGoogle(clientId) {
  const script = document.createElement('script');
  script.src = 'https://accounts.google.com/gsi/client';
  script.async = true;
  script.onload = () => {
    google.accounts.id.initialize({ client_id: clientId, callback: handleGoogle, auto_select: false });
    google.accounts.id.renderButton($('google-button'), { type: 'standard', theme: 'outline', size: 'large', text: 'continue_with', shape: 'rectangular' });
    googleReady = true;
    $('google-access').hidden = mode === 'reset' || mode === 'update';
  };
  script.onerror = () => message('auth-message', 'Google sign-in could not load. You can still use email and password.', true);
  document.head.append(script);
}
async function handleGoogle(response) {
  if (googleBusy || !response.credential) return;
  googleBusy = true;
  message('auth-message', 'Verifying your Google account…');
  try {
    const data = { credential: response.credential };
    if ($('password').value) data.password = $('password').value;
    const session = await api('/api/google-login', { method: 'POST', data });
    saveToken(session.token);
    $('password').value = '';
    await showUser(session);
  } catch (error) {
    if (error.code === 'password_required') { setMode('login'); $('password').focus(); }
    message('auth-message', error.message, true);
  } finally { googleBusy = false; }
}
initialize();
