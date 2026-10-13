"""MongoDB-backed visitor accounts for Olga's GitHub Pages website."""
import hashlib
import logging
import os
import secrets
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps, partial
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from dotenv import load_dotenv
from email_validator import EmailNotValidError, validate_email
from flask import Flask, g, jsonify, request
from google.oauth2 import id_token as google_id_token
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import TransportError
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash


def utcnow():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def connection_error_summary(error):
    """Explain the failed stage without exposing a URI or credentials."""
    detail = str(error).lower()
    if 'ssl' in detail or 'tls' in detail:
        return 'Secure connection (TLS handshake) failed before MongoDB commands could run.'
    if 'authentication failed' in detail or getattr(error, 'code', None) == 18:
        return 'MongoDB was reached, but database-user authentication failed.'
    if 'not authorized' in detail or getattr(error, 'code', None) == 13:
        return 'MongoDB was reached, but the database user lacks permission.'
    if 'dns' in detail or 'resolution' in detail or 'query name' in detail:
        return 'The MongoDB hostname lookup failed or timed out.'
    return f'MongoDB connection check failed ({type(error).__name__}).'


def create_app(database=None, settings=None):
    load_dotenv(Path(__file__).with_name('.env'))
    cfg = dict(os.environ)
    cfg.update(settings or {})
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
    origins = {item.strip() for item in cfg.get('ALLOWED_ORIGINS', '').split(',') if item.strip()}
    if not origins:
        raise RuntimeError('Set ALLOWED_ORIGINS before starting the backend.')
    for origin in origins:
        parsed = urlsplit(origin)
        local = parsed.hostname in {'localhost', '127.0.0.1'}
        if (parsed.scheme != 'https' and not (local and parsed.scheme == 'http')) or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise RuntimeError('ALLOWED_ORIGINS must contain exact HTTPS origins (HTTP is allowed for localhost).')
    frontend = cfg.get('FRONTEND_URL', 'http://localhost:4173/')
    frontend_parts = urlsplit(frontend)
    if f'{frontend_parts.scheme}://{frontend_parts.netloc}' not in origins or frontend_parts.query or frontend_parts.fragment:
        raise RuntimeError('FRONTEND_URL must belong to ALLOWED_ORIGINS and have no query or fragment.')
    hours = int(cfg.get('SESSION_HOURS', '8'))
    if not 1 <= hours <= 24:
        raise RuntimeError('SESSION_HOURS must be between 1 and 24.')
    if cfg.get('RENDER') == 'true':
        # Render is the trusted reverse proxy. Do not trust forwarded headers locally.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    if database is None:
        uri = cfg.get('MONGODB_URI')
        if not uri:
            raise RuntimeError('Set MONGODB_URI in backend/.env or Render environment settings.')
        # MongoClient starts connection discovery; constructing it is not proof
        # of a successful connection. Ping forces a real, authenticated command.
        app.logger.info('Checking MongoDB connection with ping (before creating indexes)...')
        mongo = None
        try:
            mongo = MongoClient(uri, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000, tz_aware=True)
            mongo.admin.command('ping')
        except PyMongoError as error:
            if mongo is not None:
                mongo.close()
            raise RuntimeError(connection_error_summary(error)) from None
        app.logger.info('MongoDB ping succeeded. Creating database indexes next.')
        database = mongo[cfg.get('MONGODB_DB', 'olga_portal')]
        app.extensions['mongo_client'] = mongo
    db = database
    app.extensions['database'] = db
    db.users.create_index('email', unique=True)
    db.users.create_index('google_sub', unique=True, sparse=True)
    db.sessions.create_index('token_hash', unique=True)
    db.sessions.create_index('expires_at', expireAfterSeconds=0)
    db.password_resets.create_index('token_hash', unique=True)
    db.password_resets.create_index('expires_at', expireAfterSeconds=0)
    db.rate_limits.create_index('expires_at', expireAfterSeconds=0)
    db.applications.create_index('slug', unique=True)
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')
    smtp_ready = bool(cfg.get('SMTP_HOST') and cfg.get('SMTP_FROM'))
    google_client_id = cfg.get('GOOGLE_CLIENT_ID', '').strip()

    @app.before_request
    def guard_request():
        if not request.path.startswith('/api/'):
            return None
        origin = request.headers.get('Origin')
        if origin is not None and origin not in origins:
            return jsonify(error='This website is not allowed to use the login service.'), 403
        if request.method == 'OPTIONS':
            return '', 204
        if request.method == 'POST' and not request.is_json:
            return jsonify(error='Send a JSON request.'), 415

    @app.after_request
    def response_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        origin = request.headers.get('Origin')
        if origin in origins:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Max-Age'] = '600'
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(PyMongoError)
    def database_error(error):
        # Do not print exception strings: connection errors can include connection details.
        app.logger.error('Database operation failed (%s)', type(error).__name__)
        return jsonify(error='The account service cannot reach its database. Please try again later.'), 503

    def body():
        data = request.get_json()
        if not isinstance(data, dict):
            return {}
        return data

    def email_from(data):
        value = data.get('email')
        if not isinstance(value, str) or len(value) > 254:
            return None
        try:
            # Consistently case-insensitive accounts. No network/DNS validation here.
            return validate_email(value.strip(), check_deliverability=False).normalized.casefold()
        except EmailNotValidError:
            return None

    def valid_password(value):
        return isinstance(value, str) and 8 <= len(value) <= 128

    def limited(action, subject, maximum, seconds):
        bucket = int(time.time()) // seconds
        key = digest(f'{action}:{subject}:{bucket}')
        expires = datetime.fromtimestamp((bucket + 1) * seconds, timezone.utc) + timedelta(hours=1)
        try:
            record = db.rate_limits.find_one_and_update(
                {'_id': key}, {'$inc': {'count': 1}, '$setOnInsert': {'expires_at': expires}},
                upsert=True, return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:
            record = db.rate_limits.find_one_and_update({'_id': key}, {'$inc': {'count': 1}}, return_document=ReturnDocument.AFTER)
        return record['count'] > maximum

    def too_many():
        response = jsonify(error='Too many attempts. Please wait before trying again.')
        response.headers['Retry-After'] = '900'
        return response, 429

    def public_user(user):
        return {'name': user['name'], 'email': user['email']}

    def start_session(user):
        token = secrets.token_urlsafe(32)
        expires = utcnow() + timedelta(hours=hours)
        db.sessions.insert_one({'token_hash': digest(token), 'user_id': user['_id'],
                                'auth_version': user.get('auth_version', 0), 'expires_at': expires})
        return jsonify(token=token, expires_at=expires.isoformat(), user=public_user(user))

    def require_login(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            auth = request.headers.get('Authorization', '')
            token = auth[7:] if auth.startswith('Bearer ') else ''
            if not token or len(token) > 128:
                return jsonify(error='Please sign in to access the projects.'), 401
            session = db.sessions.find_one({'token_hash': digest(token), 'expires_at': {'$gt': utcnow()}})
            user = db.users.find_one({'_id': session['user_id']}) if session else None
            if not user or session.get('auth_version', 0) != user.get('auth_version', 0):
                return jsonify(error='Your session has expired. Please sign in again.'), 401
            g.user, g.session = user, session
            return view(*args, **kwargs)
        return wrapped

    @app.get('/health')
    def health():
        db.command('ping')
        return jsonify(status='ok')

    @app.get('/api/config')
    def capabilities():
        return jsonify(password_reset_available=smtp_ready, google_client_id=google_client_id)

    @app.post('/api/register')
    def register():
        if limited('register', request.remote_addr, 5, 3600):
            return too_many()
        data = body()
        email, password, name = email_from(data), data.get('password'), data.get('name')
        if not email or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            return jsonify(error='Enter your name and a valid email address.'), 400
        if not valid_password(password):
            return jsonify(error='Use a password between 8 and 128 characters.'), 400
        try:
            db.users.insert_one({'name': name.strip(), 'email': email,
                                 'password_hash': generate_password_hash(password, method='scrypt'),
                                 'created_at': utcnow(), 'auth_version': 0})
        except DuplicateKeyError:
            return jsonify(error='This email cannot be registered. Try signing in or resetting your password.'), 409
        # Registration does not open the directory; the visitor signs in next.
        return jsonify(message='Your account is created. Sign in to explore the projects.'), 201

    @app.post('/api/login')
    def login():
        if limited('login-ip', request.remote_addr, 30, 900):
            return too_many()
        data = body()
        email, password = email_from(data), data.get('password')
        if not email or not isinstance(password, str) or len(password) > 128:
            return jsonify(error='Email or password is incorrect.'), 401
        if limited('login-email', email, 10, 900):
            return too_many()
        user = db.users.find_one({'email': email})
        matched = check_password_hash(user.get('password_hash', dummy_hash) if user else dummy_hash, password)
        if not user or not matched:
            return jsonify(error='Email or password is incorrect.'), 401
        return start_session(user)

    @app.post('/api/google-login')
    def google_login():
        if not google_client_id:
            return jsonify(error='Google sign-in is not configured yet.'), 503
        # GIS uses a JavaScript callback and JSON fetch, not a cookie-based redirect.
        if request.headers.get('Origin') not in origins:
            return jsonify(error='Use the website to sign in with Google.'), 403
        if limited('google-login', request.remote_addr, 20, 900):
            return too_many()
        data = body()
        credential = data.get('credential')
        if not isinstance(credential, str) or not 1 <= len(credential) <= 12000:
            return jsonify(error='Google sign-in could not be verified. Please try again.'), 401
        try:
            claims = google_id_token.verify_oauth2_token(credential, partial(GoogleRequest(), timeout=10), google_client_id)
        except ValueError:
            return jsonify(error='Google sign-in could not be verified. Please try again.'), 401
        except (TransportError, OSError):
            return jsonify(error='Google verification is temporarily unavailable. Please try again.'), 503
        subject, email = claims.get('sub'), email_from(claims)
        if claims.get('iss') not in {'accounts.google.com', 'https://accounts.google.com'} or claims.get('aud') != google_client_id or not isinstance(subject, str) or not subject or len(subject) > 255 or not email or claims.get('email_verified') is not True:
            return jsonify(error='Google sign-in could not be verified. Please try again.'), 401
        user = db.users.find_one({'google_sub': subject})
        if user:
            return start_session(user)
        existing = db.users.find_one({'email': email})
        if existing:
            # Existing password registrations don't verify email ownership.
            # Require both login methods before linking, never match email alone.
            password = data.get('password')
            if not valid_password(password) or not existing.get('password_hash') or existing.get('google_sub'):
                return jsonify(error='An account already uses this email. Enter its website password, then choose Google again to link it.', code='password_required'), 409
            if not check_password_hash(existing['password_hash'], password):
                return jsonify(error='The website password is incorrect.'), 401
            try:
                linked = db.users.find_one_and_update({'_id': existing['_id'], 'google_sub': {'$exists': False}}, {'$set': {'google_sub': subject}}, return_document=ReturnDocument.AFTER)
            except DuplicateKeyError:
                linked = None
            if not linked:
                return jsonify(error='The account changed. Please sign in again.'), 409
            return start_session(linked)
        name = claims.get('name')
        name = name.strip()[:80] if isinstance(name, str) and name.strip() else email.split('@')[0][:80]
        try:
            record = {'name': name, 'email': email, 'google_sub': subject, 'created_at': utcnow(), 'auth_version': 0}
            record['_id'] = db.users.insert_one(record).inserted_id
        except DuplicateKeyError:
            # A simultaneous request may have created this Google user.
            record = db.users.find_one({'google_sub': subject})
            if not record:
                return jsonify(error='An account already uses this email. Sign in with its website password first.'), 409
        return start_session(record)

    @app.get('/api/me')
    @require_login
    def me():
        return jsonify(user=public_user(g.user), expires_at=g.session['expires_at'].isoformat())

    @app.post('/api/logout')
    @require_login
    def logout():
        db.sessions.delete_one({'_id': g.session['_id']})
        return jsonify(message='Signed out.')

    @app.get('/api/applications')
    @require_login
    def applications():
        fields = {'_id': 0, 'name': 1, 'description': 1, 'category': 1, 'url': 1, 'icon': 1}
        return jsonify(applications=list(db.applications.find({}, fields).sort([('sort_order', 1), ('name', 1)])))

    @app.post('/api/password-reset/request')
    def request_reset():
        if not smtp_ready:
            return jsonify(error='Password reset email is not configured yet.'), 503
        if limited('reset-ip', request.remote_addr, 5, 3600):
            return too_many()
        email = email_from(body())
        if not email:
            return jsonify(error='Enter a valid email address.'), 400
        if limited('reset-email', email, 3, 3600):
            return too_many()
        user = db.users.find_one({'email': email})
        if user:
            token = secrets.token_urlsafe(32)
            record = db.password_resets.insert_one({'token_hash': digest(token), 'user_id': user['_id'],
                                                    'expires_at': utcnow() + timedelta(minutes=30)})
            link = frontend + ('&' if '?' in frontend else '?') + urlencode({'reset_token': token})
            mail = EmailMessage()
            mail['Subject'] = 'Reset your password — Olga Matskovsky'
            mail['From'], mail['To'] = cfg['SMTP_FROM'], email
            mail.set_content(f'To reset your password, open this link within 30 minutes:\n\n{link}\n\nIf you did not request this, ignore this email.')
            try:
                use_ssl = cfg.get('SMTP_USE_SSL', 'false').lower() == 'true'
                smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
                smtp_options = {'timeout': 15}
                if use_ssl:
                    smtp_options['context'] = ssl.create_default_context()
                with smtp_class(cfg['SMTP_HOST'], int(cfg.get('SMTP_PORT', '587')), **smtp_options) as smtp:
                    if not use_ssl:
                        smtp.starttls(context=ssl.create_default_context())
                    if cfg.get('SMTP_USERNAME'):
                        smtp.login(cfg['SMTP_USERNAME'], cfg.get('SMTP_PASSWORD', ''))
                    smtp.send_message(mail)
            except (OSError, smtplib.SMTPException):
                db.password_resets.delete_one({'_id': record.inserted_id})
                app.logger.error('Password reset email delivery failed.')
        # Same response regardless of whether the account exists or email delivery fails.
        return jsonify(message='If this email has an account, a reset link will arrive shortly.')

    @app.post('/api/password-reset/confirm')
    def confirm_reset():
        if limited('reset-confirm', request.remote_addr, 10, 900):
            return too_many()
        data = body()
        token, password = data.get('token'), data.get('password')
        if not isinstance(token, str) or not 20 <= len(token) <= 128 or not valid_password(password):
            return jsonify(error='Use a valid reset link and a password between 8 and 128 characters.'), 400
        hashed = generate_password_hash(password, method='scrypt')
        record = db.password_resets.find_one_and_delete({'token_hash': digest(token), 'expires_at': {'$gt': utcnow()}})
        if not record:
            return jsonify(error='This reset link is invalid or expired. Request a new link.'), 400
        db.users.update_one({'_id': record['user_id']}, {'$set': {'password_hash': hashed}, '$inc': {'auth_version': 1}})
        db.sessions.delete_many({'user_id': record['user_id']})
        db.password_resets.delete_many({'user_id': record['user_id']})
        return jsonify(message='Your password is updated. Sign in with your new password.')

    return app


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    create_app().run(host='127.0.0.1', port=5000, debug=False)
