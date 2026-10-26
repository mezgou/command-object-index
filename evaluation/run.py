"""Оценка алгоритмов поиска команд на размеченном наборе запросов.

Запуск из корня репозитория:

    python3 -m evaluation.run                         # все алгоритмы из algo/config.py
    python3 -m evaluation.run -a levenshtein-combinations --report evaluation/report.md
    python3 -m evaluation.run --save evaluation/runs/base.json
    python3 -m evaluation.run --compare evaluation/runs/base.json
    python3 -m evaluation.run --latency-scale 1,5,10

Что считается и как читать результат — в evaluation/README.md.
"""

import argparse
import datetime
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for _path in (os.path.join(ROOT, 'backend', 'app'), ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from algo.config import ALGORITHMS  # noqa: E402
from algo.registry import load_search_function, validate_results  # noqa: E402
from algo.shared import candidate_forms, normalize  # noqa: E402
from catalog import DEFAULT_COMMANDS  # noqa: E402
from evaluation import rules as default_rules  # noqa: E402

DEFAULT_DATASET = os.path.join(ROOT, 'evaluation', 'queries.jsonl')
TYPES = {
    'exact': 'точное',
    'reorder': 'порядок слов',
    'partial': 'неполное',
    'synonym': 'синоним',
    'typo': 'опечатка',
    'layout': 'раскладка',
    'noise': 'лишние слова',
    'ambiguous': 'неоднозначное',
    'danger': 'похоже на опасное',
    'negation': 'отрицание',
    'ood': 'не по теме',
}
THRESHOLDS = [round(step / 20, 2) for step in range(21)]
MARGINS = [0.0, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3]
EPSILON = 1e-9
TOP_SAVED = 5


# ---------------------------------------------------------------- данные

def load_catalog(path=None):
    """Каталог в том же виде, в каком его получает алгоритм: с `index` от 1."""
    if path:
        with open(path, encoding='utf-8') as file:
            commands = json.load(file)
    else:
        commands = DEFAULT_COMMANDS
    return [{**command, 'index': position + 1} for position, command in enumerate(commands)]


def load_dataset(path=DEFAULT_DATASET):
    items = []
    with open(path, encoding='utf-8') as file:
        for line_number, line in enumerate(file, 1):
            if line.strip():
                item = json.loads(line)
                item['line'] = line_number
                items.append(item)
    return items


def expected_groups(item):
    """Список групп допустимых ответов.

    `[]` — правильно отказать; `["a", "b"]` — одна группа, подходит любая команда;
    `[["a"], ["b"]]` — несколько толкований, правильно переспросить.
    """
    expected = item.get('expected') or []
    if all(isinstance(entry, str) for entry in expected):
        return [[normalize(text) for text in expected]] if expected else []
    if all(isinstance(entry, list) for entry in expected):
        return [[normalize(text) for text in group] for group in expected]
    raise ValueError(f"строка {item.get('line')}: expected должен быть списком строк или списком списков")


def query_kind(groups):
    if not groups:
        return 'refuse'
    return 'single' if len(groups) == 1 else 'clarify'


class Rules:
    """Опасные команды, противоположные пары и равнозначные блоки из rules.py."""

    def __init__(self, module=default_rules):
        self.dangerous = {normalize(text) for text in module.DANGEROUS}
        self.opposites = defaultdict(set)
        for left, right in module.OPPOSITES:
            self.opposites[normalize(left)].add(normalize(right))
            self.opposites[normalize(right)].add(normalize(left))
        self.group_of = {}
        for group in module.EQUIVALENT:
            key = min(normalize(text) for text in group)
            for text in group:
                self.group_of[normalize(text)] = key
        self.mentioned = self.dangerous | set(self.opposites) | set(self.group_of)

    def same_effect(self, left, right):
        return self.group_of.get(left, left) == self.group_of.get(right, right)

    def forbidden(self, groups, extra=()):
        """Команды, выбор которых для этого запроса — критическая ошибка.

        `extra` — поле `forbidden` из строки набора, например команда, которую просили не выполнять.
        """
        bad = set(self.dangerous) | {normalize(text) for text in extra}
        if len(groups) != 1:
            return bad
        allowed = set(groups[0])
        for text in allowed:
            bad |= self.opposites.get(text, set())
        return bad - allowed


def validate(dataset, blocks, rules):
    known = {normalize(block['text']) for block in blocks}
    problems, warnings, seen = [], [], {}
    for item in dataset:
        where = f"строка {item['line']}"
        query = item.get('query')
        if not isinstance(query, str) or not query.strip():
            problems.append(f'{where}: пустой query')
            continue
        if item.get('type') not in TYPES:
            problems.append(f"{where}: неизвестный type «{item.get('type')}»")
        key = normalize(query)
        if key in seen:
            problems.append(f'{where}: запрос «{query}» уже есть в строке {seen[key]}')
        seen[key] = item['line']
        try:
            groups = expected_groups(item)
        except ValueError as error:
            problems.append(str(error))
            continue
        forbidden = item.get('forbidden', [])
        if not isinstance(forbidden, list) or not all(isinstance(text, str) for text in forbidden):
            problems.append(f'{where}: forbidden должен быть списком строк')
            forbidden = []
        for text in [entry for group in groups for entry in group] + [normalize(entry) for entry in forbidden]:
            if text not in known:
                problems.append(f'{where}: команды «{text}» нет в каталоге')
    for text in sorted(rules.mentioned - known):
        warnings.append(f'rules.py ссылается на «{text}», которой нет в каталоге')
    return problems, warnings


# ---------------------------------------------------------------- прогон и метрики

def run_algorithm(algorithm, dataset, blocks):
    search = load_search_function(algorithm)
    valid_indexes = {block['index'] for block in blocks}
    text_of = {block['index']: normalize(block['text']) for block in blocks}
    rankings, latencies, errors = [], [], []
    for item in dataset:
        started = time.perf_counter()
        try:
            results = validate_results(search(item['query'], blocks), valid_indexes)
        except Exception as error:  # сломанный алгоритм не должен ронять всю оценку
            results = []
            errors.append(f"«{item['query']}»: {type(error).__name__}: {error}")
        latencies.append((time.perf_counter() - started) * 1000)
        if any(left['score'] < right['score'] for left, right in zip(results, results[1:])):
            errors.append(f"«{item['query']}»: результаты не отсортированы по убыванию score — оцениваю в том порядке, в каком они пришли")
        ranking, seen = [], set()
        for result in results:
            if result['index'] not in seen:
                seen.add(result['index'])
                ranking.append({'command': text_of[result['index']], 'score': result['score'], 'form': result['text']})
        rankings.append(ranking)
    return rankings, latencies, errors


def ranking_metrics(groups, ranking):
    kind = query_kind(groups)
    if kind == 'single':
        rank = next((position for position, candidate in enumerate(ranking, 1) if candidate['command'] in groups[0]), None)
        return {'rank': rank, 'hit1': rank == 1, 'hit3': rank is not None and rank <= 3, 'rr': 1 / rank if rank else 0.0}
    if kind == 'clarify':
        top5 = {candidate['command'] for candidate in ranking[:5]}
        return {'coverage5': sum(1 for group in groups if top5 & set(group)) / len(groups)}
    return {}


def decide(ranking, threshold, margin, rules):
    """Команда, которую система выполнила бы молча, или None — отказ / уточнение."""
    if not ranking or ranking[0]['score'] < threshold - EPSILON:
        return None
    top = ranking[0]
    runner_up = next((candidate['score'] for candidate in ranking[1:] if not rules.same_effect(candidate['command'], top['command'])), 0.0)
    if top['score'] - runner_up < margin - EPSILON:
        return None
    return top['command']


def outcome(groups, chosen, rules, extra_forbidden=()):
    if chosen is None:
        return 'false_refusal' if len(groups) == 1 else 'correct_refusal'
    if len(groups) == 1 and chosen in groups[0]:
        return 'correct'
    return 'critical' if chosen in rules.forbidden(groups, extra_forbidden) else 'wrong'


def operating_point(groups_list, rankings, threshold, margin, rules, extras=None):
    extras = extras or [()] * len(groups_list)
    chosen = [decide(ranking, threshold, margin, rules) for ranking in rankings]
    outcomes = [outcome(groups, pick, rules, extra) for groups, pick, extra in zip(groups_list, chosen, extras)]
    counts = Counter(outcomes)
    return {
        'threshold': threshold,
        'margin': margin,
        'good': counts['correct'] + counts['correct_refusal'],
        'counts': {key: counts[key] for key in ('correct', 'correct_refusal', 'false_refusal', 'wrong', 'critical')},
        'chosen': chosen,
        'outcomes': outcomes,
    }


def choose_points(groups_list, rankings, rules, extras=None):
    """Лучший порог и зазор по доле верных решений и лучший среди тех, где нет критических ошибок."""
    best = safe = None
    for threshold in THRESHOLDS:
        for margin in MARGINS:
            point = operating_point(groups_list, rankings, threshold, margin, rules, extras)
            if best is None or (point['good'], -point['counts']['critical']) > (best['good'], -best['counts']['critical']):
                best = point
            if point['counts']['critical'] == 0 and (safe is None or point['good'] > safe['good']):
                safe = point
    return best, safe


def percentile(values, share):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)] if ordered else 0.0


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def evaluate(algorithm, dataset, blocks, rules, fixed=None):
    rankings, latencies, errors = run_algorithm(algorithm, dataset, blocks)
    groups_list = [expected_groups(item) for item in dataset]
    extras = [tuple(item.get('forbidden', [])) for item in dataset]
    metrics = [ranking_metrics(groups, ranking) for groups, ranking in zip(groups_list, rankings)]
    best, safe = choose_points(groups_list, rankings, rules, extras)
    main_point = best if fixed is None else operating_point(groups_list, rankings, fixed[0], fixed[1], rules, extras)
    singles = [metric for metric in metrics if 'rank' in metric]
    clarify = [metric['coverage5'] for metric in metrics if 'coverage5' in metric]

    by_type = []
    for type_id, label in TYPES.items():
        positions = [position for position, item in enumerate(dataset) if item['type'] == type_id]
        if not positions:
            continue
        type_singles = [metrics[position] for position in positions if 'rank' in metrics[position]]
        counts = Counter(main_point['outcomes'][position] for position in positions)
        by_type.append({
            'type': type_id,
            'label': label,
            'n': len(positions),
            'hit1': mean(metric['hit1'] for metric in type_singles),
            'hit3': mean(metric['hit3'] for metric in type_singles),
            'good': (counts['correct'] + counts['correct_refusal']) / len(positions),
            'false_refusal': counts['false_refusal'],
            'wrong': counts['wrong'],
            'critical': counts['critical'],
        })

    queries = []
    for position, item in enumerate(dataset):
        ranking = rankings[position]
        queries.append({
            'query': item['query'],
            'type': item['type'],
            'expected': item.get('expected', []),
            'top': [[candidate['command'], round(candidate['score'], 4)] for candidate in ranking[:TOP_SAVED]],
            'hit1': metrics[position].get('hit1'),
            'rank': metrics[position].get('rank'),
            'chosen': main_point['chosen'][position],
            'outcome': main_point['outcomes'][position],
        })

    def describe(point):
        if point is None:
            return None
        return {key: point[key] for key in ('threshold', 'margin', 'good', 'counts')} | {'accuracy': point['good'] / len(dataset)}

    return {
        'id': algorithm['id'],
        'name': algorithm['name'],
        'summary': {
            'hit1': mean(metric['hit1'] for metric in singles),
            'hit3': mean(metric['hit3'] for metric in singles),
            'mrr': mean(metric['rr'] for metric in singles),
            'coverage5': mean(clarify),
            'main': describe(main_point),
            'main_is_fixed': fixed is not None,
            'safe': describe(safe),
            'latency_p50_ms': percentile(latencies, 0.5),
            'latency_p95_ms': percentile(latencies, 0.95),
            'errors': len(errors),
        },
        'by_type': by_type,
        'queries': queries,
        'error_messages': errors,
    }


