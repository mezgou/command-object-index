"""Реестр алгоритмов, доступных платформе.

Чтобы добавить алгоритм:
1. Создайте модуль в `algo/` с функцией `search(query, blocks)`.
2. Добавьте сюда одну запись с его модулем и именем функции.
"""

ALGORITHMS = [
    {
        'id': 'levenshtein-combinations',
        'name': 'Левенштейн: комбинации',
        'description': 'Сравнивает запрос со всеми комбинациями «действие + объект» и «объект + действие».',
        'module': 'algo.levenshtein_combinations',
        'function': 'search',
    },
    {
        'id': 'levenshtein-normalized',
        'name': 'Левенштейн + нормализация',
        'description': 'Те же комбинации, но запрос и формы сначала нормализуются: раскладка, слова-паразиты, числа и время; на «не» — отказ.',
        'module': 'algo.levenshtein_normalized',
        'function': 'search',
    },
]
