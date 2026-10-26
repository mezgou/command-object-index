"""Структурный индекс: действия и объекты по словам, операторы запроса, политика решения.

Левенштейн по комбинациям сравнивает запрос целиком со всеми формами
«действие + объект» и поэтому теряет смысл: «не включай свет» и «выключи свет
через час» для него почти «включи свет», а лишнее слово или вторая команда
портят расстояние. Здесь порядок другой:

1. запрос делится на слова; каждое слово ищется в словаре aliases блоков —
   точно, а при отсутствии точного совпадения через индекс удалений (OSA ≤ 1–2);
2. динамическое программирование выбирает лучшее покрытие слов спанами:
   действие, слово объекта, специальная команда, служебное слово, неизвестное;
3. служебные слова задают структуру: «и» перед действием — новая команда,
   «и»/«или» между объектами — сочинение, «в»/«на» — уточнение места,
   «не», «нет», «кроме», «через час» — отрицание, исправление, неподдержанные части;
4. для каждой команды объект сравнивается с объектами блоков по словам:
   «свет» — неполное название, подходит нескольким блокам; «свет в гараже» —
   слово «гараже» не объяснено, команда не выбирается молча;
5. политика решает: уверенный выбор (`accept`), уточнение (`clarify`) или
   безопасный отказ (`reject`). Ничья противоположных действий после опечатки
   («ыключи» — «включи» или «выключи») никогда не выбирается молча.

Кроме обязательных `index`, `text`, `score` каждый результат несёт
необязательные поля контракта: `decision`, `status`, `command`, `explain`.
"""

import json
from itertools import product

from algo.shared import DeletionIndex, edit_kind, tokens

OPERATORS = {
    'and': ['и', 'а также', ','],
    'or': ['или', 'либо'],
    'neg': ['не', 'не надо', 'не нужно', 'нельзя'],
    'correction': ['нет', 'вернее', 'точнее', 'то есть'],
    'except': ['кроме', 'за исключением'],
    'all': ['всё', 'весь', 'всю', 'везде'],
    'anaphora': ['его', 'её', 'их', 'это', 'там', 'тут'],
    'prep': ['в', 'во', 'на'],
    'filler': ['пожалуйста', 'ну', 'давай', 'можешь', 'мне', 'ка', 'а', 'бы', 'сейчас', 'ой'],
    'mod': ['через', 'завтра', 'сегодня', 'утром', 'вечером', 'ночью', 'потом', 'позже',
            'секунду', 'секунд', 'минуту', 'минуты', 'минут', 'час', 'часа', 'часов', 'полчаса',
            'один', 'одну', 'два', 'две', 'три', 'пять', 'десять', 'двадцать', 'тридцать',
            'процентов', 'градусов', 'наполовину'],
}
# Объекты, для которых опечатка никогда не даёт уверенного выбора: ошибка здесь
# дороже переспроса. В схеме блока нет поля риска, поэтому список — часть политики.
CAREFUL = {'дверь', 'двери', 'замок', 'холодильник', 'плиту', 'газ', 'сигнализацию'}
FUZZY_PENALTY = 0.15      # штраф качества за одну опечатку
MARGIN = 0.10             # насколько лучший кандидат должен опережать второй
READING_MARGIN = 0.05     # то же для прочтений всего запроса
LIMIT = 5                 # кандидатов на одну команду
MISSING_ACTION = 0.5      # множитель кандидатов, если действие не названо
STATUS_ORDER = ['negated', 'unsupported', 'not_found', 'incompatible', 'incomplete', 'ambiguous', 'resolved']
_CACHE = {}


def search(query, blocks):
    """Возвращает ранжированные блоки по контракту платформы и разбор запроса.

    Результаты идут по командам запроса: сначала кандидаты первой команды,
    потом второй. Поле `command` — номер команды, `status` — её статус,
    `decision` — решение по всему запросу, `explain` — почему блок здесь.
    """
    analysis = analyze(query, blocks)
    results = []
    for number, command in enumerate(analysis['commands'], 1):
        for candidate in command['candidates']:
            results.append({
                'index': candidate['index'],
                'text': candidate['text'],
                'score': round(candidate['score'], 4),
                'decision': analysis['decision'],
                'status': command['status'],
                'command': number,
                'explain': (candidate['explain'] + command['issues'] + analysis['notes'])[:6],
            })
    return results


