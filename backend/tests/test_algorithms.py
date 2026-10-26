import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'backend', 'app'))

from algo.levenshtein_combinations import search
from algo.registry import public_algorithms, run_algorithms
from algo.shared import candidate_forms, levenshtein, normalize
from catalog import DEFAULT_COMMANDS
from main import clean_command


class SharedTests(unittest.TestCase):
    def test_normalization_and_distance(self):
        self.assertEqual(normalize('  ВКЛЮЧИ \t  свет  '), 'включи свет')
        self.assertEqual(levenshtein('кот', 'кит'), 1)
        self.assertEqual(levenshtein('', 'свет'), 4)

    def test_candidate_forms_include_both_orders_and_empty_action(self):
        block = {'index': 1, 'text': 'сделай тише', 'actions': ['сделай', ''], 'objects': ['тише']}
        self.assertEqual(candidate_forms(block), ['сделай тише', 'тише сделай', 'тише'])


class LevenshteinAlgorithmTests(unittest.TestCase):
    def setUp(self):
        self.block = {
            'index': 7,
            'text': 'включи свет на кухне',
            'actions': ['включи'],
            'objects': ['кухонный свет'],
        }

    def test_contract_and_direct_combination(self):
        result = search('включи кухонный свет', [self.block])
        self.assertEqual(result, [{'index': 7, 'text': 'включи кухонный свет', 'score': 1}])

    def test_reversed_combination(self):
        result = search('кухонный свет включи', [self.block])[0]
        self.assertEqual((result['index'], result['text'], result['score']), (7, 'кухонный свет включи', 1))

    def test_empty_action_can_match_object_only(self):
        block = {'index': 3, 'text': 'сделай тише', 'actions': ['сделай', ''], 'objects': ['тише']}
        self.assertEqual(search('тише', [block])[0], {'index': 3, 'text': 'тише', 'score': 1})

    def test_results_are_ranked_by_score(self):
        blocks = [
            {'index': 1, 'text': 'включи свет'},
            {'index': 2, 'text': 'выключи свет'},
        ]
        self.assertEqual([item['index'] for item in search('включи свет', blocks)], [1, 2])


class RegistryAndDataTests(unittest.TestCase):
    def test_registry_exposes_configured_algorithm(self):
        algorithms = public_algorithms()
        self.assertIn({
            'id': 'levenshtein-combinations',
            'name': 'Левенштейн: комбинации',
            'description': 'Сравнивает запрос со всеми комбинациями «действие + объект» и «объект + действие».',
        }, algorithms)
        self.assertTrue(all(set(algorithm) == {'id', 'name', 'description'} for algorithm in algorithms))
        self.assertEqual(len({algorithm['id'] for algorithm in algorithms}), len(algorithms))

    def test_every_configured_algorithm_keeps_contract(self):
        blocks = [{**command, 'index': position + 1} for position, command in enumerate(DEFAULT_COMMANDS)]
        identifiers = [algorithm['id'] for algorithm in public_algorithms()]
        for identifier in identifiers:
            result = run_algorithms([identifier], 'включи свет на кухне', blocks)[0]['results']
            self.assertTrue(result, identifier)
            scores = [item['score'] for item in result]
            self.assertEqual(scores, sorted(scores, reverse=True), identifier)

    def test_registry_runs_and_validates_algorithm(self):
        blocks = [{'index': 1, 'text': 'дальше'}]
        result = run_algorithms(['levenshtein-combinations'], 'дальше', blocks)
        self.assertEqual(result[0]['results'], [{'index': 1, 'text': 'дальше', 'score': 1.0}])

    def test_catalog_and_empty_action_validation(self):
        music = next(command for command in DEFAULT_COMMANDS if command['text'] == 'включи музыку')
        quieter = next(command for command in DEFAULT_COMMANDS if command['text'] == 'сделай тише')
        self.assertIn('музыку', music['objects'])
        self.assertIn('', quieter['actions'])
        self.assertEqual(clean_command({'text': 'тише', 'actions': ['']}), {'text': 'тише', 'actions': ['']})
        with self.assertRaises(ValueError):
            clean_command({'text': 'тише', 'objects': ['']})


if __name__ == '__main__':
    unittest.main()