# ---------------------------------------------------------------- задержка на большом каталоге

def scaled_catalog(blocks, factor):
    """Каталог, увеличенный в `factor` раз копиями с изменёнными названиями. Только для замера скорости."""
    scaled = []
    for copy in range(factor):
        for block in blocks:
            clone = {key: (list(value) if isinstance(value, list) else value) for key, value in block.items()}
            if copy:
                clone['text'] = f"{block['text']} {copy}"
                if clone.get('objects'):
                    clone['objects'] = [f'{name} {copy}' for name in clone['objects']]
            clone['index'] = len(scaled) + 1
            scaled.append(clone)
    return scaled


def latency_by_scale(algorithms, dataset, blocks, factors, sample_size=60):
    step = max(1, len(dataset) // sample_size)
    sample = dataset[::step][:sample_size]
    rows = []
    for factor in factors:
        catalog = scaled_catalog(blocks, factor)
        forms = sum(len(candidate_forms(block)) for block in catalog)
        for algorithm in algorithms:
            _, latencies, _ = run_algorithm(algorithm, sample, catalog)
            rows.append([algorithm['id'], f'×{factor}', len(catalog), forms, f'{percentile(latencies, 0.5):.1f}', f'{percentile(latencies, 0.95):.1f}'])
    return ['Алгоритм', 'Каталог', 'Команд', 'Форм', 'p50, мс', 'p95, мс'], rows


# ---------------------------------------------------------------- вывод

def pct(value):
    return '—' if value is None else f'{value * 100:.0f}%'


def point_label(point):
    return '—' if point is None else f"{point['threshold']:.2f} / {point['margin']:.2f}"


def text_table(headers, rows):
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows)]

    def line(row):
        return '  '.join(str(cell).ljust(width) for cell, width in zip(row, widths)).rstrip()

    return '\n'.join([line(headers), line(['-' * width for width in widths])] + [line(row) for row in rows])


