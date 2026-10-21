import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from search import rank

DB_PATH = os.environ.get('DB_PATH', '/data/commands.db')
EXAMPLES = ['включи свет', 'выключи свет', 'приглуши свет', 'открой окно',
            'закрой окно', 'открой дверь', 'закрой дверь', 'включи музыку',
            'выключи музыку', 'сделай громче', 'сделай тише', 'поставь на паузу',
            'покажи погоду', 'установи таймер', 'который час', 'найди телефон',
            'включи пылесос', 'останови пылесос']


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def initialize():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS commands (id INTEGER PRIMARY KEY, text TEXT NOT NULL)')


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path != '/api/commands':
            return self.respond(404, {'error': 'Не найдено'})
        query = parse_qs(url.query, keep_blank_values=True).get('q', [''])[0]
        if len(query) > 200:
            return self.respond(400, {'error': 'Запрос слишком длинный (максимум 200 символов)'})
        with connect() as db:
            commands = [dict(row) for row in db.execute('SELECT id, text FROM commands')]
        self.respond(200, {'commands': rank(query, commands) if query.strip() else commands})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/commands/examples':
            with connect() as db:
                db.execute('DELETE FROM commands')
                db.executemany('INSERT INTO commands (text) VALUES (?)', [(x,) for x in EXAMPLES])
            return self.respond(200, {'ok': True})
        if path != '/api/commands':
            return self.respond(404, {'error': 'Не найдено'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size > 4096 or size < 1:
                raise ValueError()
            payload = json.loads(self.rfile.read(size))
            text = payload.get('text')
            if not isinstance(text, str):
                raise ValueError()
            text = ' '.join(text.split())
            if not text or len(text) > 200:
                raise ValueError()
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return self.respond(400, {'error': 'Введите команду длиной до 200 символов'})
        with connect() as db:
            if any(' '.join(row['text'].lower().split()) == text.lower() for row in db.execute('SELECT text FROM commands')):
                return self.respond(409, {'error': 'Такая команда уже есть в списке'})
            cursor = db.execute('INSERT INTO commands (text) VALUES (?)', (text,))
            self.respond(201, {'id': cursor.lastrowid, 'text': text})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path == '/api/commands':
            with connect() as db:
                db.execute('DELETE FROM commands')
            return self.respond(200, {'ok': True})
        prefix = '/api/commands/'
        if path.startswith(prefix) and path[len(prefix):].isdigit():
            with connect() as db:
                cursor = db.execute('DELETE FROM commands WHERE id = ?', (int(path[len(prefix):]),))
            return self.respond(200 if cursor.rowcount else 404, {'ok': bool(cursor.rowcount)})
        self.respond(404, {'error': 'Не найдено'})


if __name__ == '__main__':
    initialize()
    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8000'))), Handler).serve_forever()
