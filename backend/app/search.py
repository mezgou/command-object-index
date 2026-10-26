import re

from lexicon import (
    ACTIONS,
    CANCEL_WORDS,
    CHOICE_MARKERS,
    DAYS,
    ENTITIES,
    EXCLUSION_MARKERS,
    FILLER_WORDS,
    LIST_FILLER_WORDS,
    LIST_MARKERS,
    LIST_NAMES,
    LOCATIONS,
    LOCATION_PHRASES,
    MEDIA_ACTIONS,
    MEDIA_SEARCH_ACTIONS,
    MEDIA_NOUNS,
    MEDIA_POINTERS,
    MEDIA_REFS,
    MODIFIERS,
    NUMBER_WORDS,
    NUMERIC_VALUE_ACTIONS,
    QUERY_ENTITIES,
    QUERY_MARKERS,
    QUESTION_WORDS,
    RECURRENCE,
    SCOPES,
    TIME_OF_DAY,
    TIME_UNITS,
    TIME_UNIT_FORMS,
    VALUE_UNITS,
)

COMMAND_RULE_FIELDS = [
    'action',
    'object',
    'location',
    'location_scope',
    'excluded_locations',
    'excluded_locations_display',
    'excluded_location',
    'modifier',
    'ambiguous',
    'cancel_requested',
    'intent',
    'delay',
    'time',
    'recurrence',
    'item',
    'media_ref',
    'query',
    'raw'
]

INTENTS = {'device', 'timer', 'alarm', 'list', 'media', 'query', 'cancel', 'unknown'}

# Имена из lexicon сохраняются как алиасы, чтобы не менять публичный API модуля.
STOP_WORDS = FILLER_WORDS
ACTION_ALIASES = ACTIONS
LOCATION_ALIASES = LOCATIONS
MODIFIER_ALIASES = MODIFIERS
SCOPE_ALIASES = SCOPES
NORMALIZED_ALIASES = ENTITIES
CANCEL_ALIASES = CANCEL_WORDS
RECURRENCE_ALIASES = RECURRENCE
DAY_ALIASES = DAYS
LIST_ALIASES = LIST_NAMES
MEDIA_REF_ALIASES = {word: ref for ref, words in MEDIA_REFS.items() for word in words}
NEXT_MARKERS = MEDIA_REFS['next']
PREVIOUS_MARKERS = MEDIA_REFS['previous']


def empty_command_rule(default_action=None, default_object=None, raw=''):
    return {
        'action': default_action,
        'object': default_object,
        'location': None,
        'location_scope': None,
        'excluded_locations': [],
        'excluded_locations_display': [],
        'excluded_location': None,
        'modifier': None,
        'ambiguous': False,
        'cancel_requested': False,
        'intent': None,
        'delay': None,
        'time': None,
        'recurrence': None,
        'item': None,
        'media_ref': None,
        'query': None,
        'raw': raw
    }


def normalize(text):
    return ' '.join(text.lower().split()) if text else ''


def clean_word(token):
    return normalize(token).strip(' ,;:!?()[]{}"\'«»')


def split_compound_parts(text):
    cleaned = normalize(text)
    if not cleaned:
        return []
    parts = re.split(r'\s+(?:и|а)\s+', cleaned)
    return [part.strip(' ,;:!?') for part in parts if part.strip(' ,;:!?')]


def match_alias(word, aliases, fuzzy_threshold=1):
    if word in aliases:
        return aliases[word]
    for alias, canonical in aliases.items():
        if len(word) >= 3 and levenshtein(word, alias) <= fuzzy_threshold:
            return canonical
    return None


def resolve_location_token(token):
    word = clean_word(token)
    if not word:
        return None
    word = word.replace('ё', 'е')
    return match_alias(word, LOCATION_ALIASES, fuzzy_threshold=1)