def markdown_table(headers, rows):
    lines = ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join('---' for _ in headers) + '|']
    lines += ['| ' + ' | '.join(str(cell) for cell in row) + ' |' for row in rows]
    return '\n'.join(lines)


SUMMARY_HEADERS = ['Алгоритм', 'Hit@1', 'Hit@3', 'MRR', 'Варианты@5', 'Порог / зазор', 'Верных решений',
                   'Критич.', 'Без критич.: порог / зазор', 'Без критич.: верных', 'p50, мс', 'p95, мс']
TYPE_HEADERS = ['Тип запроса', 'N', 'Hit@1', 'Hit@3', 'Верных решений', 'Лишних отказов', 'Ошибок', 'Критич.']


def summary_row(result):
    summary = result['summary']
    main, safe = summary['main'], summary['safe']
    return [
        result['id'], pct(summary['hit1']), pct(summary['hit3']),
        '—' if summary['mrr'] is None else f"{summary['mrr']:.2f}", pct(summary['coverage5']),
        point_label(main), pct(main['accuracy']), main['counts']['critical'],
        point_label(safe), '—' if safe is None else pct(safe['accuracy']),
        f"{summary['latency_p50_ms']:.1f}", f"{summary['latency_p95_ms']:.1f}",
    ]


def type_rows(result):
    return [[row['label'], row['n'], pct(row['hit1']), pct(row['hit3']), pct(row['good']),
             row['false_refusal'], row['wrong'], row['critical']] for row in result['by_type']]


