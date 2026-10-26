import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
from search import (
    COMMAND_RULE_FIELDS,
    build_clarification_message,
    empty_command_rule,
    format_command_summary,
    is_cancel_intent,
    is_confident_command,
    levenshtein,
    match_command_rule,
    normalize,
    normalize_tokens,
    parse_command,
    parse_command_rule,
    parse_compound_commands,
    parse_intent_rule,
    rank,
    split_compound_parts,
)


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

    def test_stop_words_and_word_order_are_ignored(self):
        commands = [{'id': 1, 'text': 'включи свет'}, {'id': 2, 'text': 'выключи свет'}]
        ranked = rank('будь добр свет включи', commands)
        self.assertEqual([item['id'] for item in ranked], [1, 2])

    def test_short_polite_form_is_ignored_as_noise(self):
        parsed = parse_command_rule('пж включи свет')
        self.assertEqual(parsed['action'], 'включ')
        self.assertEqual(parsed['object'], 'свет')

    def test_unknown_words_are_rejected_by_schema(self):
        parsed = parse_command_rule('пж включи приветливый свет')
        self.assertEqual(parsed['action'], 'включ')
        self.assertEqual(parsed['object'], 'свет')

    def test_verbal_forms_are_normalized(self):
        commands = [{'id': 1, 'text': 'включи свет'}, {'id': 2, 'text': 'выключи свет'}]
        ranked = rank('включите свет', commands)
        self.assertEqual([item['id'] for item in ranked], [1, 2])

    def test_compound_requests_are_split(self):
        parts = split_compound_parts('включи свет и музыку')
        self.assertEqual(parts, ['включи свет', 'музыку'])
        self.assertEqual(normalize_tokens('свет, будь добр, включи'), ['свет', 'включ'])

    def test_parse_command_with_location(self):
        parsed = parse_command('выключи свет в ванной')
        self.assertEqual(parsed['action'], 'выключ')
        self.assertEqual(parsed['object'], 'свет')
        self.assertEqual(parsed['location'], 'ванная')

    def test_parse_command_with_location_in_locative_case(self):
        parsed = parse_command('включи музыку в гостинной')
        self.assertEqual(parsed['action'], 'включ')
        self.assertEqual(parsed['object'], 'музыка')
        self.assertEqual(parsed['location'], 'гостиная')

    def test_parse_device_modifier_in_location(self):
        parsed = parse_command_rule('открой шторы в гостиной наполовину')
        self.assertEqual(parsed['action'], 'открой')
        self.assertEqual(parsed['object'], 'шторы')
        self.assertEqual(parsed['location'], 'гостиная')
        self.assertEqual(parsed['modifier'], 'наполовину')

    def test_parse_brightness_modifier(self):
        parsed = parse_command_rule('сделай свет в спальне ярче')
        self.assertEqual(parsed['action'], 'сделай')
        self.assertEqual(parsed['object'], 'свет')
        self.assertEqual(parsed['location'], 'спальня')
        self.assertEqual(parsed['modifier'], 'ярче')

    def test_parse_temperature_value_modifier(self):
        parsed = parse_command_rule('установи кондиционер на 22 градуса')
        self.assertEqual(parsed['action'], 'установи')
        self.assertEqual(parsed['object'], 'кондиционер')
        self.assertEqual(parsed['modifier'], '22 градуса')

    def test_parse_compound_command_with_multiple_targets(self):
        parsed = parse_compound_commands('включи свет и музыку')
        self.assertEqual([(part['action'], part['object']) for part in parsed], [
            ('включ', 'свет'), ('включ', 'музыка')
        ])
        self.assertEqual([part['intent'] for part in parsed], ['device', 'media'])
        self.assertTrue(all('time' in part and 'media_ref' in part for part in parsed))

    def test_parse_compound_command_keeps_cancel_intent(self):
        parsed = parse_compound_commands('включи свет и я передумал')
        self.assertTrue(any(part.get('cancel_requested') for part in parsed))

    def test_parse_command_with_location_list(self):
        parsed = parse_compound_commands('включи свет в ванной и гостиной')
        self.assertEqual([(part['object'], part['location']) for part in parsed], [
            ('свет', 'ванная'), ('свет', 'гостиная')
        ])
        self.assertTrue(all(part['intent'] == 'device' for part in parsed))

    def test_cancel_summary_is_explicit(self):
        parsed = parse_compound_commands('включи свет и я передумал')
        self.assertIn('отмена', format_command_summary(parsed))

    def test_parse_negative_location(self):
        parsed = parse_command_rule('включи свет везде кроме спальни')
        self.assertEqual(parsed['action'], 'включ')
        self.assertEqual(parsed['object'], 'свет')
        self.assertEqual(parsed['location'], 'везде')
        self.assertEqual(parsed['excluded_locations'], ['спальня'])

    def test_parse_volume_restriction(self):
        parsed = parse_command_rule('включи музыку только тихо')
        self.assertEqual(parsed['action'], 'включ')
        self.assertEqual(parsed['object'], 'музыка')
        self.assertEqual(parsed['modifier'], 'тихо')

    def test_parse_rule_keeps_compound_exclusions(self):
        parsed = parse_compound_commands('включи свет везде кроме спальни и музыку только тихо')
        self.assertEqual(parsed[0]['action'], 'включ')
        self.assertEqual(parsed[0]['excluded_locations'], ['спальня'])
        self.assertEqual(parsed[1]['modifier'], 'тихо')

    def test_format_command_summary_includes_exclusions_and_modifiers(self):
        parsed = parse_command_rule('включи свет везде кроме спальни только тихо')
        summary = format_command_summary(parsed)
        self.assertIn('включ', summary)
        self.assertIn('свет', summary)
        self.assertIn('везде', summary)
        self.assertIn('спальни', summary)
        self.assertIn('тихо', summary)

    def test_match_command_rule_identifies_same_action_and_target(self):
        query_rule = parse_command_rule('включи свет в ванной')
        catalog_rule = {'action': 'включ', 'object': 'свет', 'location': 'ванная', 'location_scope': 'ванная', 'excluded_locations': [], 'excluded_location': None, 'modifier': None}
        self.assertTrue(match_command_rule(query_rule, catalog_rule))

    def test_match_command_rule_rejects_excluded_locations(self):
        query_rule = parse_command_rule('включи свет везде кроме спальни')
        catalog_rule = {'action': 'включ', 'object': 'свет', 'location': 'спальня', 'location_scope': 'спальня', 'excluded_locations': ['спальня'], 'excluded_location': 'спальня', 'modifier': None}
        self.assertFalse(match_command_rule(query_rule, catalog_rule))

    def test_parse_command_with_choice_is_ambiguous(self):
        parsed = parse_command_rule('включи свет или музыку')
        self.assertTrue(parsed['ambiguous'])
        self.assertFalse(is_confident_command(parsed))

    def test_parse_unknown_schema_tokens_requires_rephrase(self):
        parsed = parse_command_rule('если в квартире двигаются, включи музыку')
        self.assertTrue(parsed['ambiguous'])
        self.assertFalse(is_confident_command(parsed))
        self.assertIn('повторите', build_clarification_message(parsed).lower())

    def test_compound_command_with_unknown_trigger_is_not_executed(self):
        parsed = parse_compound_commands('если в квартире двигаются, включи музыку')
        self.assertEqual(len(parsed), 1)
        self.assertTrue(parsed[0].get('ambiguous'))
        self.assertIsNone(parsed[0].get('action'))

    def test_parse_command_with_multiple_locations_is_ambiguous(self):
        parsed = parse_command_rule('включи свет в ванной или гостиной')
        self.assertTrue(parsed['ambiguous'])
        self.assertFalse(is_confident_command(parsed))

    def test_parse_command_with_single_target_is_confident(self):
        parsed = parse_command_rule('включи свет в ванной')
        self.assertFalse(parsed['ambiguous'])
        self.assertTrue(is_confident_command(parsed))

    def test_command_schema_is_explicit_and_complete(self):
        rule = empty_command_rule()
        self.assertEqual(list(rule.keys()), COMMAND_RULE_FIELDS)
        self.assertFalse(rule['ambiguous'])
        self.assertEqual(rule['excluded_locations'], [])
        self.assertEqual(rule['modifier'], None)

    def test_build_clarification_message_for_ambiguous_command(self):
        rule = parse_command_rule('включи свет или музыку')
        message = build_clarification_message(rule)
        self.assertIn('повторите', message.lower())
        self.assertIn('не совсем понял', message.lower())

    def test_cancel_intent_is_detected(self):
        parsed = parse_command_rule('отмена')
        self.assertTrue(parsed['cancel_requested'])
        self.assertTrue(is_cancel_intent(parsed))

    def test_cancel_intent_from_change_of_mind_is_detected(self):
        parsed = parse_command_rule('я передумал')
        self.assertTrue(parsed['cancel_requested'])
        self.assertTrue(is_cancel_intent(parsed))

    def test_parse_exclusion_after_global_location_with_but_not(self):
        parsed = parse_command_rule('включи музыку везде, но не в гостиной')
        self.assertEqual(parsed['action'], 'включ')
        self.assertEqual(parsed['object'], 'музыка')
        self.assertEqual(parsed['location'], 'везде')
        self.assertEqual(parsed['excluded_locations'], ['гостиная'])
        self.assertIn('гостиной', parsed['excluded_locations_display'])

    def test_scope_examples_parse_without_ambiguity(self):
        examples = {
            'Включи свет на кухне': ('device', 'включ', 'свет', 'кухня', None),
            'Выключи ночник в спальне': ('device', 'выключ', 'ночник', 'спальня', None),
            'Открой шторы в гостиной наполовину': ('device', 'открой', 'шторы', 'гостиная', None),
            'Сделай свет в спальне ярче': ('device', 'сделай', 'свет', 'спальня', None),
            'Установи кондиционер на 22 градуса': ('device', 'установи', 'кондиционер', None, None),
            'Выключи свет через десять минут': ('timer', 'выключ', 'свет', None, '10 минут'),
            'Поставь будильник на завтра на семь утра': ('alarm', 'поставь', 'будильник', None, None),
            'Отключи все будильники на выходных': ('alarm', 'выключ', 'будильник', None, None),
            'Добавь молоко в список покупок': ('list', 'добавь', 'молоко', None, None),
            'Поставь лайк этой песне': ('media', 'поставь', 'лайк', None, None),
            'Сделай громче': ('device', 'сделай', 'громкость', None, None),
            'Включи следующий трек': ('media', 'включ', 'музыка', None, None),
            'Покажи камеру у входной двери': ('device', 'покажи', 'камера', 'входная дверь', None),
            'Какая температура на кухне?': ('query', None, 'температура', 'кухня', None),
            'Алиса, я хочу, чтобы ты разбудила меня на выходных во время рассвета': ('alarm', 'разбуди', 'будильник', None, None),
        }
        for text, (intent, action, object_name, location, delay) in examples.items():
            with self.subTest(text=text):
                parsed = parse_intent_rule(text)
                self.assertEqual(parsed['intent'], intent)
                self.assertEqual(parsed['action'], action)
                self.assertEqual(parsed['object'], object_name)
                self.assertEqual(parsed['location'], location)
                self.assertEqual(parsed['delay'], delay)
                self.assertFalse(parsed['ambiguous'])
                self.assertTrue(is_confident_command(parsed))

        self.assertEqual(parse_intent_rule('Поставь будильник на завтра на семь утра')['time'], 'завтра 07:00 утра')
        self.assertEqual(parse_intent_rule('Отключи все будильники на выходных')['recurrence'], 'выходные')
        self.assertEqual(parse_intent_rule('Добавь молоко в список покупок')['item'], 'молоко')
        self.assertEqual(parse_intent_rule('Поставь лайк этой песне')['media_ref'], 'current')
        self.assertEqual(parse_intent_rule('Включи следующий трек')['media_ref'], 'next')
        self.assertEqual(parse_intent_rule('Алиса, я хочу, чтобы ты разбудила меня на выходных во время рассвета')['time'], 'рассвет')

    def test_api_compound_parser_preserves_intent_slots(self):
        parsed = parse_compound_commands('Какая температура на кухне?')[0]
        self.assertEqual(parsed['intent'], 'query')
        self.assertEqual(parsed['query'], 'температура')
        self.assertEqual(parsed['location'], 'кухня')
        self.assertTrue(is_confident_command(parsed))

    def test_unknown_music_title_becomes_open_search_query(self):
        parsed = parse_intent_rule('включи Кино')
        self.assertEqual(parsed['intent'], 'media')
        self.assertEqual(parsed['object'], 'музыка')
        self.assertEqual(parsed['media_ref'], 'search')
        self.assertEqual(parsed['query'], 'кино')
        self.assertTrue(is_confident_command(parsed))

    def test_bare_volume_number_is_explicit_set_value(self):
        parsed = parse_intent_rule('громкость 20')
        self.assertEqual(parsed['intent'], 'device')
        self.assertEqual(parsed['action'], 'установи')
        self.assertEqual(parsed['object'], 'громкость')
        self.assertEqual(parsed['modifier'], '20')
        self.assertFalse(parsed['ambiguous'])

    def test_action_negation_requires_clarification(self):
        parsed = parse_intent_rule('не включай свет')
        self.assertEqual(parsed['action'], 'включ')
        self.assertTrue(parsed['ambiguous'])

    def test_negative_location_is_not_action_negation(self):
        parsed = parse_intent_rule('включи свет не в спальне')
        self.assertEqual(parsed['excluded_locations'], ['спальня'])
        self.assertFalse(parsed['ambiguous'])


if __name__ == '__main__':
    unittest.main()