def analyze(query, blocks):
    """Полный разбор: решение, команды с кандидатами и пояснения."""
    index = lexicon_for(blocks)
    readings = []
    paths = index.segment(tokens(query))
    for items in paths:
        readings.extend(Parser(index).readings(items))
    if len(paths) > 1:
        for reading in readings:
            reading['notes'].append('слова запроса можно разобрать по-разному')
    readings.sort(key=lambda reading: -reading['score'])
    best = readings[0] if readings else {'commands': [], 'notes': [], 'score': 0}
    close = len(readings) > 1 and best['score'] - readings[1]['score'] < READING_MARGIN
    decision = decide(best['commands'], close, best.get('conflict', False))
    notes = best['notes'] + (['запрос допускает несколько близких прочтений'] if close else [])
    return {'decision': decision, 'commands': best['commands'], 'notes': notes}


def decide(commands, close_readings, conflict):
    statuses = [command['status'] for command in commands]
    if not statuses or all(status in ('negated', 'unsupported', 'not_found') for status in statuses):
        return 'reject'
    if all(status == 'resolved' for status in statuses) and not close_readings and not conflict:
        return 'accept'
    return 'clarify'


def lexicon_for(blocks):
    """Индекс строится один раз на содержимое каталога: правка блока меняет ключ."""
    key = json.dumps(blocks, ensure_ascii=False, sort_keys=True)
    if key not in _CACHE:
        if len(_CACHE) >= 4:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = Lexicon(blocks)
    return _CACHE[key]


