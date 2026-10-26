"""Левенштейн по формам блока после нормализации запроса и форм.

То же, что `levenshtein-combinations`, но и запрос, и каждая форма сначала
проходят через `algo.normalization.normalize_text`: исправляется раскладка,
выбрасываются слова-паразиты, числа и время. Если в запросе есть «не»,
все кандидаты получают score 0 — система не должна выполнять то, что просили
не делать.
"""

from functools import lru_cache

from algo.normalization import normalize_text
from algo.shared import candidate_forms, levenshtein


@lru_cache(maxsize=8192)
def _normalized_forms(text, actions, objects):
    """Нормализованные формы блока. Кэш по содержимому блока, поэтому правка каталога его не портит."""
    block = {'text': text}
    if actions:
        block['actions'] = list(actions)
    if objects:
        block['objects'] = list(objects)
    forms, seen = [], set()
    for form in candidate_forms(block):
        normalized = normalize_text(form).text
        if normalized and normalized not in seen:
            seen.add(normalized)
            forms.append((form, normalized))
    return tuple(forms)


def search(query, blocks):
    normalized_query = normalize_text(query)
    results = []
    for block in blocks:
        forms = _normalized_forms(block['text'], tuple(block.get('actions', [])), tuple(block.get('objects', [])))
        best = None
        for form, normalized_form in forms:
            distance = levenshtein(normalized_query.text, normalized_form)
            score = max(0.0, 1 - distance / len(normalized_form))
            candidate = (distance, -score, normalized_form, form, score)
            if best is None or candidate < best:
                best = candidate
        if best is None:
            results.append({'index': block['index'], 'text': block['text'], 'score': 0.0})
            continue
        score = 0.0 if normalized_query.negated else best[4]
        results.append({'index': block['index'], 'text': best[3], 'score': score})
    return sorted(results, key=lambda result: (-result['score'], result['text'], result['index']))