def critical_lines(result):
    lines = []
    for query in result['queries']:
        if query['outcome'] == 'critical':
            expected = query['expected']
            if not expected:
                wanted = 'отказ'
            elif isinstance(expected[0], list):
                wanted = 'уточнение'
            else:
                wanted = ' / '.join(f'«{text}»' for text in expected)
            lines.append(f"«{query['query']}» → «{query['chosen']}» (нужно: {wanted}; тип: {TYPES[query['type']]})")
    return lines


def miss_lines(result, limit):
    lines = []
    for query in result['queries']:
        if query['hit1'] is not None and (query['rank'] is None or query['rank'] > 3):
            top = ', '.join(f'{command} ({score:.2f})' for command, score in query['top'][:3])
            lines.append(f"«{query['query']}» [{TYPES[query['type']]}] → {top}")
    return lines[:limit]


def dataset_overview(dataset):
    counts = Counter(item['type'] for item in dataset)
    return ', '.join(f'{label} {counts[type_id]}' for type_id, label in TYPES.items() if counts[type_id])


def print_results(results, blocks, dataset, show_misses):
    forms = sum(len(candidate_forms(block)) for block in blocks)
    print(f'Каталог: {len(blocks)} команд, {forms} форм. Запросов: {len(dataset)} ({dataset_overview(dataset)}).\n')
    print(text_table(SUMMARY_HEADERS, [summary_row(result) for result in results]))
    for result in results:
        main = result['summary']['main']
        kind = 'заданном' if result['summary']['main_is_fixed'] else 'лучшем'
        print(f"\n== {result['name']} ({result['id']}) — при {kind} пороге {main['threshold']:.2f} и зазоре {main['margin']:.2f}")
        print(text_table(TYPE_HEADERS, type_rows(result)))
        lines = critical_lines(result)
        print(f'\nКритические ошибки: {len(lines)}')
        for line in lines:
            print('  ' + line)
        if show_misses:
            lines = miss_lines(result, show_misses)
            print(f'\nНужной команды нет в топ-3 (первые {len(lines)}):')
            for line in lines:
                print('  ' + line)
        if result['error_messages']:
            print(f"\nПроблемы с ответами алгоритма: {len(result['error_messages'])} (первые 5):")
            for message in result['error_messages'][:5]:
                print('  ' + message)


