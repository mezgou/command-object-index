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
        'id': 'tfidf-char',
        'name': 'TF-IDF: 3-граммы',
        'description': 'Косинус по символьным триграммам с весами IDF; устойчив к опечаткам и лишним словам.',
        'module': 'algo.tfidf_char',
        'function': 'search',
    },
    {
        'id': 'structured',
        'name': 'Структурный индекс',
        'description': 'Находит действия, объекты и служебные слова; несколько команд, отрицание, безопасный отказ.',
        'module': 'algo.structured',
        'function': 'search',
    },
]