def normalize_word(token):
    word = clean_word(token)
    if not word:
        return ''
    word = word.replace('ё', 'е')
    if word in ACTION_ALIASES:
        return ACTION_ALIASES[word]
    if word in CANCEL_ALIASES:
        return CANCEL_ALIASES[word]
    if word in STOP_WORDS:
        return ''
    if word in SCOPE_ALIASES:
        return SCOPE_ALIASES[word]
    location_match = resolve_location_token(word)
    if location_match is not None:
        return location_match
    if word in MODIFIER_ALIASES:
        return MODIFIER_ALIASES[word]
    if word in NORMALIZED_ALIASES:
        return NORMALIZED_ALIASES[word]
    return word


def classify_token(token):
    word = normalize(token)
    if not word:
        return {'kind': 'empty'}
    cleaned = word.replace('ё', 'е')
    if cleaned in ACTION_ALIASES:
        return {'kind': 'action', 'value': ACTION_ALIASES[cleaned]}
    if cleaned in CANCEL_ALIASES:
        return {'kind': 'cancel', 'value': CANCEL_ALIASES[cleaned]}
    if cleaned in EXCLUSION_MARKERS:
        return {'kind': 'exclusion', 'value': cleaned}
    if cleaned in CHOICE_MARKERS:
        return {'kind': 'choice', 'value': cleaned}
    if cleaned in SCOPE_ALIASES:
        return {'kind': 'scope', 'value': SCOPE_ALIASES[cleaned]}
    location_match = resolve_location_token(cleaned)
    if location_match is not None:
        return {'kind': 'location', 'value': location_match}
    modifier_match = match_alias(cleaned, MODIFIER_ALIASES, fuzzy_threshold=0)
    if modifier_match is not None:
        return {'kind': 'modifier', 'value': modifier_match}

    normalized_entity = normalize_word(cleaned)
    if normalized_entity and normalized_entity in NORMALIZED_ALIASES.values():
        return {'kind': 'entity', 'value': normalized_entity}
    if cleaned in STOP_WORDS:
        return {'kind': 'empty'}
    if cleaned.isdigit():
        return {'kind': 'entity', 'value': cleaned}
    return {'kind': 'unknown'}


def normalize_tokens(text):
    result = []
    for part in split_compound_parts(text):
        for raw in re.split(r'\s+|,\s*', part):
            token = normalize_word(raw)
            if token:
                result.append(token)
    return result


def canonicalize_expression(text):
    tokens = normalize_tokens(text)
    if not tokens:
        return ''
    action = None
    rest = []
    location = []
    for token in tokens:
        if token in ACTION_ALIASES.values():
            action = token
        elif token in LOCATION_ALIASES.values():
            location.append(token)
        else:
            rest.append(token)
    if action is None:
        return ' '.join(tokens)
    ordered = [action]
    if rest:
        ordered.extend(rest)
    if location:
        ordered.extend(location)
    return ' '.join(ordered)


def parse_number(word):
    return NUMBER_WORDS.get(word)


def parse_clock_time(tokens, start):
    """Разбирает время вида «семь утра», «7:30», «в 7 утра». Возвращает (time, next_index)."""
    index = start
    if index < len(tokens) and tokens[index] in {'в', 'на'}:
        index += 1
    if index >= len(tokens):
        return None, start
    word = tokens[index]
    if re.fullmatch(r'\d{1,2}:\d{2}', word):
        return word, index + 1
    if word.isdigit():
        hour = int(word)
    else:
        hour = parse_number(word)
        if hour is None:
            return None, start
    if not 0 <= hour <= 23:
        return None, start
    index += 1
    period = None
    if index < len(tokens) and tokens[index] in TIME_OF_DAY:
        period = TIME_OF_DAY[tokens[index]]
        index += 1
    if period is None:
        return None, start
    return f'{hour:02d}:00 {period}', index


def pluralize_time(amount, unit):
    one, few, many = TIME_UNIT_FORMS[unit]
    if amount % 10 == 1 and amount % 100 != 11:
        return one
    if 2 <= amount % 10 <= 4 and not 12 <= amount % 100 <= 14:
        return few
    return many


