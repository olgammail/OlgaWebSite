// Dependency-free local preview. Binds only to your computer.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const allowed = new Set(['index.html', 'styles.css', 'landing.css', 'app.js', 'config.js', 'workspace-preview.local.html']);
const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript' };
http.createServer((req, res) => {
  let filename;
  try { filename = decodeURIComponent(new URL(req.url, 'http://localhost').pathname).slice(1) || 'index.html'; }
  catch { res.writeHead(400); return res.end('Bad request'); }
  if (!allowed.has(filename)) { res.writeHead(404); return res.end('Not found'); }
  fs.readFile(path.join(root, filename), (error, data) => {
    if (error) { res.writeHead(500); return res.end('Unable to read file'); }
    res.writeHead(200, { 'Content-Type': `${types[path.extname(filename)]}; charset=utf-8`, 'Cache-Control': 'no-store' });
    res.end(data);
  });
}).listen(4173, '127.0.0.1', () => console.log('Preview: http://localhost:4173'));
