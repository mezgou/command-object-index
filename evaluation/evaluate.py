"""Прогоняет алгоритмы из `algo/config.py` через размеченный датасет и считает оценку.

Запуск из корня репозитория:

    python3 evaluation/evaluate.py
    python3 evaluation/evaluate.py --algorithms structured tfidf-char --details
    python3 evaluation/evaluate.py --threshold 0.9 --json evaluation/report.json

Каждая запись датасета ссылается на блоки по их `text`, поэтому порядок и
номера блоков в каталоге не важны. Подробности — в evaluation/README.md.
"""

import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'backend', 'app'))

from algo.config import ALGORITHMS  # noqa: E402
from algo.registry import configured_algorithms, load_search_function, validate_results  # noqa: E402
from catalog import DEFAULT_COMMANDS  # noqa: E402

DATASET = os.path.join(os.path.dirname(__file__), 'dataset.json')
TOP = 5


def load_blocks(path=None):
    """Каталог из catalog.py или из JSON-файла, сохранённого платформой."""
    commands = DEFAULT_COMMANDS
    if path:
        with open(path, encoding='utf-8') as file:
            commands = json.load(file)
    return [{**command, 'id': index + 1, 'index': index + 1} for index, command in enumerate(commands)]


def load_dataset(path, blocks):
    with open(path, encoding='utf-8') as file:
        dataset = json.load(file)
    known = {block['text'] for block in blocks}
    for item in dataset:
        item.setdefault('expect', [])
        item.setdefault('alternatives', [])
        item['confident'] = bool(item['expect'])
        missing = [text for text in item['expect'] + item['alternatives'] if text not in known]
        if missing:
            raise ValueError(f'«{item["query"]}»: в каталоге нет блоков {missing}')
    return dataset


def is_confident(results, threshold):
    """Уверенный ответ: decision=accept, если алгоритм его сообщает, иначе top-1 score ≥ порога."""
    if not results:
        return False
    if 'decision' in results[0]:
        return results[0]['decision'] == 'accept'
    return results[0]['score'] >= threshold


def answer(results):
    """Что алгоритм выбрал бы уверенно: лучший блок каждой команды или просто top-1."""
    if results and 'command' in results[0]:
        chosen = {}
        for result in results:
            chosen.setdefault(result['command'], result['index'])
        return [chosen[number] for number in sorted(chosen)]
    return [results[0]['index']] if results else []


def evaluate(algorithm, dataset, blocks, threshold):
    search = load_search_function(algorithm)
    by_index = {block['index']: block['text'] for block in blocks}
    valid = set(by_index)
    rows, latencies = [], []
    for item in dataset:
        search(item['query'], blocks)            # прогрев кэшей
        started = time.perf_counter()
        results = validate_results(search(item['query'], blocks), valid)
        latencies.append((time.perf_counter() - started) * 1000)
        top = [by_index[result['index']] for result in results[:TOP]]
        confident = is_confident(results, threshold)
        chosen = [by_index[index] for index in answer(results)]
        if len(item['expect']) > 1:
            correct = item['confident'] and sorted(chosen) == sorted(item['expect'])
        else:
            correct = item['confident'] and chosen[:1] == item['expect']
        if item['confident']:
            found = sum(text in top for text in item['expect']) / len(item['expect'])
            points = 1.0 if confident and correct else 0.5 * found if not confident else 0.0
        else:
            found = sum(text in top for text in item['alternatives']) / len(item['alternatives']) if item['alternatives'] else 1.0
            points = 0.0 if confident else 0.5 + 0.5 * found
        rows.append({'query': item['query'], 'kind': item['kind'], 'top': top[:3], 'confident': confident,
                     'correct': correct, 'found': found, 'points': points,
                     'dangerous': confident and not correct, 'rank': rank(top, item['expect'])})
    return summarize(rows, latencies), rows


def rank(top, expect):
    if len(expect) != 1:
        return None
    return top.index(expect[0]) + 1 if expect[0] in top else None


