"""Метаморфные тесты: свойства, которые должны выполняться для любых запросов.

Ручной датасет проверяет конкретные фразы. Метаморфные отношения берут каждую
фразу датасета, меняют её так, чтобы правильный ответ был известен без разметки,
и проверяют, что алгоритм ведёт себя согласованно:

1. перестановка блоков каталога не меняет решение и выбранные блоки;
2. «пожалуйста» в начале или в конце и обращение «привет» не меняют решение и выбор;
3. «не» перед запросом никогда не даёт уверенного ответа (accept);
4. опечатка, близкая к обоим антонимам («включи» / «выключи», «громче» / «тише»),
   никогда не даёт уверенного ответа.

Отношения 3–4 не применяются к запросам с самоисправлением («…, нет, выключи»):
изменение в отброшенной части правильно не влияет на ответ. Настоящие слова
(«выключит», «включать» — по словарю pymorphy3, если он установлен) опечатками
не считаются: точное совпадение со словом важнее похожести на антоним.

Запуск из корня репозитория:

    python3 evaluation/metamorphic.py
    python3 evaluation/metamorphic.py --algorithms structured --details
"""

import argparse
import os
import random
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from algo.config import ALGORITHMS  # noqa: E402
from algo.registry import configured_algorithms, load_search_function, validate_results  # noqa: E402
from algo.shared import max_edits, osa, tokens  # noqa: E402
from algo.structured import GROUPS, OPERATORS, OPPOSITE  # noqa: E402
from evaluate import DATASET, is_confident, load_blocks, load_dataset  # noqa: E402

try:
    import pymorphy3
    MORPH = pymorphy3.MorphAnalyzer()
except ImportError:           # без словаря настоящими словами считаем только слова каталога и лексикона
    MORPH = None

LETTERS = 'абвгдежзийклмнопрстуфхцчшщъыьэюя'
CORRECTIONS = {word for word in OPERATORS['correction']}
SEED = 20261028


def outcome(search, query, blocks, threshold):
    """Что алгоритм делает с запросом: уверен ли и какие блоки (по тексту) выбрал."""
    results = validate_results(search(query, blocks), {block['index'] for block in blocks})
    text = {block['index']: block['text'] for block in blocks}
    if results and 'command' in results[0]:
        chosen = {}
        for result in results:
            chosen.setdefault(result['command'], text[result['index']])
        chosen = [chosen[number] for number in sorted(chosen)]
    else:
        chosen = [text[results[0]['index']]] if results else []
    return is_confident(results, threshold), chosen


def reindex(commands):
    return [{**command, 'id': number + 1, 'index': number + 1} for number, command in enumerate(commands)]


def permutations(blocks, count=3):
    rng = random.Random(SEED)
    plain = [{key: value for key, value in block.items() if key not in ('id', 'index')} for block in blocks]
    shuffled = []
    for _ in range(count):
        copy = list(plain)
        rng.shuffle(copy)
        shuffled.append(reindex(copy))
    return shuffled


def known_words(blocks):
    words = {word for block in blocks for text in [block['text']] + block.get('actions', []) + block.get('objects', [])
             for word in tokens(text)}
    words |= {tokens(word)[0] for group in GROUPS.values() for word in group}
    words |= {word for group in OPERATORS.values() for phrase in group for word in tokens(phrase)}
    return words


def antonym_typos(word, known):
    """Однобуквенные опечатки слова, которые в пределах допуска и к слову, и к его антониму."""
    group = next((name for name, words in GROUPS.items() if word in {tokens(item)[0] for item in words}), None)
    opposite = {right for left, right in OPPOSITE if left == group} | {left for left, right in OPPOSITE if right == group}
    rivals = {tokens(item)[0] for name in opposite for item in GROUPS[name]}
    if not rivals:
        return []
    variants = {word[:i] + word[i + 1:] for i in range(len(word))}
    variants |= {word[:i] + word[i + 1] + word[i] + word[i + 2:] for i in range(len(word) - 1)}
    variants |= {word[:i] + letter + word[i + 1:] for i in range(len(word)) for letter in LETTERS}
    variants |= {word[:i] + letter + word[i:] for i in range(len(word) + 1) for letter in LETTERS}
    found = []
    for variant in sorted(variants - known):
        if MORPH and MORPH.word_is_known(variant):     # «выключит», «включать» — слова, а не опечатки
            continue
        if len(variant) < 4 or osa(variant, word) > max_edits(variant):
            continue
        if any(osa(variant, rival) <= min(max_edits(variant), max_edits(rival)) for rival in rivals):
            found.append(variant)
    return found