def parse_delay(tokens, start):
    """Разбирает «через десять минут». Возвращает (delay, next_index)."""
    if start >= len(tokens) or tokens[start] != 'через':
        return None, start
    index = start + 1
    if index >= len(tokens):
        return None, start
    word = tokens[index]
    amount = int(word) if word.isdigit() else parse_number(word)
    if amount is None and word in {'час', 'часа', 'часов'}:
        amount = 1
        unit = 'час'
        return f'{amount} {pluralize_time(amount, unit)}', index + 1
    if amount is None:
        return None, start
    index += 1
    if index >= len(tokens) or tokens[index] not in TIME_UNITS:
        return None, start
    unit = TIME_UNITS[tokens[index]]
    return f'{amount} {pluralize_time(amount, unit)}', index + 1


def parse_recurrence(tokens):
    for word in tokens:
        if word in RECURRENCE_ALIASES:
            return RECURRENCE_ALIASES[word]
    return None


def parse_day(tokens):
    for word in tokens:
        if word in DAY_ALIASES:
            return DAY_ALIASES[word]
    return None


def parse_list_name(tokens):
    for word in tokens:
        if word in LIST_ALIASES:
            return LIST_ALIASES[word]
    return None


def parse_list_item(tokens):
    words = [word for word in tokens if word not in LIST_FILLER_WORDS and not word.isdigit()]
    if words and words[0] in ACTION_ALIASES:
        words = words[1:]
    return ' '.join(words) if words else None


def parse_query(tokens):
    """Извлекает известную тему вопроса; локацию оставляет для разбора второго прохода."""
    return next((token for token in tokens if token in QUERY_ENTITIES), None)


def parse_media_ref(tokens):
    """Указатель (этот/следующий/предыдущий) сильнее существительного (трек/песня)."""
    ref = None
    for word in tokens:
        if word in MEDIA_POINTERS:
            return MEDIA_REF_ALIASES[word]
        if word in MEDIA_NOUNS:
            ref = MEDIA_REF_ALIASES[word]
    return ref


def detect_intent(tokens, action, object_text, location, delay, time_value, recurrence, item, media_ref, query):
    if any(word in CANCEL_ALIASES for word in tokens):
        return 'cancel'
    if any(word in QUESTION_WORDS for word in tokens) or (query and action is None):
        return 'query'
    if delay:
        return 'timer'
    if object_text == 'будильник' or recurrence and (time_value or object_text == 'будильник'):
        return 'alarm'
    if action == 'добавь' or item:
        return 'list'
    if media_ref and (action in MEDIA_ACTIONS or object_text in {'музыка', 'громкость', 'звук', 'лайк'}):
        return 'media'
    if action is not None and object_text is not None:
        return 'device'
    return 'unknown'


