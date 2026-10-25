"""Загрузка алгоритмов из конфигурации и проверка их контракта."""

from importlib import import_module
from numbers import Real

from algo.config import ALGORITHMS


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
        validated.append({'index': index, 'text': text, 'score': float(score)})
    return validated


def run_algorithms(algorithm_ids, query, blocks):
    configured = configured_algorithms()
    if len(set(algorithm_ids)) != len(algorithm_ids) or any(identifier not in configured for identifier in algorithm_ids):
        raise ValueError('Выбран неизвестный алгоритм')
    valid_indexes = {block['index'] for block in blocks}
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