class Lexicon:
    """Словарь блоков: фразы действий и спецкоманд, слова объектов, служебные слова."""

    def __init__(self, blocks):
        self.blocks = {block['index']: block for block in blocks}
        self.operators = {}
        for kind, words in OPERATORS.items():
            for word in words:
                self.operators[tuple(tokens(word)) or (word,)] = kind
        function_words = {word for phrase in self.operators for word in phrase}
        self.phrases = {}          # слова фразы → [(вид, alias, множество блоков)]
        self.objects = []          # (блок, alias, значимые слова alias)
        self.by_word = {}          # слово объекта → номера записей self.objects
        self.empty_action = set()  # блоки, где допустима форма без действия
        for block in blocks:
            actions, objects = block.get('actions', []), block.get('objects', [])
            if not actions and not objects:
                self.add_phrase('special', block['text'], block['index'])
            for action in actions:
                if action:
                    self.add_phrase('action', action, block['index'])
                else:
                    self.empty_action.add(block['index'])
            if objects and not actions:
                self.empty_action.add(block['index'])
            for alias in objects:
                words = tuple(word for word in tokens(alias) if word not in function_words)
                if words:
                    for word in set(words):
                        self.by_word.setdefault(word, []).append(len(self.objects))
                    self.objects.append((block['index'], alias, words))
        self.longest = max([len(phrase) for phrase in list(self.phrases) + list(self.operators)] or [1])
        self.vocabulary = {word for phrase in self.phrases for word in phrase} | set(self.by_word)
        self.fuzzy = DeletionIndex(self.vocabulary - function_words)
        self.function_words = function_words

    def add_phrase(self, kind, alias, index):
        phrase = tuple(tokens(alias))
        if not phrase:
            return
        entries = self.phrases.setdefault(phrase, [])
        for entry in entries:
            if entry[0] == kind and entry[1] == alias:
                entry[2].add(index)
                return
        entries.append((kind, alias, {index}))

    def expand(self, word):
        """Варианты слова: точное совпадение побеждает, иначе ближайшие по OSA."""
        if word in self.vocabulary:
            return [(word, 0)]
        if word in self.function_words or word.isdigit():
            return []
        found = self.fuzzy.lookup(word)
        if not found:
            return []
        best = found[0][1]
        return [item for item in found if item[1] <= best + 1][:6]

    def segment(self, words, beam=4, tie=0.05):
        """Лучшие покрытия слов спанами; несколько — только при почти равной оценке."""
        variants = [self.expand(word) for word in words]
        options = [[] for _ in words]
        for start in range(len(words)):
            for length in range(1, min(self.longest, len(words) - start) + 1):
                phrase = tuple(words[start:start + length])
                if phrase in self.operators:
                    kind = self.operators[phrase]
                    options[start].append((start + length, length - 0.01, Span('op', start, length, words, op=kind)))
                if any(not variants[start + shift] for shift in range(length)):
                    continue
                by_kind = {}
                for combo in product(*[variants[start + shift][:3] for shift in range(length)]):
                    for kind, alias, indexes in self.phrases.get(tuple(word for word, _ in combo), []):
                        distance = sum(distance for _, distance in combo)
                        typos = [(words[start + shift], word) for shift, (word, d) in enumerate(combo) if d]
                        by_kind.setdefault(kind, []).append(Alt(alias, distance, typos, indexes))
                for kind, alts in by_kind.items():
                    alts = best_alternatives(alts)
                    quality = 1 - FUZZY_PENALTY * alts[0].distance
                    options[start].append((start + length, length * quality - 0.01, Span(kind, start, length, words, alts=alts)))
            if variants[start] and any(word in self.by_word for word, _ in variants[start]):
                alts = [Alt(word, distance, [(words[start], word)] if distance else [], set())
                        for word, distance in variants[start] if word in self.by_word]
                alts = best_alternatives(alts)
                quality = 1 - FUZZY_PENALTY * alts[0].distance
                options[start].append((start + 1, quality - 0.02, Span('object', start, 1, words, alts=alts)))
            if words[start].isdigit():
                options[start].append((start + 1, 0.99, Span('op', start, 1, words, op='mod')))
            options[start].append((start + 1, -0.5, Span('unknown', start, 1, words)))
        best = [[] for _ in range(len(words) + 1)]
        best[0] = [(0.0, [])]
        for start in range(len(words)):
            for score, path in best[start]:
                for end, gain, span in options[start]:
                    best[end].append((score + gain, path + [span]))
            for end in range(start + 1, len(words) + 1):
                best[end] = sorted(best[end], key=lambda item: -item[0])[:beam]
        if not words:
            return [[]]
        top = best[-1][0][0]
        return [path for score, path in best[-1] if score >= top - tie]


class Alt:
    """Один вариант прочтения спана: alias, число опечаток и блоки, где он встречается."""

    def __init__(self, alias, distance, typos, indexes):
        self.alias, self.distance, self.typos, self.indexes = alias, distance, typos, indexes

    @property
    def quality(self):
        return max(0.0, 1 - FUZZY_PENALTY * self.distance)


def best_alternatives(alts):
    """Оставляет лучшие и почти лучшие варианты; одинаковые aliases склеивает."""
    alts = sorted(alts, key=lambda alt: alt.distance)
    best, merged = alts[0].distance, {}
    for alt in alts:
        if alt.distance <= best + 1:
            if alt.alias in merged:
                merged[alt.alias].indexes = merged[alt.alias].indexes | alt.indexes
            else:
                merged[alt.alias] = Alt(alt.alias, alt.distance, alt.typos, set(alt.indexes))
    return list(merged.values())


class Span:
    """Кусок запроса: действие, спецкоманда, слово объекта, служебное или неизвестное слово."""

    def __init__(self, kind, start, length, words, op=None, alts=None):
        self.kind, self.op, self.alts = kind, op, alts or []
        self.text = ' '.join(words[start:start + length])


class Mention:
    """Упоминание объекта: слова, уточнения после «в/на» и связь с предыдущим.

    Каждое слово хранится списком вариантов `Alt` (точное или с опечатками).
    `shared` — номера предыдущих упоминаний, к которым можно отнести место:
    «включи свет и телевизор на кухне».
    """

    def __init__(self, link=None, words=None, copied=False):
        self.words, self.qualifiers, self.link, self.shared, self.copied = list(words or []), [], link, [], copied


