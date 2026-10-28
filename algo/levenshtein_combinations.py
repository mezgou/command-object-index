"""Текущий алгоритм: Левенштейн по формам смыслового блока."""

import json

from algo.shared import levenshtein_normalized, normalize, normalized_candidate_forms

_CACHE = {}


def index_for(blocks):
    """Готовит формы каталога один раз и пересобирает индекс при его изменении."""
    key = json.dumps(blocks, ensure_ascii=False, sort_keys=True)
    if key not in _CACHE:
        if len(_CACHE) >= 4:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = [(block['index'], normalized_candidate_forms(block)) for block in blocks]
    return _CACHE[key]


def search(query, blocks):
    """Возвращает `index`, лучшую форму `text` и нормированную `score`.

    Контракт всех алгоритмов платформы:
    `search(query: str, blocks: list[dict]) -> list[dict]`, где каждый
    словарь результата имеет только ключи `index`, `text`, `score`.
    """
    query_normalized = normalize(query)
    results = []
    for index, forms in index_for(blocks):
        matches = []
        for form, normalized_form in forms:
            distance = levenshtein_normalized(query_normalized, normalized_form)
            length = len(normalized_form)
            score = max(0, 1 - distance / length) if length else 0
            matches.append((distance, -score, normalized_form, form, score))
        _, _, normalized_text, matched_text, score = min(matches)
        results.append(({'index': index, 'text': matched_text, 'score': score}, normalized_text))
    return [result for result, _ in sorted(results, key=lambda item: (-item[0]['score'], item[1], item[0]['index']))]
