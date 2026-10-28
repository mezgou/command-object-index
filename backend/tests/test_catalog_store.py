import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import Request, urlopen

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'backend', 'app'))

import main
from algo.registry import run_algorithms


class CatalogStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path_patch = patch.object(main, 'DATA_PATH', os.path.join(self.directory.name, 'commands.json'))
        self.snapshot_patch = patch.object(main, '_SNAPSHOT', None)
        self.path_patch.start()
        self.snapshot_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(self.snapshot_patch.stop)

    def test_search_uses_prepared_snapshot_without_reading_or_rebuilding(self):
        snapshot = main.catalog_snapshot()
        self.assertEqual(set(snapshot.indexes), {'levenshtein', 'tfidf-char', 'structured'})
        with patch.object(main, 'load_commands', side_effect=AssertionError('лишнее чтение')):
            with patch('algo.structured.Lexicon', side_effect=AssertionError('лишняя перестройка')):
                before = dict(snapshot.indexes)
                for _ in range(2):
                    run_algorithms(['structured'], 'включи свет на кухне', main.catalog_snapshot())
                self.assertTrue(all(snapshot.indexes[key] is value for key, value in before.items()))

    def test_failed_save_keeps_old_snapshot(self):
        snapshot = main.catalog_snapshot()
        with patch.object(main, 'save_commands', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                main.update_catalog([{'text': 'новая команда'}])
        self.assertIs(main.catalog_snapshot(), snapshot)

    def test_web_changes_replace_snapshot_and_search_index(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), main.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(method, path, payload=None):
            data = None if payload is None else json.dumps(payload).encode('utf-8')
            req = Request(f'http://127.0.0.1:{server.server_port}{path}', data=data, method=method)
            with urlopen(req) as response:
                return json.load(response)

        request('DELETE', '/api/commands')
        empty = main.catalog_snapshot()
        self.assertEqual(empty, [])
        request('POST', '/api/commands', {'text': 'особая команда'})
        added = main.catalog_snapshot()
        self.assertIsNot(added, empty)
        results = request('POST', '/api/search', {'query': 'особая команда', 'algorithms': ['levenshtein-combinations']})
        self.assertEqual(results['algorithms'][0]['results'][0]['score'], 1)
        request('PUT', '/api/commands/1', {'text': 'другая команда'})
        self.assertEqual(main.catalog_snapshot()[0]['text'], 'другая команда')
        self.assertEqual(added[0]['text'], 'особая команда')
        results = request('POST', '/api/search', {'query': 'другая команда', 'algorithms': ['levenshtein-combinations']})
        self.assertEqual(results['algorithms'][0]['results'][0]['score'], 1)
        request('DELETE', '/api/commands/1')
        self.assertEqual(main.catalog_snapshot(), [])
        request('POST', '/api/commands/examples')
        self.assertGreater(len(main.catalog_snapshot()), 0)
        with open(main.DATA_PATH, encoding='utf-8') as file:
            self.assertEqual(len(json.load(file)), len(main.catalog_snapshot()))


if __name__ == '__main__':
    unittest.main()