def write_report(path, results, blocks, dataset, latency=None):
    forms = sum(len(candidate_forms(block)) for block in blocks)
    created = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    parts = [
        '# Оценка алгоритмов поиска команд',
        f'{created}. Каталог: {len(blocks)} команд, {forms} форм. Запросов: {len(dataset)} ({dataset_overview(dataset)}).',
        '## Сводка',
        markdown_table(SUMMARY_HEADERS, [summary_row(result) for result in results]),
        '- **Hit@1 / Hit@3 / MRR** — нужная команда первая / в первой тройке / средняя обратная позиция; по запросам с одним правильным ответом.\n'
        '- **Варианты@5** — для неоднозначных запросов: какая доля толкований попала в первую пятёрку (чтобы было из чего переспросить).\n'
        '- **Порог / зазор** — система выполняет первую команду молча, только если её score не ниже порога и отрыв от первой команды с другим действием не меньше зазора; иначе отказывается или переспрашивает. Подобраны по максимуму верных решений.\n'
        '- **Верных решений** — выполнена правильная команда, либо правильно отказано на запросе не по теме или неоднозначном.\n'
        '- **Критич.** — молча выбрана опасная команда или команда с противоположным действием.\n'
        '- **Без критич.** — лучший порог и зазор, при которых критических ошибок нет совсем.',
    ]
    for result in results:
        main = result['summary']['main']
        parts.append(f"## {result['name']} (`{result['id']}`)")
        parts.append(f"Порог {main['threshold']:.2f}, зазор {main['margin']:.2f}.")
        parts.append(markdown_table(TYPE_HEADERS, type_rows(result)))
        lines = critical_lines(result)
        parts.append(f'**Критические ошибки: {len(lines)}**')
        if lines:
            parts.append('\n'.join(f'- {line}' for line in lines))
    if latency:
        parts.append('## Задержка на увеличенном каталоге')
        parts.append(markdown_table(*latency))
    with open(path, 'w', encoding='utf-8') as file:
        file.write('\n\n'.join(parts) + '\n')


def save_run(path, results, blocks, dataset, dataset_path):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    data = {
        'meta': {
            'created': datetime.datetime.now().isoformat(timespec='seconds'),
            'dataset': os.path.relpath(dataset_path, ROOT),
            'queries': len(dataset),
            'catalog_commands': len(blocks),
        },
        'algorithms': {result['id']: {key: result[key] for key in ('name', 'summary', 'by_type', 'queries')} for result in results},
    }
    with open(path, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=1)
        file.write('\n')