def extract_slots(tokens):
    """Первый проход: извлекает слоты и исключает их токены из разбора сущностей."""
    consumed = set()
    slots: dict[str, str | None] = {
        'delay': None,
        'time': None,
        'recurrence': None,
        'item': None,
        'media_ref': None,
        'query': None,
        'location': None,
    }

    for phrase, canonical in sorted(LOCATION_PHRASES.items(), key=lambda item: len(item[0].split()), reverse=True):
        phrase_tokens = phrase.split()
        for index in range(len(tokens) - len(phrase_tokens) + 1):
            if tokens[index:index + len(phrase_tokens)] == phrase_tokens:
                slots['location'] = canonical
                consumed.update(range(index, index + len(phrase_tokens)))
                break
        if slots['location']:
            break

    for index, token in enumerate(tokens):
        if token != 'через':
            continue
        delay, end = parse_delay(tokens, index)
        if delay:
            slots['delay'] = delay
            consumed.update(range(index, end))
        break

    time_value = None
    time_span = None
    for index, token in enumerate(tokens):
        if token in TIME_OF_DAY:
            time_value = TIME_OF_DAY[token]
            time_span = (index, index + 1)
            if index >= 2 and tokens[index - 2:index] == ['во', 'время']:
                time_span = (index - 2, index + 1)
            elif index >= 1 and tokens[index - 1] in {'в', 'на'}:
                time_span = (index - 1, index + 1)
            break
        if token not in {'в', 'на'} and parse_number(token) is None and not token.isdigit() and not re.fullmatch(r'\d{1,2}:\d{2}', token):
            continue
        candidate, end = parse_clock_time(tokens, index)
        if candidate:
            time_value = candidate
            time_span = (index, end)
            break
    if time_value is None:
        for index, token in enumerate(tokens):
            if token in DAY_ALIASES:
                time_value = DAY_ALIASES[token]
                time_span = (index, index + 1)
                break
    elif time_span:
        for index, token in enumerate(tokens):
            if token in DAY_ALIASES:
                time_value = f'{DAY_ALIASES[token]} {time_value}'
                time_span = (min(index, time_span[0]), max(index + 1, time_span[1]))
                break
    if time_value and time_span:
        slots['time'] = time_value
        consumed.update(range(*time_span))

    recurrence_indices = [index for index, token in enumerate(tokens) if token in RECURRENCE_ALIASES]
    if recurrence_indices:
        slots['recurrence'] = RECURRENCE_ALIASES[tokens[recurrence_indices[0]]]
        consumed.update(recurrence_indices)

    list_indices = [index for index, token in enumerate(tokens) if token in LIST_ALIASES]
    if list_indices:
        slots['item'] = parse_list_item(tokens)
        consumed.update({index for index, token in enumerate(tokens) if token not in LIST_FILLER_WORDS and token not in ACTION_ALIASES})
        consumed.update({index for index, token in enumerate(tokens) if token in LIST_MARKERS})
        consumed.update(list_indices)

    slots['media_ref'] = parse_media_ref(tokens)
    if slots['media_ref']:
        consumed.update({index for index, token in enumerate(tokens) if token in MEDIA_POINTERS or token in MEDIA_NOUNS})

    remaining_indices = [index for index in range(len(tokens)) if index not in consumed]
    media_action_indices = [
        index for index in remaining_indices
        if ACTIONS.get(tokens[index]) in MEDIA_SEARCH_ACTIONS
    ]
    has_known_entity = any(classify_token(tokens[index]).get('kind') == 'entity' for index in remaining_indices)
    if media_action_indices and not has_known_entity:
        action_index = min(media_action_indices)
        unknown_indices = [index for index in remaining_indices if classify_token(tokens[index]).get('kind') == 'unknown']
        search_terms = [tokens[index] for index in unknown_indices if tokens[index] not in FILLER_WORDS]
        if search_terms and all(index > action_index for index in unknown_indices):
            slots['media_ref'] = 'search'
            slots['query'] = ' '.join(search_terms)
            consumed.update(unknown_indices)

    query_marker_indices = [index for index, token in enumerate(tokens) if token in QUERY_MARKERS]
    if query_marker_indices:
        slots['query'] = parse_query(tokens)
        consumed.update(query_marker_indices)
        if slots['query']:
            consumed.update({index for index, token in enumerate(tokens) if token in QUERY_ENTITIES})

    remaining = [token for index, token in enumerate(tokens) if index not in consumed]
    return slots, remaining


