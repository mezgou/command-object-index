"""Общие утилиты, которые могут использовать разные алгоритмы."""


def normalize(text):
    return ' '.join(text.lower().split())


def levenshtein(left, right):
    left, right = normalize(left), normalize(right)
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i]
        for j, right_char in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (left_char != right_char),
            ))
        previous = current
    return previous[-1]


def candidate_forms(block):
    """Строит уникальные текстовые формы, которые описывает смысловой блок."""
    forms = [block['text']]
    actions = block.get('actions', [])
    objects = block.get('objects', [])

    if actions and objects:
        for action in actions:
            for object_name in objects:
                forms.append(' '.join(part for part in (action, object_name) if part))
                forms.append(' '.join(part for part in (object_name, action) if part))
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
