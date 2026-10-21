import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
from search import levenshtein, normalize, rank


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


if __name__ == '__main__':
    unittest.main()