def cases(dataset, blocks):
    """Все проверки в виде (отношение, исходный запрос, изменённый запрос или каталог, ожидание)."""
    known = known_words(blocks)
    result = []
    for item in dataset:
        query = item['query']
        for shuffled in permutations(blocks):
            result.append(('перестановка каталога', query, (query, shuffled), 'same'))
        for changed in (f'пожалуйста {query}', f'{query} пожалуйста', f'привет {query}'):
            result.append(('вежливость и обращение', query, (changed, blocks), 'same'))
        if CORRECTIONS & set(tokens(query)):
            continue          # «включи свет, нет, выключи»: изменения в отброшенной части правильно не мешают ответу
        result.append(('добавлено «не»', query, (f'не {query}', blocks), 'not_accept'))
        words = tokens(query)
        for position, word in enumerate(words):
            for variant in antonym_typos(word, known):
                changed = ' '.join(words[:position] + [variant] + words[position + 1:])
                result.append(('опечатка-антоним', query, (changed, blocks), 'not_accept'))
    return result


def check(algorithm, checks, blocks, threshold):
    """Нарушения отношения: список (отношение, исходный запрос, изменённый запрос, что пошло не так)."""
    search = load_search_function(algorithm)
    base, violations, totals = {}, [], {}
    for relation, query, (changed, catalog), expect in checks:
        totals[relation] = totals.get(relation, 0) + 1
        if query not in base:
            base[query] = outcome(search, query, blocks, threshold)
        confident, chosen = outcome(search, changed, catalog, threshold)
        if expect == 'same' and (confident, chosen) != base[query]:
            violations.append((relation, query, changed, f'{base[query]} → {(confident, chosen)}'))
        if expect == 'not_accept' and confident:
            violations.append((relation, query, changed, f'уверенно: {chosen}'))
    return totals, violations


def main():
    parser = argparse.ArgumentParser(description='Метаморфные тесты алгоритмов')
    parser.add_argument('--algorithms', nargs='*', help='id из algo/config.py; по умолчанию все')
    parser.add_argument('--threshold', type=float, default=0.8, help='порог уверенности для алгоритмов без decision')
    parser.add_argument('--details', action='store_true', help='показать нарушения')
    args = parser.parse_args()

    blocks = load_blocks()
    checks = cases(load_dataset(DATASET, blocks), blocks)
    configured = configured_algorithms()
    ids = args.algorithms or [algorithm['id'] for algorithm in ALGORITHMS]
    relations = list(dict.fromkeys(relation for relation, *_ in checks))
    print(f'Проверок: {len(checks)} на основе датасета · порог уверенности без decision: {args.threshold}\n')
    print(f'{"нарушений":<28}' + ''.join(f'{relation[:22]:>24}' for relation in relations))
    report = {}
    for identifier in ids:
        try:
            totals, violations = check(configured[identifier], checks, blocks, args.threshold)
        except ValueError as error:
            print(f'{identifier:<28}пропущен: {error}')
            continue
        report[identifier] = violations
        counts = {relation: sum(1 for violation in violations if violation[0] == relation) for relation in relations}
        print(f'{identifier:<28}' + ''.join(f'{f"{counts[relation]} / {totals[relation]}":>24}' for relation in relations))
    if args.details:
        for identifier, violations in report.items():
            print(f'\n{identifier}: {len(violations)} нарушений')
            for relation, query, changed, what in violations[:25]:
                print(f'  [{relation}] «{changed}» (из «{query}»): {what}')


if __name__ == '__main__':
    main()
