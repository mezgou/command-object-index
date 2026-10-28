"""Сравнение вариантов TF-IDF на одном каталоге и датасете.

Запуск: python3 evaluation/tfidf_experiments.py
Это исследовательский код, не используемый платформой.
"""

import heapq
import math
from collections import Counter, defaultdict
from unittest.mock import patch

from evaluate import DATASET, evaluate, load_blocks, load_dataset
from algo import tfidf_char
from algo.shared import candidate_forms, normalize


def grams(text, sizes):
    text = f' {normalize(text)} '
    return Counter(text[i:i + n] for n in sizes for i in range(len(text) - n + 1))


def make_search(blocks, sizes=(3,), binary=False, block_idf=False, unknown_penalty=False):
    forms, vectors, owners = [], [], []
    for block in blocks:
        for form in candidate_forms(block):
            forms.append((block['index'], form))
            vectors.append(grams(form, sizes))
            owners.append(block['index'])
    if block_idf:
        terms = defaultdict(set)
        for owner, vector in zip(owners, vectors):
            terms[owner].update(vector)
        frequency = Counter(gram for vector in terms.values() for gram in vector)
        count = len(blocks)
    else:
        frequency = Counter(gram for vector in vectors for gram in vector)
        count = len(vectors)
    idf = {gram: math.log((1 + count) / (1 + frequency)) + 1 for gram, frequency in frequency.items()}
    unseen_idf = math.log(1 + count) + 1
    postings = defaultdict(list)
    for number, vector in enumerate(vectors):
        weights = {gram: (1 if binary else tf) * idf[gram] for gram, tf in vector.items()}
        norm = math.sqrt(sum(weight * weight for weight in weights.values()))
        for gram, weight in weights.items():
            postings[gram].append((number, weight / norm))

    def search(query, _blocks):
        weights = {gram: (1 if binary else tf) * idf.get(gram, unseen_idf)
                   for gram, tf in grams(query, sizes).items() if unknown_penalty or gram in idf}
        norm = math.sqrt(sum(weight * weight for weight in weights.values())) or 1
        similarities = defaultdict(float)
        for gram, weight in weights.items():
            for number, form_weight in postings.get(gram, ()):
                similarities[number] += weight / norm * form_weight
        best = {}
        for number, score in similarities.items():
            block, text = forms[number]
            if score > best.get(block, (0, ''))[0]:
                best[block] = (min(score, 1), text)
        results = ({'index': block, 'text': text, 'score': round(score, 4)}
                   for block, (score, text) in best.items() if score >= 0.5)
        return heapq.nsmallest(10, results,
                               key=lambda result: (-result['score'], normalize(result['text']), result['index']))

    return search, vectors


def main():
    blocks = load_blocks()
    dataset = load_dataset(DATASET, blocks)
    for item in dataset:
        normalize(item['query'])  # сравниваем поиск при одинаково прогретой нормализации
    configurations = [
        ('3-граммы, TF, IDF форм', {}),
        ('2-граммы', {'sizes': (2,)}),
        ('4-граммы', {'sizes': (4,)}),
        ('2–3-граммы', {'sizes': (2, 3)}),
        ('3–4-граммы', {'sizes': (3, 4)}),
        ('3-граммы, бинарный TF', {'binary': True}),
        ('3-граммы, IDF блоков', {'block_idf': True}),
        ('3-граммы, учёт неизвестных', {'unknown_penalty': True}),
    ]
    print(f'{len(dataset)} запросов; кэш нормализации прогрет, индекс построен, порог выдачи 0.5, до 10 блоков.')
    print(f'{"вариант":<30} {"итог":>6} {"top-1":>6} {"recall@5":>8} {"опасных":>8} {"p50 мс":>8} {"p95 мс":>8}')
    baseline_rows = None
    for name, options in configurations:
        search, vectors = make_search(blocks, **options)
        if not options:
            for item in dataset:
                assert search(item['query'], blocks) == tfidf_char.search(item['query'], blocks), item['query']
        with patch('evaluate.load_search_function', return_value=search):
            metrics, rows = evaluate({}, dataset, blocks, 0.8)
        if baseline_rows is None:
            baseline_rows = rows
            counts = [count for vector in vectors for count in vector.values()]
            print(f'Форм: {len(vectors)}, доля TF=1 среди ненулевых триграмм: {sum(v == 1 for v in counts) / len(counts):.1%}; '
                  f'доля форм с повторами: {sum(any(v > 1 for v in vector.values()) for vector in vectors) / len(vectors):.1%}.')
        print(f'{name:<30} {metrics["score"]:6.3f} {metrics["top1"]:6.3f} {metrics["recall5"]:8.3f} '
              f'{metrics["dangerous"]:8d} {metrics["p50_ms"]:8.3f} {metrics["p95_ms"]:8.3f}')
        if options:
            changed = [row['query'] for row, base in zip(rows, baseline_rows) if row['top'][:1] != base['top'][:1]]
            print(f'  top-1 изменился для {len(changed)} запросов: {", ".join(changed[:5])}')


if __name__ == '__main__':
    main()