def resolve_rule(slots, rule, object_explicit):
    """Второй проход: собирает итоговое правило из слотов и разобранного остатка.

    Здесь только правила приоритета слотов, без частных случаев для отдельных фраз.
    """
    action = rule['action']
    object_text = rule['object']
    if action is None and object_text in NUMERIC_VALUE_ACTIONS and rule['modifier'] and rule['modifier'].isdigit():
        action = NUMERIC_VALUE_ACTIONS[object_text]
        rule['action'] = action
    query = slots['query']
    item = slots['item']
    media_ref = slots['media_ref']

    if slots.get('location'):
        rule['location'] = slots['location']
        rule['location_scope'] = slots['location']
    if query and media_ref != 'search':
        object_text = query
    elif item:
        object_text = item
    elif media_ref and not object_explicit:
        object_text = 'музыка'
    elif object_text is None and action in {'сделай', 'приглуши', 'подними', 'уменьши', 'увеличь'} and rule['modifier']:
        object_text = 'громкость'
    elif object_text is None and action == 'разбуди':
        object_text = 'будильник'

    intent = 'cancel' if rule['cancel_requested'] else detect_intent(
        [], action, object_text, rule['location'], slots['delay'], slots['time'],
        slots['recurrence'], item, media_ref, query
    )

    rule.update({
        'object': object_text,
        'intent': intent,
        'delay': slots['delay'],
        'time': slots['time'],
        'recurrence': slots['recurrence'],
        'item': item,
        'media_ref': media_ref,
        'query': query,
    })
    return rule


def is_rule_complete(rule):
    """Проверяет заполненность обязательных слотов для выбранного intent."""
    intent = rule.get('intent')
    required_fields = {
        'cancel': (),
        'query': ('query',),
        'alarm': ('object',),
        'timer': ('object', 'delay'),
        'list': ('item',),
        'media': ('media_ref',),
        'device': ('action', 'object'),
    }
    fields = required_fields.get(intent)
    if fields is None or not all(rule.get(field) for field in fields):
        return False
    if intent == 'alarm':
        return bool(rule.get('time') or rule.get('recurrence'))
    if intent == 'media' and rule.get('media_ref') == 'search':
        return bool(rule.get('query'))
    return True


def parse_command_rule(text, default_action=None, default_object=None):
    raw_tokens = [part for part in re.split(r'\s+|,\s*|;\s*', normalize(text)) if part]
    if not raw_tokens:
        return empty_command_rule(default_action=default_action, default_object=default_object, raw=text)

    state = {
        'action': default_action,
        'location': None,
        'excluded_locations': [],
        'excluded_locations_display': [],
        'modifier': None,
        'object_tokens': [],
        'pending_exclusion': False,
        'ambiguous': False,
        'cancel_requested': False,
        'location_candidates': [],
        'unsupported_tokens': False,
        'delay': None,
        'time': None,
        'recurrence': None,
        'item': None,
        'media_ref': None,
        'query': None,
    }

    def assign_location(raw_token, location):
        if state['pending_exclusion']:
            state['excluded_locations'].append(location)
            state['excluded_locations_display'].append(raw_token.rstrip(' ,;:!?'))
            state['pending_exclusion'] = False
            return
        state['location_candidates'].append(location)
        if state['location'] is None:
            state['location'] = location
        elif state['location'] != location:
            state['ambiguous'] = True
        state['pending_exclusion'] = False

    def consume_token(raw_token, token_info, index):
        raw_text = normalize(raw_token)
        kind = token_info.get('kind')
        token = token_info.get('value')

        if kind in {'empty', 'unknown'} or token is None:
            return None
        if kind == 'cancel':
            state['cancel_requested'] = True
            return None
        if kind == 'choice':
            state['ambiguous'] = True
            return None
        if kind == 'exclusion':
            if token in {'не', 'ни'}:
                state['pending_exclusion'] = True
            elif token in {'но', 'а'}:
                state['pending_exclusion'] = False
            else:
                state['pending_exclusion'] = True
            return None
        if kind == 'scope':
            state['location'] = token
            state['pending_exclusion'] = False
            return None
        if kind == 'modifier':
            state['modifier'] = token
            return None
        if kind == 'location':
            assign_location(raw_token, token)
            return None
        if raw_text.isdigit():
            if state['object_tokens'] and state['object_tokens'][-1] in NUMERIC_VALUE_ACTIONS:
                state['modifier'] = raw_text
                return None
            if index + 1 < len(raw_tokens):
                next_token = normalize_word(raw_tokens[index + 1])
                if next_token in VALUE_UNITS:
                    state['modifier'] = f'{raw_text} {VALUE_UNITS[next_token]}'
                    return index + 1
        if kind == 'action':
            state['action'] = token
            return None
        if state['action'] is None:
            state['action'] = default_action
        state['object_tokens'].append(token)
        return None

    skip_index = None
    for index, raw_token in enumerate(raw_tokens):
        if skip_index is not None and index == skip_index:
            skip_index = None
            continue
        token_info = classify_token(raw_token)
        if token_info.get('kind') == 'unknown':
            state['unsupported_tokens'] = True
        if token_info.get('kind') in {'empty', 'unknown'} or not token_info.get('value'):
            continue
        skip_index = consume_token(raw_token, token_info, index)

    object_text = ' '.join(state['object_tokens']).strip() if state['object_tokens'] else default_object
    if not object_text:
        object_text = None

    if len(state['location_candidates']) > 1:
        state['ambiguous'] = True
        state['location'] = state['location_candidates'][0]

    if len(set(state['object_tokens'])) > 1 and any(tok in {'свет', 'музыка'} for tok in state['object_tokens']):
        state['ambiguous'] = True
    if state['unsupported_tokens'] or state['pending_exclusion']:
        state['ambiguous'] = True

    excluded_location = state['excluded_locations'][0] if state['excluded_locations'] else None

    result = empty_command_rule(default_action=state['action'], default_object=object_text, raw=text)
    result.update({
        'action': state['action'],
        'object': object_text,
        'location': state['location'],
        'location_scope': state['location'],
        'excluded_locations': state['excluded_locations'],
        'excluded_locations_display': state['excluded_locations_display'] or state['excluded_locations'],
        'excluded_location': excluded_location,
        'modifier': state['modifier'],
        'ambiguous': state['ambiguous'],
        'cancel_requested': state['cancel_requested'],
        'raw': text
    })
    return result