class Parser:
    def __init__(self, index):
        self.index = index

    def readings(self, spans):
        notes, inherited = [], {}
        corrections = [n for n, span in enumerate(spans) if span.op == 'correction']
        if corrections:
            cut = corrections[-1]
            before = [span for span in spans[:cut] if span.op != 'and']
            after = spans[cut + 1:]
            while after and after[0].op == 'and':
                after = after[1:]
            if has_content(before) and has_content(after):
                last = clauses(before)[-1]
                inherited = {'actions': [span for span in last if span.kind == 'action'],
                             'mentions': mentions(last)}
                notes.append('исправление: отброшено «' + ' '.join(span.text for span in before) + '»')
                spans = after
            else:
                spans = before + after
        parts = clauses(spans)
        inherit = []
        for number, part in enumerate(parts):
            current = dict(inherited) if number == 0 else {}
            if not mentions(part) and any(span.kind == 'action' for span in part):
                for later in parts[number + 1:]:
                    if mentions(later):
                        current = {'mentions': mentions(later)}
                        notes.append('общий объект для нескольких действий')
                        break
            inherit.append(current)
        distributive = any(mention.shared for part in parts for mention in mentions(part))
        readings = []
        for spread in ([True, False] if distributive else [True]):
            commands = []
            for part, current in zip(parts, inherit):
                commands.extend(self.commands(part, current, spread))
            tops = [command['candidates'][0]['score'] if command['candidates'] else 0 for command in commands]
            score = sum(tops) / len(tops) if tops else 0
            reading_notes = list(notes)
            if distributive:
                reading_notes.append('место отнесено ко всем объектам' if spread else 'место отнесено только к последнему объекту')
                if not spread:
                    score *= 0.9
            readings.append({'score': score, 'commands': commands, 'notes': reading_notes,
                             'conflict': self.conflict(commands)})
        return readings

    def conflict(self, commands):
        """Две уверенные команды над одним объектом с разными действиями: «открой и закрой шторы»."""
        chosen = [command['candidates'][0] for command in commands if command['status'] == 'resolved' and command['candidates']]
        seen = {}
        for candidate in chosen:
            if candidate['object'] in seen and seen[candidate['object']] != candidate['index']:
                return True
            seen[candidate['object']] = candidate['index']
        return False

    def commands(self, spans, inherited, spread):
        index = self.index
        actions = [span for span in spans if span.kind == 'action'] or inherited.get('actions', [])
        specials = [span for span in spans if span.kind == 'special']
        ops = {span.op for span in spans if span.op}
        modifiers = [span.text for span in spans if span.op == 'mod']
        found = mentions(spans) or inherited.get('mentions', [])
        leading, places, extra = unknown_words(spans)
        issues = []
        if 'neg' in ops:
            issues.append('отрицание: команду не выполнять')
        if 'all' in ops or 'except' in ops:
            issues.append('«всё» и «кроме» пока не поддерживаются')
        if modifiers:
            issues.append('время или число не поддерживаются: ' + ' '.join(modifiers))
        if actions and not found and leading + places + extra:
            issues.append('неизвестный объект: ' + ', '.join(leading + places + extra))
        else:
            if leading:
                issues.append('пропущено обращение: ' + ', '.join(leading))
            if places:
                issues.append('неизвестное место: ' + ', '.join(places))
            if extra:
                issues.append('непонятные слова: ' + ', '.join(extra))
        if 'anaphora' in ops and not found:
            issues.append('ссылка на прошлую команду без контекста')
        if len({alt.alias for span in actions for alt in span.alts[:1]}) > 1:
            issues.append('несколько действий без союза')

        result = []
        for span in specials:
            candidates = [self.candidate(item, alt.alias, alt.quality, explain_typos(alt), '', alt.distance > 0)
                          for alt in span.alts for item in sorted(alt.indexes)]
            result.append(self.status(candidates, issues))
        if not actions and not found:
            return result

        groups, choices = [], []
        for number, mention in enumerate(found):
            extra = [word for other in found[number + 1:] if spread and number in other.shared for word in other.qualifiers]
            targets = self.objects(mention, extra)
            if mention.link == 'or' and groups:
                groups[-1] = groups[-1] + targets
                choices[-1] = True
            else:
                groups.append(targets)
                choices.append(False)

        if not found:
            candidates = []
            for span in actions[:1]:
                for alt in span.alts:
                    for item in sorted(alt.indexes):
                        candidates.append(self.candidate(item, alt.alias, alt.quality * MISSING_ACTION, explain_typos(alt), '',
                                                         alt.distance > 0))
            unknown_object = any(issue.startswith('неизвестный объект') for issue in issues)
            result.append(self.status(candidates, issues if unknown_object else issues + ['не указан объект']))
            return result

        for targets, choice in zip(groups, choices):
            if not targets:
                result.append(self.status([], issues, missing='не найден объект с таким сочетанием слов'))
                continue
            candidates, others = [], []
            for item, alias, quality, explain, fuzzy in targets:
                if not actions:
                    if item in index.empty_action:
                        candidates.append(self.candidate(item, '', quality, explain, alias, fuzzy))
                    else:
                        others.append(self.candidate(item, '', quality * MISSING_ACTION, explain, alias, fuzzy))
                    continue
                for span in actions:
                    for alt in span.alts:
                        typo = fuzzy or alt.distance > 0
                        if item in alt.indexes:
                            candidates.append(self.candidate(item, alt.alias, alt.quality * quality,
                                                             explain_typos(alt) + explain, alias, typo))
                        else:
                            others.append(self.candidate(item, alt.alias, alt.quality * quality * MISSING_ACTION,
                                                         explain_typos(alt) + explain, alias, typo))
            if candidates:
                result.append(self.status(candidates, issues + (['выбор через «или»: решает пользователь'] if choice else []),
                                          choice=choice))
            elif not actions:
                result.append(self.status(others, issues + ['не указано действие'], incomplete=True))
            else:
                result.append(self.status(others, issues + ['действие не подходит к объекту'], incompatible=True))
        return result

    def objects(self, mention, extra):
        """Блоки, объект которых объясняет все слова упоминания."""
        index = self.index
        words = mention.words + mention.qualifiers + extra
        records = {number for alts in words for alt in alts for number in index.by_word.get(alt.alias, [])}
        best = {}
        for number in records:
            item, alias, alias_words = index.objects[number]
            matched, typos, unexplained = {}, [], []
            for alts in words:
                hit = [alt for alt in alts if alt.alias in alias_words]
                if not hit:
                    unexplained.append(alts[0].typos[0][0] if alts[0].typos else alts[0].alias)
                    continue
                alt = min(hit, key=lambda alt: alt.distance)
                matched[alt.alias] = max(matched.get(alt.alias, 0), alt.quality)
                typos.extend(alt.typos)
            if unexplained or not matched:
                continue
            completeness = len(matched) / len(set(alias_words))
            quality = sum(matched.values()) / len(matched) * (0.6 + 0.4 * completeness)
            explain = [f'«{typed}» → «{word}»: {edit_kind(typed, word)}' for typed, word in typos]
            if completeness < 1:
                explain.append(f'неполное название: совпало {len(matched)} из {len(set(alias_words))} слов «{alias}»')
            if item not in best or quality > best[item][2]:
                best[item] = (item, alias, quality, explain, bool(typos))
        return list(best.values())

    def candidate(self, item, action, quality, explain, alias, fuzzy=False):
        block = self.index.blocks[item]
        text = ' '.join(part for part in (action, alias) if part) or block['text']
        objects = block.get('objects') or [block['text']]
        careful = any(word in CAREFUL for name in objects for word in tokens(name))
        return {'index': item, 'text': text, 'score': quality, 'explain': list(dict.fromkeys(explain)),
                'object': tuple(sorted(objects)), 'careful': careful and (fuzzy or bool(explain))}

    def status(self, candidates, issues, incomplete=False, incompatible=False, missing=None, choice=False):
        unique = {}
        for candidate in sorted(candidates, key=lambda candidate: -candidate['score']):
            unique.setdefault(candidate['index'], candidate)
        candidates = list(unique.values())[:LIMIT]
        issues = issues + ([missing] if missing else [])
        if any(issue.startswith('отрицание') for issue in issues):
            status = 'negated'
        elif any(issue.startswith(('«всё»', 'время')) for issue in issues):
            status = 'unsupported'
        elif missing or any(issue.startswith(('неизвестный объект', 'неизвестное место')) for issue in issues):
            status = 'not_found'
        elif incomplete or any(issue.startswith(('не указан', 'ссылка')) for issue in issues):
            status = 'incomplete'
        elif incompatible:
            status = 'incompatible'
        elif not candidates:
            status = 'not_found'
        elif choice or any(issue.startswith(('несколько действий', 'непонятные слова')) for issue in issues):
            status = 'ambiguous'
        elif candidates[0]['careful']:
            status = 'ambiguous'
            issues = issues + ['осторожный объект распознан неточно — нужно подтверждение']
        elif len(candidates) == 1 or candidates[0]['score'] - candidates[1]['score'] >= MARGIN:
            status = 'resolved'
        else:
            status = 'ambiguous'
            issues = issues + ['несколько близких вариантов — нужно уточнение']
        return {'status': status, 'candidates': candidates, 'issues': issues}