def compare_runs(results, path, limit=20):
    with open(path, encoding='utf-8') as file:
        old = json.load(file)
    print(f"\n== Сравнение с прогоном {path} ({old['meta'].get('created', '?')})")
    for result in results:
        before = old['algorithms'].get(result['id'])
        if before is None:
            print(f"{result['id']}: в старом прогоне его нет")
            continue
        old_queries = {query['query']: query for query in before['queries']}
        fixed, broken, moved = [], [], []
        for query in result['queries']:
            previous = old_queries.get(query['query'])
            if previous is None:
                continue
            old_top = previous['top'][0][0] if previous['top'] else None
            new_top = query['top'][0][0] if query['top'] else None
            if query['hit1'] is not None and previous.get('hit1') is not None and query['hit1'] != previous['hit1']:
                (fixed if query['hit1'] else broken).append((query['query'], old_top, new_top))
            elif old_top != new_top:
                moved.append((query['query'], old_top, new_top))
        old_summary, new_summary = before['summary'], result['summary']
        print(f"{result['id']}: Hit@1 {pct(old_summary['hit1'])} → {pct(new_summary['hit1'])}, "
              f"критических {old_summary['main']['counts']['critical']} → {new_summary['main']['counts']['critical']}; "
              f"починилось {len(fixed)}, сломалось {len(broken)}, другой первый кандидат {len(moved)}")
        for title, rows in (('Сломалось', broken), ('Починилось', fixed), ('Другой первый кандидат', moved)):
            for query, old_top, new_top in rows[:limit]:
                print(f'  {title}: «{query}»: «{old_top}» → «{new_top}»')


# ---------------------------------------------------------------- точка входа

def main(argv=None):
    parser = argparse.ArgumentParser(description='Оценка алгоритмов поиска команд на размеченных запросах.')
    parser.add_argument('-a', '--algorithms', nargs='+', metavar='ID', help='id алгоритмов из algo/config.py (по умолчанию все)')
    parser.add_argument('--dataset', default=DEFAULT_DATASET, help='JSONL с запросами (по умолчанию evaluation/queries.jsonl)')
    parser.add_argument('--catalog', help='JSON со списком команд, например сохранённый интерфейсом; по умолчанию catalog.py')
    parser.add_argument('--threshold', type=float, help='зафиксировать порог вместо подбора')
    parser.add_argument('--margin', type=float, help='зафиксировать зазор вместо подбора')
    parser.add_argument('--report', metavar='PATH', help='записать отчёт в Markdown')
    parser.add_argument('--save', metavar='PATH', help='сохранить прогон в JSON')
    parser.add_argument('--compare', metavar='PATH', help='сравнить с сохранённым прогоном')
    parser.add_argument('--show-misses', type=int, default=0, metavar='N', help='показать до N запросов, где нужной команды нет в топ-3')
    parser.add_argument('--latency-scale', metavar='1,5,10', help='замерить задержку на каталоге, увеличенном в указанное число раз')
    args = parser.parse_args(argv)

    configured = {algorithm['id']: algorithm for algorithm in ALGORITHMS}
    unknown = [identifier for identifier in args.algorithms or [] if identifier not in configured]
    if unknown:
        parser.error(f"неизвестные алгоритмы: {', '.join(unknown)}; есть: {', '.join(configured)}")
    algorithms = [configured[identifier] for identifier in args.algorithms] if args.algorithms else list(ALGORITHMS)

    blocks = load_catalog(args.catalog)
    dataset = load_dataset(args.dataset)
    rules = Rules()
    problems, warnings = validate(dataset, blocks, rules)
    for warning in warnings:
        print('Предупреждение: ' + warning)
    if problems:
        print('Набор запросов не сходится с каталогом:')
        for problem in problems:
            print('  ' + problem)
        return 2

    fixed = None
    if args.threshold is not None or args.margin is not None:
        fixed = (args.threshold or 0.0, args.margin or 0.0)
    results = [evaluate(algorithm, dataset, blocks, rules, fixed) for algorithm in algorithms]
    print_results(results, blocks, dataset, args.show_misses)

    latency = None
    if args.latency_scale:
        factors = [int(part) for part in args.latency_scale.split(',') if part.strip()]
        latency = latency_by_scale(algorithms, dataset, blocks, factors)
        print('\n== Задержка на увеличенном каталоге')
        print(text_table(*latency))
    if args.report:
        write_report(args.report, results, blocks, dataset, latency)
        print(f'\nОтчёт: {args.report}')
    if args.compare:
        compare_runs(results, args.compare)
    if args.save:
        save_run(args.save, results, blocks, dataset, args.dataset)
        print(f'Прогон сохранён: {args.save}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
