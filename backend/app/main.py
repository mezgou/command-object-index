import copy
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from algo.registry import public_algorithms, run_algorithms
from algo.shared import normalize
from catalog import DEFAULT_COMMANDS

DATA_PATH = os.environ.get('DATA_PATH', '/data/commands.json')
LOCK = threading.Lock()


def clean_words(value, allow_empty=False):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError()
    words = []
    for item in value:
        item = ' '.join(item.split())
        if not item and allow_empty:
            if '' not in words:
                words.append('')
            continue
        if not item or len(item) > 200:
            raise ValueError()
        if normalize(item) not in {normalize(word) for word in words}:
            words.append(item)
    return words


def clean_command(value):
    if not isinstance(value, dict) or not isinstance(value.get('text'), str):
        raise ValueError()
    text = ' '.join(value['text'].split())
    if not text or len(text) > 200:
        raise ValueError()
    command = {'text': text}
    for field in ('actions', 'objects'):
        words = clean_words(value.get(field), allow_empty=field == 'actions')
        if words:
            command[field] = words
    return command


def load_commands():
    if not os.path.exists(DATA_PATH):
        return copy.deepcopy(DEFAULT_COMMANDS)
    with open(DATA_PATH, encoding='utf-8') as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError('Файл команд должен содержать список')
    return [clean_command(command) for command in data]


def save_commands(commands):
    os.makedirs(os.path.dirname(os.path.abspath(DATA_PATH)), exist_ok=True)
    temporary = f'{DATA_PATH}.tmp'
    with open(temporary, 'w', encoding='utf-8') as file:
        json.dump(commands, file, ensure_ascii=False, indent=2)
        file.write('\n')
    os.replace(temporary, DATA_PATH)


def with_ids(commands):
    return [{**command, 'id': index + 1, 'index': index + 1} for index, command in enumerate(commands)]


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_payload(self):
        size = int(self.headers.get('Content-Length', '0'))
        if not 1 <= size <= 16384:
            raise ValueError()
        return json.loads(self.rfile.read(size))

    def commands(self):
        with LOCK:
            return load_commands()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/api/algorithms':
            return self.respond(200, {'algorithms': public_algorithms()})
        if url.path != '/api/commands':
            return self.respond(404, {'error': 'Не найдено'})
        self.respond(200, {'commands': with_ids(self.commands())})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/search':
            try:
                payload = self.read_payload()
                query = payload.get('query')
                algorithm_ids = payload.get('algorithms')
                if not isinstance(query, str) or not query.strip() or len(query) > 200:
                    raise ValueError('Введите запрос длиной до 200 символов')
                if not isinstance(algorithm_ids, list) or not 1 <= len(algorithm_ids) <= 3 or any(not isinstance(item, str) for item in algorithm_ids):
                    raise ValueError('Выберите от одного до трёх алгоритмов')
                algorithms = run_algorithms(algorithm_ids, query, with_ids(self.commands()))
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, AttributeError) as error:
                return self.respond(400, {'error': str(error) or 'Некорректный запрос'})
            return self.respond(200, {'algorithms': algorithms})
        if path == '/api/commands/examples':
            with LOCK:
                save_commands(copy.deepcopy(DEFAULT_COMMANDS))
            return self.respond(200, {'ok': True})
        if path != '/api/commands':
            return self.respond(404, {'error': 'Не найдено'})
        try:
            command = clean_command(self.read_payload())
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return self.respond(400, {'error': 'Заполните текст команды и корректные варианты длиной до 200 символов'})
        with LOCK:
            commands = load_commands()
            if any(normalize(item['text']) == normalize(command['text']) for item in commands):
                return self.respond(409, {'error': 'Такая команда уже есть в списке'})
            commands.append(command)
            save_commands(commands)
        self.respond(201, {**command, 'id': len(commands)})

    def do_PUT(self):
        prefix = '/api/commands/'
        path = urlparse(self.path).path
        if not path.startswith(prefix) or not path[len(prefix):].isdigit():
            return self.respond(404, {'error': 'Не найдено'})
        try:
            command = clean_command(self.read_payload())
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return self.respond(400, {'error': 'Заполните текст команды и корректные варианты длиной до 200 символов'})
        index = int(path[len(prefix):]) - 1
        with LOCK:
            commands = load_commands()
            if not 0 <= index < len(commands):
                return self.respond(404, {'error': 'Команда не найдена'})
            if any(i != index and normalize(item['text']) == normalize(command['text']) for i, item in enumerate(commands)):
                return self.respond(409, {'error': 'Такая команда уже есть в списке'})
            commands[index] = command
            save_commands(commands)
        self.respond(200, {**command, 'id': index + 1})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path == '/api/commands':
            with LOCK:
                save_commands([])
            return self.respond(200, {'ok': True})
        prefix = '/api/commands/'
        if not path.startswith(prefix) or not path[len(prefix):].isdigit():
            return self.respond(404, {'error': 'Не найдено'})
        index = int(path[len(prefix):]) - 1
        with LOCK:
            commands = load_commands()
            if not 0 <= index < len(commands):
                return self.respond(404, {'error': 'Команда не найдена'})
            commands.pop(index)
            save_commands(commands)
        self.respond(200, {'ok': True})


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8000'))), Handler).serve_forever()
