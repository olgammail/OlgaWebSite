import unittest
from unittest.mock import patch
import mongomock
from backend.app import create_app

class GoogleTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True).google_test
        self.client = create_app(self.db, {'ALLOWED_ORIGINS': 'http://localhost:4173', 'FRONTEND_URL': 'http://localhost:4173/', 'GOOGLE_CLIENT_ID': 'test-client', 'SMTP_HOST': '', 'SMTP_FROM': '', 'RENDER': ''}).test_client()
        self.claims = {'sub': 'google-user-1', 'email': 'visitor@example.com', 'email_verified': True, 'name': 'Google Visitor', 'iss': 'https://accounts.google.com', 'aud': 'test-client'}
        self.headers = {'Origin': 'http://localhost:4173'}
    def sign_in(self, **extra):
        return self.client.post('/api/google-login', json={'credential': 'signed-token', **extra}, headers=self.headers)
    @patch('backend.app.google_id_token.verify_oauth2_token')
    def test_new_and_returning_user_and_password_login(self, verify):
        verify.return_value = self.claims
        first = self.sign_in()
        self.assertEqual(first.status_code, 200)
        verify.assert_called_with('signed-token', unittest.mock.ANY, 'test-client')
        self.assertEqual(self.db.users.count_documents({}), 1)
        self.assertNotIn('password_hash', self.db.users.find_one())
        self.assertNotIn('credential', self.db.users.find_one())
        self.assertEqual(self.sign_in().status_code, 200)
        self.assertEqual(self.db.users.count_documents({}), 1)
        self.assertEqual(self.client.post('/api/login', json={'email': self.claims['email'], 'password': 'incorrect-pass'}).status_code, 401)
        auth = {'Authorization': 'Bearer ' + first.json['token']}
        self.assertEqual(self.client.get('/api/me', headers=auth).status_code, 200)
        self.client.post('/api/logout', json={}, headers=auth)
        self.assertEqual(self.client.get('/api/me', headers=auth).status_code, 401)
    @patch('backend.app.google_id_token.verify_oauth2_token')
    def test_existing_account_requires_password_before_link(self, verify):
        verify.return_value = self.claims
        self.client.post('/api/register', json={'email': self.claims['email'], 'name': 'Visitor', 'password': 'Original-password-123'})
        self.assertEqual(self.sign_in().status_code, 409)
        self.assertEqual(self.sign_in(password='wrong-password').status_code, 401)
        self.assertNotIn('google_sub', self.db.users.find_one())
        self.assertEqual(self.sign_in(password='Original-password-123').status_code, 200)
        self.assertEqual(self.db.users.count_documents({}), 1)
        self.assertEqual(self.db.users.find_one()['google_sub'], self.claims['sub'])
    @patch('backend.app.google_id_token.verify_oauth2_token')
    def test_invalid_token_and_claims_create_no_account(self, verify):
        verify.side_effect = ValueError('expired or forged')
        self.assertEqual(self.sign_in().status_code, 401)
        verify.side_effect = None
        for change in [{'aud': 'other-client'}, {'iss': 'attacker'}, {'email_verified': False}, {'sub': ''}]:
            verify.return_value = {**self.claims, **change}
            self.assertEqual(self.sign_in().status_code, 401)
        self.assertEqual(self.db.users.count_documents({}), 0)
    def test_origin_and_malformed_requests_rejected(self):
        self.assertEqual(self.client.post('/api/google-login', json={'credential': 'token'}).status_code, 403)
        self.assertEqual(self.client.post('/api/google-login', json={'credential': {'bad': 'value'}}, headers=self.headers).status_code, 401)
    @patch('backend.app.google_id_token.verify_oauth2_token')
    def test_email_collision_cannot_link_different_google_subject(self, verify):
        verify.return_value = self.claims
        self.sign_in()
        verify.return_value = {**self.claims, 'sub': 'different-google-user'}
        self.assertEqual(self.sign_in().status_code, 409)
        self.assertEqual(self.db.users.find_one()['google_sub'], 'google-user-1')
