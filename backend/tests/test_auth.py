import unittest
from datetime import timedelta
from unittest.mock import patch
import mongomock
from backend.app import create_app, digest, utcnow


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True).test_portal
        self.settings = {'ALLOWED_ORIGINS': 'http://localhost:4173', 'FRONTEND_URL': 'http://localhost:4173/', 'SMTP_HOST': '', 'SMTP_FROM': '', 'RENDER': ''}
        self.app = create_app(self.db, self.settings)
        self.client = self.app.test_client()
        self.account = {'name': 'Test Visitor', 'email': 'visitor@example.com', 'password': 'Testing-password-123'}

    def register(self):
        return self.client.post('/api/register', json=self.account)

    def login(self):
        self.register()
        response = self.client.post('/api/login', json=self.account)
        self.assertEqual(response.status_code, 200)
        return response.json['token']

    def auth(self, token):
        return {'Authorization': f'Bearer {token}'}

    def test_registration_hashes_password_and_requires_subsequent_login(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        user = self.db.users.find_one()
        self.assertTrue(user['password_hash'].startswith('scrypt:'))
        self.assertNotEqual(user['password_hash'], self.account['password'])
        self.assertNotIn('password', user)
        self.assertNotIn('token', response.json)
        self.assertEqual(self.db.sessions.count_documents({}), 0)
        self.assertEqual(self.client.get('/api/applications').status_code, 401)

    def test_duplicate_email_is_case_insensitive(self):
        self.register()
        self.account['email'] = 'VISITOR@EXAMPLE.COM'
        self.assertEqual(self.register().status_code, 409)
        self.assertEqual(self.db.users.count_documents({}), 1)

    def test_registration_validation(self):
        for change in [{'name': ''}, {'email': 'invalid'}, {'password': 'short'}, {'password': 'a' * 129}, {'email': {'$ne': None}}]:
            response = self.client.post('/api/register', json={**self.account, **change})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.db.users.count_documents({}), 0)

    def test_wrong_password_and_unknown_account_have_same_error(self):
        self.register()
        wrong = self.client.post('/api/login', json={**self.account, 'password': 'wrong-password'})
        unknown = self.client.post('/api/login', json={**self.account, 'email': 'unknown@example.com'})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json, unknown.json)
        self.assertEqual(self.db.sessions.count_documents({}), 0)

    def test_login_stores_only_token_hash_and_returns_only_public_user(self):
        token = self.login()
        self.assertEqual(self.db.sessions.find_one()['token_hash'], digest(token))
        self.assertNotIn('token', self.db.sessions.find_one())
        response = self.client.get('/api/me', headers=self.auth(token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['user'], {'name': 'Test Visitor', 'email': 'visitor@example.com'})

    def test_directory_requires_real_token(self):
        self.db.applications.insert_one({'slug': 'game', 'name': 'Private game', 'url': 'https://example.com/game', 'sort_order': 1})
        response = self.client.get('/api/applications', headers=self.auth('fake-token'))
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Private game', response.get_data(as_text=True))
        response = self.client.get('/api/applications', headers=self.auth(self.login()))
        self.assertEqual(response.json['applications'][0]['name'], 'Private game')
        self.assertNotIn('_id', response.json['applications'][0])

    def test_expiry_checked_before_background_ttl_cleanup(self):
        token = self.login()
        self.db.sessions.update_one({}, {'$set': {'expires_at': utcnow() - timedelta(seconds=1)}})
        for path in ['/api/me', '/api/applications']:
            self.assertEqual(self.client.get(path, headers=self.auth(token)).status_code, 401)

    def test_logout_revokes_token(self):
        token = self.login()
        self.assertEqual(self.client.post('/api/logout', json={}, headers=self.auth(token)).status_code, 200)
        self.assertEqual(self.client.get('/api/me', headers=self.auth(token)).status_code, 401)

    def test_cors_rejects_untrusted_origins(self):
        allowed = self.client.options('/api/login', headers={'Origin': 'http://localhost:4173', 'Access-Control-Request-Method': 'POST'})
        self.assertEqual(allowed.status_code, 204)
        self.assertEqual(allowed.headers['Access-Control-Allow-Origin'], 'http://localhost:4173')
        rejected = self.client.post('/api/register', json=self.account, headers={'Origin': 'https://untrusted.example'})
        self.assertEqual(rejected.status_code, 403)
        self.assertNotIn('Access-Control-Allow-Origin', rejected.headers)
        self.assertEqual(self.db.users.count_documents({}), 0)

    def test_json_required(self):
        self.assertEqual(self.client.post('/api/login', data=self.account).status_code, 415)
        self.assertEqual(self.client.post('/api/login', data='not-json', content_type='application/json').status_code, 400)

    def test_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.client.post('/api/login', json=self.account).status_code, 401)
        self.assertEqual(self.client.post('/api/login', json=self.account).status_code, 429)

    def test_registration_rate_limit(self):
        for i in range(5):
            self.client.post('/api/register', json={**self.account, 'email': f'user{i}@example.com'})
        self.assertEqual(self.register().status_code, 429)

    def test_reset_unavailable_without_email_configuration(self):
        self.assertFalse(self.client.get('/api/config').json['password_reset_available'])
        self.assertEqual(self.client.post('/api/password-reset/request', json={'email': self.account['email']}).status_code, 503)

    def test_reset_is_single_use_and_revokes_all_sessions(self):
        token = self.login()
        reset_token = 'a-long-test-reset-token-12345'
        self.db.password_resets.insert_one({'token_hash': digest(reset_token), 'user_id': self.db.users.find_one()['_id'], 'expires_at': utcnow() + timedelta(minutes=30)})
        payload = {'token': reset_token, 'password': 'A-new-test-password-456'}
        self.assertEqual(self.client.post('/api/password-reset/confirm', json=payload).status_code, 200)
        self.assertEqual(self.client.get('/api/me', headers=self.auth(token)).status_code, 401)
        self.assertEqual(self.client.post('/api/password-reset/confirm', json=payload).status_code, 400)
        self.assertEqual(self.client.post('/api/login', json=self.account).status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={**self.account, 'password': payload['password']}).status_code, 200)

    def test_expired_reset_rejected(self):
        self.register()
        self.db.password_resets.insert_one({'token_hash': digest('expired-token-1234567890'), 'user_id': self.db.users.find_one()['_id'], 'expires_at': utcnow() - timedelta(seconds=1)})
        self.assertEqual(self.client.post('/api/password-reset/confirm', json={'token': 'expired-token-1234567890', 'password': 'New-password-123'}).status_code, 400)

    def test_reset_email_link_and_generic_response(self):
        self.register()
        app = create_app(self.db, {**self.settings, 'SMTP_HOST': 'smtp.example.com', 'SMTP_FROM': 'sender@example.com'})
        with patch('backend.app.smtplib.SMTP') as smtp:
            client = app.test_client()
            known = client.post('/api/password-reset/request', json={'email': self.account['email']})
            unknown = client.post('/api/password-reset/request', json={'email': 'unknown@example.com'})
            self.assertEqual(known.json, unknown.json)
            self.assertNotIn('token', known.json)
            mail = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertIn('http://localhost:4173/?reset_token=', mail.get_content())
            self.assertEqual(self.db.password_resets.count_documents({}), 1)


if __name__ == '__main__':
    unittest.main()
