import unittest
from unittest.mock import patch, Mock
from datetime import timedelta
import mongomock
from backend.app import create_app, digest, utcnow

class GitHubTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True).github_test
        self.client = create_app(self.db, {'ALLOWED_ORIGINS':'http://localhost:4173','FRONTEND_URL':'http://localhost:4173/','GITHUB_CLIENT_ID':'test-client','GITHUB_CLIENT_SECRET':'test-secret','SMTP_HOST':'','SMTP_FROM':'','RENDER':''}).test_client()
        self.headers = {'Origin':'http://localhost:4173'}
        self.key = 'browser-key-' + 'a'*32
    def start(self):
        result=self.client.post('/api/github/start',json={'browser_key':self.key},headers=self.headers)
        self.assertEqual(result.status_code,200)
        self.assertIn('code_challenge_method=S256',result.json['authorize_url'])
        return result.json['state']
    def finish(self,state,key=None):
        return self.client.post('/api/github/finish',json={'code':'github-code','state':state,'browser_key':key or self.key},headers=self.headers)
    def reply(self,data):
        response=Mock();response.json.return_value=data;return response
    def test_invalid_state_browser_and_expiry_do_not_call_github(self):
        state=self.start()
        with patch('backend.app.http_requests.post') as post:
            self.assertEqual(self.finish(state,'wrong-browser').status_code,401)
            self.assertEqual(self.finish('unknown-state').status_code,401)
            self.db.oauth_attempts.update_many({}, {'$set':{'expires_at':utcnow()-timedelta(seconds=1)}})
            self.assertEqual(self.finish(state).status_code,401)
            post.assert_not_called()
    @patch('backend.app.http_requests.get')
    @patch('backend.app.http_requests.post')
    def test_verified_account_stable_identity_and_one_use_state(self,post,get):
        post.return_value=self.reply({'access_token':'private-access-token'})
        get.side_effect=[self.reply({'id':123,'login':'visitor'}),self.reply([{'email':'visitor@example.com','verified':True,'primary':True}])]
        state=self.start();response=self.finish(state)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.db.users.find_one()['github_id'],'123')
        self.assertNotIn('access_token',self.db.users.find_one())
        self.assertNotIn('private-access-token',str(list(self.db.sessions.find())))
        self.assertEqual(self.finish(state).status_code,401)
        self.assertEqual(post.call_count,1)
        payload=post.call_args.kwargs['json']
        self.assertIn('code_verifier',payload)
        self.assertEqual(payload['redirect_uri'],'http://localhost:4173/')
    @patch('backend.app.http_requests.get')
    @patch('backend.app.http_requests.post')
    def test_unverified_email_rejected(self,post,get):
        post.return_value=self.reply({'access_token':'private-access-token'})
        get.side_effect=[self.reply({'id':123}),self.reply([{'email':'visitor@example.com','verified':False}])]
        self.assertEqual(self.finish(self.start()).status_code,401)
        self.assertEqual(self.db.users.count_documents({}),0)
    @patch('backend.app.http_requests.get')
    @patch('backend.app.http_requests.post')
    def test_link_requires_password_and_ticket_is_one_use(self,post,get):
        self.client.post('/api/register',json={'name':'Visitor','email':'visitor@example.com','password':'Original-password-123'})
        post.return_value=self.reply({'access_token':'private-access-token'})
        get.side_effect=[self.reply({'id':123,'login':'visitor'}),self.reply([{'email':'visitor@example.com','verified':True}])]
        response=self.finish(self.start());self.assertEqual(response.status_code,409)
        ticket=response.json['link_ticket'];self.assertNotIn('github_id',self.db.users.find_one())
        payload={'link_ticket':ticket,'password':'Original-password-123'}
        self.assertEqual(self.client.post('/api/github/link',json=payload,headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/github/link',json=payload,headers=self.headers).status_code,401)
        self.assertEqual(self.db.users.count_documents({}),1)
        self.assertEqual(self.db.users.find_one()['github_id'],'123')
