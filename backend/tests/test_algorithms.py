import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'backend', 'app'))

from algo import structured, tfidf_char
from algo.levenshtein_combinations import search
from algo.registry import public_algorithms, run_algorithms, validate_results
from algo.shared import DeletionIndex, candidate_forms, levenshtein, max_edits, normalize, osa, tokens
from catalog import DEFAULT_COMMANDS
from main import clean_command

BLOCKS = [{**command, 'id': index + 1, 'index': index + 1} for index, command in enumerate(DEFAULT_COMMANDS)]
TEXT = {block['index']: block['text'] for block in BLOCKS}


def understood(query, blocks=BLOCKS):
    """Решение и лучший блок каждой команды структурного индекса."""
    results = structured.search(query, blocks)
    chosen = {}
    for result in results:
        chosen.setdefault(result['command'], TEXT.get(result['index'], result['index']))
    return (results[0]['decision'] if results else 'reject'), [chosen[number] for number in sorted(chosen)], results


class SharedTests(unittest.TestCase):
    def test_normalization_and_distance(self):
        self.assertEqual(normalize('  ВКЛЮЧИ \t  свет  '), 'включи свет')
        self.assertEqual(levenshtein('кот', 'кит'), 1)
        self.assertEqual(levenshtein('', 'свет'), 4)

    def test_tokens_keep_commas_and_split_hyphens(self):
        self.assertEqual(tokens('Включи робот-пылесос, нет, всё'), ['включи', 'робот', 'пылесос', ',', 'нет', ',', 'все'])

    def test_osa_counts_transposition_as_one_edit(self):
        self.assertEqual(osa('вклюич', 'включи'), 1)
        self.assertEqual(osa('ыключи', 'включи'), 1)
        self.assertEqual(osa('ыключи', 'выключи'), 1)
        self.assertEqual(osa('включи', 'выключи', limit=0), 1)

    def test_deletion_index_matches_brute_force(self):
        words = {word for block in BLOCKS for text in block.get('objects', []) for word in tokens(text)}
        index = DeletionIndex(words)
        for typed in ['свте', 'кухн', 'телевизр', 'спалне', 'музку', 'пылесс', 'гостинной', 'зз']:
            limit = max_edits(typed)
            expected = sorted((word, osa(typed, word)) for word in words
                              if osa(typed, word) <= min(limit, max_edits(word)))
            self.assertEqual(sorted(index.lookup(typed)), expected, typed)

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
        self.assertEqual(public_algorithms()[0], {
            'id': 'levenshtein-combinations',
            'name': 'Левенштейн: комбинации',
            'description': 'Сравнивает запрос со всеми комбинациями «действие + объект» и «объект + действие».',
        })
        self.assertEqual([algorithm['id'] for algorithm in public_algorithms()],
                         ['levenshtein-combinations', 'tfidf-char', 'structured'])

    def test_optional_fields_are_validated_and_passed_through(self):
        result = {'index': 1, 'text': 'дальше', 'score': 1, 'decision': 'accept', 'status': 'resolved',
                  'command': 1, 'explain': ['точное совпадение'], 'debug': 'не попадёт в ответ'}
        self.assertEqual(validate_results([result], {1}), [{
            'index': 1, 'text': 'дальше', 'score': 1.0, 'decision': 'accept', 'status': 'resolved',
            'command': 1, 'explain': ['точное совпадение'],
        }])
        for broken in ({'decision': 'maybe'}, {'status': 'ok'}, {'command': 0}, {'explain': 'строка'}):
            with self.assertRaises(ValueError):
                validate_results([{'index': 1, 'text': 'дальше', 'score': 1, **broken}], {1})

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


