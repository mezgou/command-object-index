import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from algo.levenshtein_normalized import search
from algo.normalization import normalize_text


class NormalizationTests(unittest.TestCase):
    def test_layout_case_punctuation_and_letter_runs(self):
        self.assertEqual(normalize_text('cltkfq nbit').text, 'сделай тише')
        self.assertEqual(normalize_text('включи cdtn').text, 'включи свет')
        self.assertEqual(normalize_text('Включи робот-пылесос!').text, 'включи робот пылесос')
        self.assertEqual(normalize_text('задёрни шторы').text, 'задерни шторы')
        self.assertEqual(normalize_text('сделай теплеее').text, 'сделай теплее')

    def test_fillers_parameters_and_repeats(self):
        self.assertEqual(normalize_text('Алиса, включи пожалуйста свет на кухне').text, 'включи свет на кухне')
        self.assertEqual(normalize_text('поставь будильник на семь утра').text, 'поставь будильник')
        self.assertEqual(normalize_text('включи кондиционер на 22 градуса').text, 'включи кондиционер')
        self.assertEqual(normalize_text('отмени будильник на завтра').text, 'отмени будильник')
        self.assertEqual(normalize_text('стоп стоп стоп').text, 'стоп')

    def test_meaningful_words_survive(self):
        self.assertEqual(normalize_text('поставь на паузу').text, 'поставь на паузу')
        self.assertEqual(normalize_text('позвони мне').text, 'позвони мне')
        self.assertEqual(normalize_text('выключи свет в спальне').text, 'выключи свет в спальне')
        self.assertEqual(normalize_text('пожалуйста').text, 'пожалуйста')
        self.assertEqual(normalize_text('какой сегодня день').text, 'какой сегодня день')

    def test_negation_is_kept_and_flagged(self):
        result = normalize_text('не включай свет')
        self.assertTrue(result.negated)
        self.assertEqual(result.text, 'не включай свет')
        self.assertFalse(normalize_text('включи свет').negated)
        self.assertTrue(normalize_text('не надо закрывать шторы').negated)
        self.assertFalse(normalize_text('поставь не паузу').negated)

    def test_explanation(self):
        result = normalize_text('алиса drk.xb')
        self.assertEqual(result.layout_fixed, [('drk.xb', 'включи')])
        self.assertEqual(result.removed, ['алиса'])


class NormalizedLevenshteinTests(unittest.TestCase):
    def setUp(self):
        self.block = {'index': 1, 'text': 'включи свет на кухне', 'actions': ['включи'], 'objects': ['свет на кухне']}

    def test_noise_and_layout_match_fully(self):
        self.assertEqual(search('алиса, включи пожалуйста свет на кухне', [self.block])[0]['score'], 1)
        self.assertEqual(search('drk.xb cdtn yf re[yt', [self.block])[0]['score'], 1)

    def test_returns_original_form(self):
        block = {'index': 2, 'text': 'включи пылесос', 'actions': ['включи'], 'objects': ['робот-пылесос']}
        self.assertEqual(search('включи робот пылесос', [block])[0], {'index': 2, 'text': 'включи робот-пылесос', 'score': 1})

    def test_negation_gives_zero_score(self):
        self.assertEqual(search('не включай свет на кухне', [self.block])[0]['score'], 0)


if __name__ == '__main__':
    unittest.main()