def unknown_words(spans):
    """Делит незнакомые слова команды по месту в запросе.

    До первого действия, объекта или спецкоманды — обращение («привет», «алиса,
    включи…»): пропускаем с пометкой. Сразу после «в»/«на» — место, которого нет
    в каталоге («в гараже»): команду не выбираем. Остальные — лишние слова
    («включи свет быстро»): кандидат есть, но нужно подтверждение.
    """
    first = next((number for number, span in enumerate(spans) if span.kind in ('action', 'object', 'special')), len(spans))
    leading, places, extra = [], [], []
    for number, span in enumerate(spans):
        if span.kind != 'unknown':
            continue
        if number < first:
            leading.append(span.text)
        elif number and spans[number - 1].op == 'prep':
            places.append(span.text)
        else:
            extra.append(span.text)
    return leading, places, extra


def has_content(spans):
    return any(span.kind in ('action', 'special', 'object') for span in spans)


def clauses(spans):
    """Режет запрос на команды: «и» или запятая перед действием начинают новую."""
    parts, current = [], []
    for number, span in enumerate(spans):
        if span.op == 'and':
            rest = []
            for following in spans[number + 1:]:
                if following.op == 'and':
                    break
                rest.append(following)
            if any(item.kind in ('action', 'special') for item in rest) and has_content(current):
                parts.append(current)
                current = []
                continue
        current.append(span)
    if current:
        parts.append(current)
    return parts


def mentions(spans):
    """Собирает упоминания объектов: «свет и телевизор на кухне», «на кухне и в спальне»."""
    found, link, after_prep = [], None, False
    current = None
    for span in spans:
        if span.op in ('and', 'or'):
            link, after_prep = span.op, False
            current = None
            continue
        if span.op == 'prep':
            after_prep = True
            continue
        if span.kind != 'object':
            if span.kind == 'action':
                after_prep = False
            continue
        if current is None:
            if after_prep and found and link:          # «… и в спальне»: тот же объект, другое место
                current = Mention(link, found[-1].words, copied=True)
            else:
                current = Mention(link if found else None)
            found.append(current)
            link = None
        (current.qualifiers if after_prep else current.words).append(span.alts)
        after_prep = False
    for number, mention in enumerate(found):
        if mention.qualifiers and not mention.copied:
            chain = number
            while chain > 0 and found[chain].link == 'and' and not found[chain - 1].qualifiers:
                chain -= 1
                mention.shared.append(chain)
    return found


def explain_typos(alt):
    return [f'«{typed}» → «{word}»: {edit_kind(typed, word)}' for typed, word in alt.typos]
