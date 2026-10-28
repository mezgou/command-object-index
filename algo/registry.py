"""Загрузка алгоритмов из конфигурации и проверка их контракта."""

from importlib import import_module
from numbers import Real

from algo.config import ALGORITHMS
from algo.shared import CatalogSnapshot

DECISIONS = {'accept', 'clarify', 'reject'}
STATUSES = {'resolved', 'ambiguous', 'incomplete', 'incompatible', 'not_found', 'negated', 'unsupported'}


def public_algorithms():
    return [
        {key: algorithm[key] for key in ('id', 'name', 'description')}
        for algorithm in ALGORITHMS
    ]


def configured_algorithms():
    return {algorithm['id']: algorithm for algorithm in ALGORITHMS}


def load_search_function(algorithm):
    module = import_module(algorithm['module'])
    function = getattr(module, algorithm['function'], None)
    if not callable(function):
        raise ValueError(f"Алгоритм «{algorithm['id']}» не содержит вызываемую функцию поиска")
    return function


def prepare_catalog(blocks):
    """Создать снимок и подготовить индексы алгоритмов, которым они нужны."""
    snapshot = CatalogSnapshot(blocks)
    for algorithm in ALGORITHMS:
        module = import_module(algorithm['module'])
        prepare = getattr(module, 'prepare_index', None)
        if callable(prepare):
            prepare(snapshot)
    return snapshot


def validate_results(results, valid_indexes):
    if not isinstance(results, list):
        raise ValueError('Алгоритм должен вернуть список результатов')
    validated = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError('Каждый результат алгоритма должен быть словарём')
        index, text, score = result.get('index'), result.get('text'), result.get('score')
        if index not in valid_indexes or not isinstance(text, str) or not text.strip():
            raise ValueError('Результат содержит неизвестный index или пустой text')
        if isinstance(score, bool) or not isinstance(score, Real) or not 0 <= score <= 1:
            raise ValueError('score должен быть числом от 0 до 1')
        validated.append({'index': index, 'text': text, 'score': float(score), **optional_fields(result)})
    return validated


def optional_fields(result):
    """Необязательные поля: решение по запросу, статус и номер команды, объяснение."""
    extra = {}
    if 'decision' in result:
        if result['decision'] not in DECISIONS:
            raise ValueError('decision должен быть accept, clarify или reject')
        extra['decision'] = result['decision']
    if 'status' in result:
        if result['status'] not in STATUSES:
            raise ValueError('Неизвестный status результата')
        extra['status'] = result['status']
    if 'command' in result:
        command = result['command']
        if isinstance(command, bool) or not isinstance(command, int) or command < 1:
            raise ValueError('command должен быть номером команды от 1')
        extra['command'] = command
    if 'explain' in result:
        explain = result['explain']
        if not isinstance(explain, list) or len(explain) > 10 or any(not isinstance(line, str) or len(line) > 300 for line in explain):
            raise ValueError('explain должен быть списком строк')
        extra['explain'] = explain
    return extra


def run_algorithms(algorithm_ids, query, blocks):
    configured = configured_algorithms()
    if len(set(algorithm_ids)) != len(algorithm_ids) or any(identifier not in configured for identifier in algorithm_ids):
        raise ValueError('Выбран неизвестный алгоритм')
    valid_indexes = blocks.valid_indexes if isinstance(blocks, CatalogSnapshot) else {block['index'] for block in blocks}
    response = []
    for identifier in algorithm_ids:
        algorithm = configured[identifier]
        search = load_search_function(algorithm)
        results = validate_results(search(query, blocks), valid_indexes)
        response.append({
            'id': algorithm['id'],
            'name': algorithm['name'],
            'description': algorithm['description'],
            'results': results,
        })
    return response
