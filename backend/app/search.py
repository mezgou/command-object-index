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


def candidate_forms(command):
    """Возвращает все текстовые формы, которые описывает смысловой блок.

    Канонический `text` сохраняем среди кандидатов: он нужен специальным
    командам и остаётся точной формой для отображения. Для каждой пары
    действия и объекта добавляются оба порядка слов.
    """
    forms = [command['text']]
    actions = command.get('actions', [])
    objects = command.get('objects', [])

    if actions and objects:
        for action in actions:
            for object in objects:
                forms.append(' '.join(part for part in (action, object) if part))
                forms.append(' '.join(part for part in (object, action) if part))
    elif actions:
        forms.extend(action for action in actions if action)
    elif objects:
        forms.extend(objects)

    unique_forms = []
    seen = set()
    for form in forms:
        normalized = normalize(form)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_forms.append(form)
    return unique_forms


def rank(query, commands):
    results = []
    for command in commands:
        matches = []
        for form in candidate_forms(command):
            distance = levenshtein(query, form)
            length = len(normalize(form))
            similarity = max(0, 100 * (1 - distance / length)) if length else 0
            matches.append((distance, -similarity, normalize(form), form, similarity))
        distance, _, _, matched_text, similarity = min(matches)
        results.append({**command, 'distance': distance, 'similarity': similarity,
                        'matched_text': matched_text})
    return sorted(results, key=lambda item: (-item['similarity'], normalize(item['text']), item.get('id', 0)))