class StructuredAlgorithmTests(unittest.TestCase):
    def test_contract_through_registry(self):
        result = run_algorithms(['structured'], 'включи свет на кухне', BLOCKS)[0]['results'][0]
        self.assertEqual(TEXT[result['index']], 'включи свет на кухне')
        self.assertEqual((result['decision'], result['status'], result['command']), ('accept', 'resolved', 1))

    def test_word_order_typo_and_synonyms(self):
        self.assertEqual(understood('свет на кухне включи')[:2], ('accept', ['включи свет на кухне']))
        self.assertEqual(understood('вклюич свет на кухне')[:2], ('accept', ['включи свет на кухне']))
        self.assertEqual(understood('погаси люстру')[:2], ('accept', ['выключи свет в гостиной']))
        self.assertEqual(understood('пожалуйста включи робот-пылесос')[:2], ('accept', ['включи пылесос']))
        self.assertEqual(understood('тише')[:2], ('accept', ['сделай тише']))

    def test_typo_between_opposite_actions_is_not_chosen_silently(self):
        decision, _, results = understood('ыключи свет на кухне')
        self.assertEqual(decision, 'clarify')
        self.assertEqual({TEXT[result['index']] for result in results[:2]}, {'включи свет на кухне', 'выключи свет на кухне'})
        self.assertEqual(results[0]['score'], results[1]['score'])

    def test_several_commands_keep_their_order(self):
        self.assertEqual(understood('включи свет на кухне и выключи телевизор в спальне')[:2],
                         ('accept', ['включи свет на кухне', 'выключи телевизор в спальне']))
        self.assertEqual(understood('выключи свет на кухне и в спальне')[:2],
                         ('accept', ['выключи свет на кухне', 'выключи свет в спальне']))
        self.assertEqual(understood('включи свет и телевизор на кухне')[:2],
                         ('accept', ['включи свет на кухне', 'включи телевизор на кухне']))
        self.assertEqual(understood('включи свет на кухне, нет, выключи')[:2], ('accept', ['выключи свет на кухне']))

    def test_alternatives_and_incomplete_queries_ask_for_clarification(self):
        for query in ['включи свет', 'включи свет или музыку', 'открой и закрой шторы в спальне', 'включи', 'свет на кухне',
                      'выключи его', 'открой свет', 'откой дверь']:
            self.assertEqual(understood(query)[0], 'clarify', query)

    def test_negation_modifiers_and_unknown_words_are_refused(self):
        for query in ['не включай свет', 'выключи свет через час', 'выключи всё, кроме холодильника',
                      'включи свет в гараже', 'свари кофе', 'открой шторы на кухне']:
            self.assertEqual(understood(query)[0], 'reject', query)
        statuses = {result['status'] for result in structured.search('выключи свет через час', BLOCKS)}
        self.assertEqual(statuses, {'unsupported'})

    def test_new_alias_changes_results_without_touching_other_blocks(self):
        blocks = [dict(block) for block in BLOCKS]
        self.assertEqual(understood('включи торшер', blocks)[0], 'reject')
        bedroom = next(block for block in blocks if block['text'] == 'включи свет в спальне')
        bedroom['objects'] = bedroom['objects'] + ['торшер']
        self.assertEqual(understood('включи торшер', blocks)[:2], ('accept', ['включи свет в спальне']))
        self.assertEqual(understood('выключи свет в спальне', blocks)[:2], ('accept', ['выключи свет в спальне']))


class TfidfAlgorithmTests(unittest.TestCase):
    def test_contract_and_typo_tolerance(self):
        results = tfidf_char.search('вклюич свет на кухне', BLOCKS)
        self.assertEqual(len(results), len(BLOCKS))
        self.assertEqual(TEXT[results[0]['index']], 'включи свет на кухне')
        self.assertTrue(all(0 <= result['score'] <= 1 for result in results))
        self.assertEqual(validate_results(results, set(TEXT)), results)


class EvaluationTests(unittest.TestCase):
    def test_dataset_matches_catalog_and_structured_has_no_dangerous_answers(self):
        sys.path.insert(0, os.path.join(ROOT, 'evaluation'))
        import evaluate
        blocks = evaluate.load_blocks()
        dataset = evaluate.load_dataset(evaluate.DATASET, blocks)
        algorithm = next(algorithm for algorithm in evaluate.ALGORITHMS if algorithm['id'] == 'structured')
        summary, _ = evaluate.evaluate(algorithm, dataset, blocks, 0.8)
        self.assertEqual(summary['dangerous'], 0)
        self.assertGreaterEqual(summary['score'], 0.9)


if __name__ == '__main__':
    unittest.main()
