def normalize(text):
    return ' '.join(text.lower().split())


def levenshtein(left, right):
    left, right = normalize(left), normalize(right)
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def rank(query, commands):
    results = []
    for command in commands:
        distance = levenshtein(query, command['text'])
        length = len(normalize(command['text']))
        results.append({**command, 'distance': distance,
                        'similarity': max(0, 100 * (1 - distance / length)) if length else 0})
    return sorted(results, key=lambda item: (-item['similarity'], normalize(item['text']), item['id']))
