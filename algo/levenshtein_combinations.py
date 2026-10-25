"""Текущий алгоритм: Левенштейн по формам смыслового блока."""

from algo.shared import candidate_forms, levenshtein, normalize


def search(query, blocks):
    """Возвращает `index`, лучшую форму `text` и нормированную `score`.

    Контракт всех алгоритмов платформы:
    `search(query: str, blocks: list[dict]) -> list[dict]`, где каждый
    словарь результата имеет только ключи `index`, `text`, `score`.
    """
    results = []
    for block in blocks:
        matches = []
        for form in candidate_forms(block):
            distance = levenshtein(query, form)
            length = len(normalize(form))
            score = max(0, 1 - distance / length) if length else 0
            matches.append((distance, -score, normalize(form), form, score))
        _, _, _, matched_text, score = min(matches)
        results.append({'index': block['index'], 'text': matched_text, 'score': score})
    return sorted(results, key=lambda result: (-result['score'], normalize(result['text']), result['index']))
