"""Текущий алгоритм: Левенштейн по формам смыслового блока."""

from algo.shared import levenshtein_normalized, normalize, normalized_candidate_forms, prepared_index


def index_for(blocks):
    """Готовит формы для снимка каталога или произвольного списка блоков."""
    return prepared_index(blocks, 'levenshtein', lambda items: [
        (block['index'], normalized_candidate_forms(block)) for block in items
    ])


prepare_index = index_for


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
