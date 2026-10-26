import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'backend', 'app'))

from evaluation.run import Rules, decide, expected_groups, load_catalog, load_dataset, outcome, validate


class DatasetTests(unittest.TestCase):
    def test_dataset_and_rules_match_catalog(self):
        problems, warnings = validate(load_dataset(), load_catalog(), Rules())
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.rules = Rules()

    @staticmethod
    def ranking(*pairs):
        return [{'command': command, 'score': score, 'form': command} for command, score in pairs]

    def test_threshold_and_margin_skip_equivalent_commands(self):
        ranking = self.ranking(('включи свет на кухне', 0.9), ('зажги свет на кухне', 0.89), ('выключи свет на кухне', 0.8))
        self.assertEqual(decide(ranking, 0.5, 0.1, self.rules), 'включи свет на кухне')
        self.assertIsNone(decide(ranking, 0.95, 0.0, self.rules))
        self.assertIsNone(decide(ranking, 0.5, 0.15, self.rules))
        self.assertIsNone(decide([], 0.0, 0.0, self.rules))

    def test_outcomes(self):
        single = expected_groups({'expected': ['открой шторы в спальне']})
        self.assertEqual(outcome(single, 'открой шторы в спальне', self.rules), 'correct')
        self.assertEqual(outcome(single, 'открой дверь', self.rules), 'critical')
        self.assertEqual(outcome(single, 'закрой шторы в спальне', self.rules), 'critical')
        self.assertEqual(outcome(single, 'включи музыку', self.rules), 'wrong')
        self.assertEqual(outcome(single, None, self.rules), 'false_refusal')
        self.assertEqual(outcome([], None, self.rules), 'correct_refusal')
        self.assertEqual(outcome([], 'открой дверь', self.rules), 'critical')
        ambiguous = expected_groups({'expected': [['выключи свет на кухне'], ['выключи свет в спальне']]})
        self.assertEqual(outcome(ambiguous, None, self.rules), 'correct_refusal')
        self.assertEqual(outcome(ambiguous, 'выключи свет на кухне', self.rules), 'wrong')


if __name__ == '__main__':
    unittest.main()