def parse_intent_rule(text, default_action=None, default_object=None):
    """Разбирает фразу в два прохода.

    1. extract_slots вырезает слоты времени, списка, медиа и вопроса.
    2. parse_command_rule разбирает оставшиеся слова как action/object/location/modifier.

    Возвращает правило той же схемы, что и parse_command_rule, с заполненным intent.
    """
    cleaned = normalize(text)
    tokens = [clean_word(token) for token in re.split(r'\s+|,\s*|;\s*', cleaned) if clean_word(token)]
    if not tokens:
        return parse_command_rule(text, default_action=default_action, default_object=default_object)

    slots, remaining = extract_slots(tokens)
    object_explicit = any(classify_token(token).get('kind') == 'entity' for token in remaining)
    rule = parse_command_rule(' '.join(remaining),
                              default_action=default_action, default_object=default_object)
    rule['raw'] = text
    rule = resolve_rule(slots, rule, object_explicit)

    if rule['intent'] == 'cancel':
        rule['cancel_requested'] = True
    if rule['intent'] == 'unknown' or not is_rule_complete(rule):
        rule['ambiguous'] = True
    return rule


def is_confident_command(rule):
    if not isinstance(rule, dict):
        return False
    if rule.get('ambiguous'):
        return False
    if rule.get('cancel_requested'):
        return True
    if rule.get('intent') is not None:
        return is_rule_complete(rule)
    if rule.get('action') is None:
        return False
    return rule.get('object') is not None


def build_clarification_message(rule):
    if not isinstance(rule, dict):
        return 'Не совсем понял команду. Повторите её более точно.'
    if rule.get('cancel_requested'):
        return 'Отменяю текущую команду. Если хотите, можете сформулировать новую.'
    if rule.get('ambiguous'):
        if rule.get('location') is not None:
            return 'Не совсем понял, где именно это нужно сделать. Повторите команду с одной локацией.'
        return 'Не совсем понял команду. Повторите её более точно, чтобы выбрать одно действие, объект и место.'
    return ''


