"""TF-IDF по символьным 3-граммам: быстрый поиск похожих формулировок.

Каждая форма блока (`candidate_forms`, как у Левенштейна) превращается в вектор
частот символьных триграмм с весом IDF: редкие кусочки слов («кух», «спа»)
важнее частых («ючи»). Запрос сравнивается с формами по косинусу через
инвертированный индекс — считаются только формы с общими триграммами.

В отличие от Левенштейна, лишние слова в запросе не «съедают» расстояние:
они лишь добавляют триграммы, которых нет у формы. Опечатка ломает 1–3
триграммы из десятков, поэтому похожая форма остаётся наверху. Смысла
(«не включай», «через час», две команды) метод не понимает — это
базовая линия для сравнения со структурным индексом.
"""

import json
import math
from collections import Counter, defaultdict

from algo.shared import candidate_forms, normalize

_CACHE = {}


def search(query, blocks):
    """Возвращает `index`, лучшую форму `text` и косинусную близость `score`."""
    index = index_for(blocks)
    weights = {gram: count * index['idf'][gram] for gram, count in trigrams(query).items() if gram in index['idf']}
    norm = math.sqrt(sum(value * value for value in weights.values())) or 1.0
    similarity = defaultdict(float)
    for gram, value in weights.items():
        for form, weight in index['postings'][gram]:
            similarity[form] += value / norm * weight
    best = {}
    for form, score in similarity.items():
        block, text = index['forms'][form]
        if score > best.get(block, (0, ''))[0]:
            best[block] = (min(score, 1.0), text)
    results = [{'index': block, 'text': text, 'score': round(score, 4)} for block, (score, text) in best.items()]
    for block in blocks:
        if block['index'] not in best:
            results.append({'index': block['index'], 'text': block['text'], 'score': 0.0})
    return sorted(results, key=lambda result: (-result['score'], normalize(result['text']), result['index']))


def trigrams(text):
    padded = f' {normalize(text).replace("ё", "е")} '
    return Counter(padded[i:i + 3] for i in range(len(padded) - 2))


def index_for(blocks):
    """Индекс строится один раз на содержимое каталога: правка блока меняет ключ."""
    key = json.dumps(blocks, ensure_ascii=False, sort_keys=True)
    if key not in _CACHE:
        if len(_CACHE) >= 4:
            _CACHE.pop(next(iter(_CACHE)))
        forms, vectors = [], []
        for block in blocks:
            for form in candidate_forms(block):
                forms.append((block['index'], form))
                vectors.append(trigrams(form))
        frequency = Counter(gram for vector in vectors for gram in vector)
        idf = {gram: math.log((1 + len(vectors)) / (1 + count)) + 1 for gram, count in frequency.items()}
        postings = defaultdict(list)
        for number, vector in enumerate(vectors):
            weights = {gram: count * idf[gram] for gram, count in vector.items()}
            norm = math.sqrt(sum(value * value for value in weights.values()))
            for gram, value in weights.items():
                postings[gram].append((number, value / norm))
        _CACHE[key] = {'forms': forms, 'idf': idf, 'postings': postings}
    return _CACHE[key]
