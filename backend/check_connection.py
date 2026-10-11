"""Read-only connection diagnostic. Does not create databases or indexes."""
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app import connection_error_summary


def main():
    load_dotenv(Path(__file__).with_name('.env'))
    uri = os.environ.get('MONGODB_URI')
    if not uri:
        print('FAIL: MONGODB_URI is missing from backend/.env.')
        return 1
    print('Loaded connection settings. Credentials will not be displayed.', flush=True)
    print('Sending MongoDB ping. No collections or indexes will be created.', flush=True)
    client = None
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000)
        client.admin.command('ping')
    except PyMongoError as error:
        print('FAIL:', connection_error_summary(error))
        return 1
    finally:
        if client is not None:
            client.close()
    print('SUCCESS: MongoDB answered ping. Connection and authentication work.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