def is_cancel_intent(rule):
    if not isinstance(rule, dict):
        return False
    return bool(rule.get('cancel_requested'))


def parse_command(text, default_action=None, default_object=None):
    return parse_command_rule(text, default_action=default_action, default_object=default_object)


def match_command_rule(query_rule, catalog_rule):
    if not isinstance(query_rule, dict) or not isinstance(catalog_rule, dict):
        return False

    def norm(value):
        if value is None:
            return None
        return normalize(str(value))

    def compare(field_name):
        query_value = query_rule.get(field_name)
        catalog_value = catalog_rule.get(field_name)
        if query_value is None:
            return True
        if catalog_value is None:
            return False
        return norm(query_value) == norm(catalog_value)

    if not compare('action'):
        return False
    if not compare('object'):
        return False
    if not compare('modifier'):
        return False
    for field_name in ('intent', 'delay', 'time', 'recurrence', 'item', 'media_ref', 'query'):
        if not compare(field_name):
            return False

    query_location = query_rule.get('location')
    catalog_location = catalog_rule.get('location')
    if query_location == 'везде':
        excluded = {norm(item) for item in (query_rule.get('excluded_locations') or [])}
        if catalog_location is not None and norm(catalog_location) in excluded:
            return False
        if query_rule.get('object') is not None and catalog_rule.get('object') is not None:
            return norm(query_rule.get('object')) == norm(catalog_rule.get('object'))
        return True

    if query_location is not None:
        if catalog_location is None:
            return False
        if norm(query_location) != norm(catalog_location):
            return False

    excluded = {norm(item) for item in (query_rule.get('excluded_locations') or [])}
    if catalog_location is not None and norm(catalog_location) in excluded:
        return False

    catalog_excluded = {norm(item) for item in (catalog_rule.get('excluded_locations') or [])}
    return query_location is None or norm(query_location) not in catalog_excluded

    return True


def _rule_without_raw(rule):
    return {key: value for key, value in rule.items() if key != 'raw'}


COMPOUND_RULE_FIELDS = [field for field in COMMAND_RULE_FIELDS if field != 'raw']


def parse_compound_commands(text):
    parts = split_compound_parts(text)
    if not parts:
        return []
    parsed = []
    inherited_action = None
    inherited_object = None

    for part in parts:
        command = parse_intent_rule(part, default_action=inherited_action, default_object=inherited_object)
        if command.get('cancel_requested'):
            cancel_rule = empty_command_rule(default_action=None, default_object=None, raw=part)
            cancel_rule.update({
                'action': None,
                'object': None,
                'location': None,
                'location_scope': None,
                'excluded_locations': [],
                'excluded_locations_display': [],
                'excluded_location': None,
                'modifier': None,
                'ambiguous': False,
                'cancel_requested': True,
                'intent': 'cancel',
                'delay': None,
                'time': None,
                'recurrence': None,
                'item': None,
                'media_ref': None,
                'query': None,
                'raw': part
            })
            return [cancel_rule]

        if command.get('ambiguous'):
            ambiguous_rule = empty_command_rule(default_action=None, default_object=None, raw=part)
            ambiguous_rule.update({
                'action': None,
                'object': None,
                'location': None,
                'location_scope': None,
                'excluded_locations': [],
                'excluded_locations_display': [],
                'excluded_location': None,
                'modifier': None,
                'ambiguous': True,
                'cancel_requested': False,
                'intent': 'unknown',
                'delay': None,
                'time': None,
                'recurrence': None,
                'item': None,
                'media_ref': None,
                'query': None,
                'raw': part
            })
            return [ambiguous_rule]

        if command['action'] is None and command['object'] is None and command['location'] is None and not command['excluded_locations'] and not command['modifier']:
            continue

        if command['action'] is None and inherited_action is not None:
            command['action'] = inherited_action
        if command['object'] is None and inherited_object is not None:
            command['object'] = inherited_object

        parsed.append({field: command[field] for field in COMPOUND_RULE_FIELDS})

        inherited_action = command['action']
        inherited_object = command['object']

    if parsed:
        return parsed
    return [empty_command_rule(default_action=None, default_object=None, raw='')]


