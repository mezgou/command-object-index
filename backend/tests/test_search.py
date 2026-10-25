import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
from search import candidate_forms, levenshtein, normalize, rank
from catalog import DEFAULT_COMMANDS
from main import clean_command


class SearchTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize('  ВКЛЮЧИ \t  свет  '), 'включи свет')

    def test_distance(self):
        self.assertEqual(levenshtein('кот', 'кот'), 0)
        self.assertEqual(levenshtein('кот', 'кит'), 1)
        self.assertEqual(levenshtein('', 'свет'), 4)
        self.assertEqual(levenshtein('  СВЕТ ', 'свет'), 0)

    def test_ranking_and_similarity(self):
        commands = [{'id': 1, 'text': 'выключи свет'}, {'id': 2, 'text': 'включи свет'}]
        ranked = rank('включи свет', commands)
        self.assertEqual([item['id'] for item in ranked], [2, 1])
        self.assertEqual(ranked[0]['distance'], 0)
        self.assertEqual(ranked[0]['similarity'], 100)

    def test_rank_by_relative_similarity_not_distance(self):
        commands = [{'id': 1, 'text': 'abc'}, {'id': 2, 'text': 'abcdefghij'}]
        ranked = rank('abcdefghi', commands)
        self.assertEqual([item['id'] for item in ranked], [2, 1])
        self.assertEqual(ranked[1]['similarity'], 0)

    def test_longer_command_wins_at_equal_distance(self):
        commands = [{'id': 1, 'text': 'abc'}, {'id': 2, 'text': 'abcde'}]
        ranked = rank('abcd', commands)
        self.assertEqual([item['id'] for item in ranked], [2, 1])
        self.assertAlmostEqual(ranked[0]['similarity'], 80)
        self.assertAlmostEqual(ranked[1]['similarity'], 100 * (1 - 1 / 3))

    def test_percentage_can_outweigh_smaller_distance(self):
        commands = [{'id': 1, 'text': 'abcdefgh'}, {'id': 2, 'text': 'abcdefghijklm'}]
        ranked = rank('abcdefghij', commands)
        self.assertEqual([item['id'] for item in ranked], [2, 1])
        self.assertGreater(ranked[0]['distance'], ranked[1]['distance'])

    def test_catalog_uses_semantic_blocks_and_special_commands(self):
        kitchen_light = next(command for command in DEFAULT_COMMANDS if command['text'] == 'включи свет на кухне')
        self.assertIn('включи', kitchen_light['actions'])
        self.assertIn('кухонный свет', kitchen_light['objects'])
        self.assertEqual(next(command for command in DEFAULT_COMMANDS if command['text'] == 'дальше'), {'text': 'дальше'})

    def test_catalog_keeps_accusative_objects_and_empty_action_form(self):
        music = next(command for command in DEFAULT_COMMANDS if command['text'] == 'включи музыку')
        quieter = next(command for command in DEFAULT_COMMANDS if command['text'] == 'сделай тише')
        self.assertIn('музыку', music['objects'])
        self.assertIn('', quieter['actions'])
        self.assertIn('потише', quieter['objects'])

    def test_empty_action_is_valid_but_empty_object_is_not(self):
        self.assertEqual(clean_command({'text': 'тише', 'actions': ['']}), {'text': 'тише', 'actions': ['']})
        with self.assertRaises(ValueError):
            clean_command({'text': 'тише', 'objects': ['']})

    def test_search_uses_action_object_combinations_in_both_orders(self):
        command = {
            'id': 1,
            'text': 'включи свет на кухне',
            'actions': ['включи'],
            'objects': ['кухонный свет'],
        }
        self.assertEqual(candidate_forms(command), ['включи свет на кухне', 'включи кухонный свет', 'кухонный свет включи'])
        direct = rank('включи кухонный свет', [command])[0]
        reversed_order = rank('кухонный свет включи', [command])[0]
        self.assertEqual((direct['distance'], direct['matched_text']), (0, 'включи кухонный свет'))
        self.assertEqual((reversed_order['distance'], reversed_order['matched_text']), (0, 'кухонный свет включи'))

    def test_search_uses_empty_action_with_object(self):
        command = {'id': 1, 'text': 'сделай тише', 'actions': ['сделай', ''], 'objects': ['тише']}
        result = rank('тише', [command])[0]
        self.assertEqual((result['distance'], result['matched_text'], result['similarity']), (0, 'тише', 100))


if __name__ == '__main__':
    unittest.main()
