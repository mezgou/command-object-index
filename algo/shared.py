"""Общие утилиты, которые могут использовать разные алгоритмы."""

import re
from collections import defaultdict

TOKEN = re.compile(r'\w+|,')


def normalize(text):
    return ' '.join(text.lower().split())


def levenshtein(left, right):
    left, right = normalize(left), normalize(right)
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i]
        for j, right_char in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (left_char != right_char),
            ))
        previous = current
    return previous[-1]


def candidate_forms(block):
    """Строит уникальные текстовые формы, которые описывает смысловой блок."""
    forms = [block['text']]
    actions = block.get('actions', [])
    objects = block.get('objects', [])

    if actions and objects:
        for action in actions:
            for object_name in objects:
                forms.append(' '.join(part for part in (action, object_name) if part))
                forms.append(' '.join(part for part in (object_name, action) if part))
    elif actions:
        forms.extend(action for action in actions if action)
    elif objects:
        forms.extend(objects)

    unique_forms = []
    seen = set()
    for form in forms:
        normalized = normalize(form)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_forms.append(form)
    return unique_forms


def tokens(text):
    """Слова запроса для структурных алгоритмов.

    Регистр, «ё» → «е», дефис как пробел («робот-пылесос»). Запятая остаётся
    отдельным токеном: она разделяет команды и исправления.
    """
    return TOKEN.findall(text.lower().replace('ё', 'е').replace('-', ' '))


def osa(left, right, limit=None):
    """Расстояние Дамерау — Левенштейна (optimal string alignment).

    Вставка, удаление, замена и перестановка соседних букв стоят 1. С `limit`
    возвращает `limit + 1`, как только ответ гарантированно больше.
    """
    if left == right:
        return 0
    if limit is not None and abs(len(left) - len(right)) > limit:
        return limit + 1
    before, previous = None, list(range(len(right) + 1))
    for i in range(1, len(left) + 1):
        current = [i] + [0] * len(right)
        for j in range(1, len(right) + 1):
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (left[i - 1] != right[j - 1]))
            if before and j > 1 and left[i - 1] == right[j - 2] and left[i - 2] == right[j - 1]:
                value = min(value, before[j - 2] + 1)
            current[j] = value
        if limit is not None and min(current) > limit:
            return limit + 1
        before, previous = previous, current
    return previous[-1]


def max_edits(word):
    """Сколько опечаток допускаем в слове: короткие слова сравниваем только точно."""
    return 0 if len(word) <= 3 else 1 if len(word) <= 7 else 2


def edit_kind(typed, word):
    """Человеческое название одной правки — для объяснения результата."""
    if len(typed) == len(word):
        diff = [i for i in range(len(word)) if typed[i] != word[i]]
        if len(diff) == 2 and diff[1] == diff[0] + 1 and typed[diff[0]] == word[diff[1]]:
            return 'перестановка букв'
        return 'замена буквы'
    return 'пропущена буква' if len(typed) < len(word) else 'лишняя буква'


def deletes(word, depth):
    result = frontier = {word}
    for _ in range(depth):
        frontier = {item[:i] + item[i + 1:] for item in frontier for i in range(len(item))}
        result = result | frontier
    return result


class DeletionIndex:
    """Нечёткий поиск слова за O(число удалений запроса), идея SymSpell.

    Для каждого слова словаря заранее храним все строки, получаемые удалением
    до `max_edits(слово)` букв. Кандидаты проверяем точным `osa`. Перебор
    словаря на 10 тыс. слов в ~1000 раз медленнее при том же ответе.
    """

    def __init__(self, words):
        self.table = defaultdict(set)
        for word in words:
            for variant in deletes(word, max_edits(word)):
                self.table[variant].add(word)

    def lookup(self, typed):
        """Слова словаря, допустимо близкие к `typed`, как список `(слово, расстояние)`."""
        limit = max_edits(typed)
        found = {}
        for variant in deletes(typed, limit):
            for word in self.table.get(variant, ()):
                if word not in found:
                    found[word] = osa(typed, word, limit)
        return sorted(((word, distance) for word, distance in found.items()
                       if distance <= min(limit, max_edits(word))), key=lambda item: (item[1], item[0]))