def format_command_summary(parsed):
    if not parsed:
        return 'разбор: без структуры'
    if isinstance(parsed, list):
        labels = []
        for item in parsed:
            if item.get('cancel_requested'):
                labels.append('отмена')
                continue
            parts = []
            if item.get('intent'):
                parts.append(f"[{item['intent']}]")
            if item.get('action'):
                parts.append(item['action'])
            if item.get('object'):
                parts.append(item['object'])
            if item.get('location'):
                parts.append(item['location'])
            excluded_display = item.get('excluded_locations_display') or item.get('excluded_locations') or []
            if excluded_display:
                parts.append('кроме ' + ', '.join(excluded_display))
            if item.get('modifier'):
                parts.append(item['modifier'])
            if item.get('delay'):
                parts.append('через ' + item['delay'])
            if item.get('time'):
                parts.append('в ' + item['time'])
            if item.get('recurrence'):
                parts.append('повтор: ' + item['recurrence'])
            if item.get('item'):
                parts.append('элемент: ' + item['item'])
            if item.get('media_ref'):
                parts.append('медиа: ' + item['media_ref'])
            if item.get('query'):
                parts.append(('медиа-поиск: ' if item.get('media_ref') == 'search' else 'запрос: ') + item['query'])
            labels.append(' / '.join(parts) if parts else 'непонятно')
        return ' | '.join(labels)
    if parsed.get('cancel_requested'):
        return 'отмена'
    parts = []
    if parsed.get('intent'):
        parts.append(f"[{parsed['intent']}]")
    if parsed.get('action'):
        parts.append(parsed['action'])
    if parsed.get('object'):
        parts.append(parsed['object'])
    if parsed.get('location'):
        parts.append(parsed['location'])
    excluded_display = parsed.get('excluded_locations_display') or parsed.get('excluded_locations') or []
    if excluded_display:
        parts.append('кроме ' + ', '.join(excluded_display))
    if parsed.get('modifier'):
        parts.append(parsed['modifier'])
    if parsed.get('delay'):
        parts.append('через ' + parsed['delay'])
    if parsed.get('time'):
        parts.append('в ' + parsed['time'])
    if parsed.get('recurrence'):
        parts.append('повтор: ' + parsed['recurrence'])
    if parsed.get('item'):
        parts.append('элемент: ' + parsed['item'])
    if parsed.get('media_ref'):
        parts.append('медиа: ' + parsed['media_ref'])
    if parsed.get('query'):
        parts.append(('медиа-поиск: ' if parsed.get('media_ref') == 'search' else 'запрос: ') + parsed['query'])
    return ' / '.join(parts) if parts else 'непонятно'


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
    query_text = canonicalize_expression(query)
    query_rule = parse_intent_rule(query)
    results = []
    for command in commands:
        candidate_text = canonicalize_expression(command['text'])
        distance = levenshtein(query_text, candidate_text)
        length = len(normalize(candidate_text))
        similarity = max(0, 100 * (1 - distance / length)) if length else 0
        parsed = parse_intent_rule(command['text'])
        rule_match = bool(match_command_rule(query_rule, parsed))
        results.append({**command, 'distance': distance,
                        'similarity': similarity,
                        'rule_match': rule_match,
                        'parsed': parsed,
                        'summary': format_command_summary(parsed)})
    return sorted(results, key=lambda item: (-int(item['rule_match']), -item['similarity'], normalize(item['text']), item['id']))
