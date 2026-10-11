"""Owner-only local command to add project records. No public write API."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from app import create_app

parser = argparse.ArgumentParser(description='Load project records into MongoDB.')
parser.add_argument('command', choices=['seed-projects'])
parser.add_argument('--file', default='projects.example.json')
args = parser.parse_args()
projects = json.loads(Path(args.file).read_text(encoding='utf-8'))
if not isinstance(projects, list):
    raise ValueError('The project file must contain a JSON list.')
for project in projects:
    if not isinstance(project, dict) or not all(isinstance(project.get(key), str) and project[key].strip() for key in ['slug', 'name', 'description', 'category']):
        raise ValueError('Each project needs a slug, name, description, and category.')
    url = project.get('url', '')
    parsed = urlsplit(url)
    if url and (parsed.scheme not in {'https', 'http'} or not parsed.netloc or parsed.username or parsed.password):
        raise ValueError('Project URLs must be HTTP/HTTPS without embedded credentials.')
    if not isinstance(project.get('sort_order', 0), int):
        raise ValueError('sort_order must be an integer.')
app = create_app()
db = app.extensions['database']
for project in projects:
    clean = {key: project.get(key, default) for key, default in {
        'slug': '', 'name': '', 'description': '', 'category': 'Tools', 'url': '', 'icon': '↗', 'sort_order': 0}.items()}
    db.applications.update_one({'slug': clean['slug']}, {'$set': clean}, upsert=True)
print(f'Loaded {len(projects)} project(s). Existing projects with other slugs were kept.')