def summarize(rows, latencies):
    single = [row for row in rows if row['kind'] not in ('несколько команд', 'неоднозначно', 'отказ')]
    expected = [row for row in rows if row['kind'] not in ('неоднозначно', 'отказ')]
    unsure = [row for row in rows if row['kind'] in ('неоднозначно', 'отказ')]
    latencies = sorted(latencies)
    return {
        'score': mean(row['points'] for row in rows),
        'top1': mean(row['rank'] == 1 for row in single),
        'mrr': mean(1 / row['rank'] if row['rank'] else 0 for row in single),
        'recall5': mean(row['found'] for row in expected),
        'confident_correct': mean(row['confident'] and row['correct'] for row in expected),
        'safe_refusal': mean(not row['confident'] for row in unsure),
        'dangerous': sum(row['dangerous'] for row in rows),
        'p50_ms': latencies[len(latencies) // 2],
        'p95_ms': latencies[int(len(latencies) * 0.95)],
        'queries': len(rows),
    }


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def by_kind(rows):
    kinds = {}
    for row in rows:
        kinds.setdefault(row['kind'], []).append(row['points'])
    return {kind: statistics.fmean(points) for kind, points in kinds.items()}


def main():
    parser = argparse.ArgumentParser(description='Оценка алгоритмов на размеченном датасете')
    parser.add_argument('--algorithms', nargs='*', help='id алгоритмов из algo/config.py; по умолчанию все')
    parser.add_argument('--dataset', default=DATASET)
    parser.add_argument('--catalog', help='JSON с блоками (например, копия /data/commands.json); по умолчанию catalog.py')
    parser.add_argument('--threshold', type=float, default=0.8, help='порог уверенности для алгоритмов без decision')
    parser.add_argument('--details', action='store_true', help='показать запросы с ошибками')
    parser.add_argument('--json', help='сохранить полный отчёт в файл')
    args = parser.parse_args()

    blocks = load_blocks(args.catalog)
    dataset = load_dataset(args.dataset, blocks)
    configured = configured_algorithms()
    ids = args.algorithms or [algorithm['id'] for algorithm in ALGORITHMS]
    unknown = [identifier for identifier in ids if identifier not in configured]
    if unknown:
        parser.error(f'неизвестные алгоритмы: {unknown}')

    print(f'Датасет: {len(dataset)} запросов · каталог: {len(blocks)} блоков · порог уверенности без decision: {args.threshold}\n')
    header = f'{"алгоритм":<28}{"ИТОГ":>7}{"top-1":>8}{"MRR":>7}{"полнота@5":>11}{"верно увер.":>13}{"безоп. отказ":>14}{"опасных":>9}{"p50 мс":>9}{"p95 мс":>9}'
    print(header)
    print('-' * len(header))
    report = {}
    for identifier in ids:
        summary, rows = evaluate(configured[identifier], dataset, blocks, args.threshold)
        report[identifier] = {'summary': summary, 'by_kind': by_kind(rows), 'rows': rows}
        print(f'{identifier:<28}{summary["score"]:>7.3f}{summary["top1"]:>8.3f}{summary["mrr"]:>7.3f}{summary["recall5"]:>11.3f}'
              f'{summary["confident_correct"]:>13.3f}{summary["safe_refusal"]:>14.3f}{summary["dangerous"]:>9}'
              f'{summary["p50_ms"]:>9.3f}{summary["p95_ms"]:>9.3f}')

    kinds = list(dict.fromkeys(item['kind'] for item in dataset))
    print('\nИТОГ по типам запросов:')
    print(f'{"тип":<20}' + ''.join(f'{identifier[:16]:>18}' for identifier in ids))
    for kind in kinds:
        print(f'{kind:<20}' + ''.join(f'{report[identifier]["by_kind"][kind]:>18.3f}' for identifier in ids))

    if args.details:
        for identifier in ids:
            print(f'\n{identifier}: запросы с потерей баллов')
            for row in report[identifier]['rows']:
                if row['points'] < 1:
                    mark = 'ОПАСНО' if row['dangerous'] else 'осторожно' if not row['confident'] else ''
                    print(f'  {row["points"]:.2f} {mark:<10} {row["kind"]:<18} «{row["query"]}» → {row["top"]}')
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as file:
            json.dump({'threshold': args.threshold, 'report': report}, file, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
