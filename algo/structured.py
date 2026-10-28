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
from functools import lru_cache
from itertools import product

from algo import tfidf_char
from algo.shared import DeletionIndex, edit_kind, osa, tokens

try:
    import pymorphy3
except ImportError:           # метод structured-morph без библиотеки недоступен, structured работает
    pymorphy3 = None

OPERATORS = {
    'and': ['и', 'а также', ','],
    'or': ['или', 'либо'],
    'neg': ['не', 'не надо', 'не нужно', 'нельзя'],
    'correction': ['нет', 'вернее', 'точнее', 'то есть'],
    'except': ['кроме', 'за исключением'],
    'all': ['всё', 'весь', 'всю', 'везде'],
    'anaphora': ['его', 'её', 'их', 'это', 'там', 'тут'],
    'prep': ['в', 'во', 'на'],
    'filler': ['пожалуйста', 'ну', 'давай', 'можешь', 'мне', 'ка', 'а', 'бы', 'сейчас', 'ой', 'тоже', 'ещё', 'также'],
    'address': ['привет', 'слушай', 'алиса', 'эй', 'короче', 'окей', 'здравствуй', 'хей'],
    'mod': ['через', 'завтра', 'сегодня', 'утром', 'вечером', 'ночью', 'потом', 'позже',
            'секунду', 'секунд', 'минуту', 'минуты', 'минут', 'час', 'часа', 'часов', 'полчаса',
            'один', 'одну', 'два', 'две', 'три', 'пять', 'десять', 'двадцать', 'тридцать',
            'процентов', 'градусов', 'наполовину'],
}
# Языковые связи — знание о русском языке, а не о конкретной квартире, поэтому живут здесь, а не в блоках.
# Одна группа — синонимы: «зажги» ведёт к блокам с «включи», даже если в каталоге «зажги» нет.
# Пары OPPOSITE — антонимы (confusion set): если слово запроса похоже на членов обеих групп,
# выбор никогда не уверенный, даже если одно из расстояний меньше.
GROUPS = {
    'turn_on': ['включить', 'включи', 'включай', 'включите', 'включишь', 'зажечь', 'зажги', 'зажгите', 'зажжёшь',
                'вруби', 'врубить', 'врубай', 'активируй', 'активировать'],
    'turn_off': ['выключить', 'выключи', 'выключай', 'выключите', 'выключишь', 'отключи', 'отключить', 'отключите',
                 'погаси', 'погасить', 'погасите', 'выруби', 'вырубить', 'вырубай'],
    'open': ['открыть', 'открой', 'откройте', 'откроешь', 'открывай', 'распахни'],
    'close': ['закрыть', 'закрой', 'закройте', 'закроешь', 'закрывай', 'запри', 'запереть', 'прикрой'],
    'start': ['запустить', 'запусти', 'запустите', 'начни', 'начать'],
    'stop': ['остановить', 'останови', 'остановите', 'остановишь'],
    'louder': ['громче', 'погромче', 'громко'],
    'quieter': ['тише', 'потише', 'тихо'],
    'warmer': ['теплее', 'потеплее', 'тепло'],
    'colder': ['холоднее', 'похолоднее', 'прохладно'],
}
OPPOSITE = [('turn_on', 'turn_off'), ('open', 'close'), ('start', 'stop'), ('louder', 'quieter'), ('warmer', 'colder')]
# Объекты, для которых опечатка никогда не даёт уверенного выбора: ошибка здесь
# дороже переспроса. В схеме блока нет поля риска, поэтому список — часть политики.
CAREFUL = {'дверь', 'двери', 'замок', 'холодильник', 'плиту', 'газ', 'сигнализацию'}
FUZZY_PENALTY = 0.15      # штраф качества за одну опечатку
MARGIN = 0.10             # насколько лучший кандидат должен опережать второй
READING_MARGIN = 0.05     # то же для прочтений всего запроса
LIMIT = 5                 # кандидатов на одну команду
MISSING_ACTION = 0.5      # множитель кандидатов, если действие не названо
HINTS = 3                 # подсказок TF-IDF, если структурный разбор ничего не нашёл
HINT_MIN = 0.5            # ниже этой близости TF-IDF подсказка — шум («свари кофе» → 0.36)
STATUS_ORDER = ['negated', 'unsupported', 'not_found', 'incompatible', 'incomplete', 'ambiguous', 'resolved']
_CACHE = {}
_MORPH = []


def search(query, blocks, morph=False):
    """Возвращает ранжированные блоки по контракту платформы и разбор запроса.

    Результаты идут по командам запроса: сначала кандидаты первой команды,
    потом второй. Поле `command` — номер команды, `status` — её статус,
    `decision` — решение по всему запросу, `explain` — почему блок здесь.
    """
    analysis = analyze(query, blocks, morph)
    commands = analysis['commands'] or [{'status': 'not_found', 'candidates': [], 'issues': [], 'source': query}]
    results = []
    for number, command in enumerate(commands, 1):
        for candidate in command['candidates'] or hints(command.get('source') or query, blocks):
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


def hints(text, blocks):
    """Гибрид для пустого ответа: похожие формулировки от TF-IDF, только как подсказка.

    Структурный разбор не нашёл ни одного кандидата — например, «открой шторы на
    кухне», когда штор на кухне нет. Решение остаётся отказом, но пользователь
    видит, что было в каталоге рядом.
    """
    found = [result for result in tfidf_char.search(text, blocks) if result['score'] >= HINT_MIN][:HINTS]
    return [{**result, 'explain': ['может, вы имели в виду… (похожая формулировка, TF-IDF)']} for result in found]


def search_morph(query, blocks):
    """То же, что `search`, но слова сравниваются ещё и по лемме (pymorphy3).

    «включите», «погасите», «лампы», «музыка» совпадают с «включи», «погаси»,
    «лампу», «музыку» из каталога без перечисления всех форм в блоках.
    """
    if pymorphy3 is None:
        raise ValueError('Для метода structured-morph нужен pymorphy3: pip install -r backend/requirements.txt')
    return search(query, blocks, morph=True)


@lru_cache(maxsize=50000)
def lemmas(word):
    """Начальные формы слова по словарю OpenCorpora; для незнакомых словарю слов — ничего.

    Догадкам pymorphy о незнакомых словах не верим: опечатка «выключа» иначе
    получила бы лемму и обошла проверку ничьей «включи / выключи».
    """
    if not _MORPH:
        _MORPH.append(pymorphy3.MorphAnalyzer())
    morph = _MORPH[0]
    if not morph.word_is_known(word):
        return frozenset()
    return frozenset(parse.normal_form.replace('ё', 'е') for parse in morph.parse(word))


def analyze(query, blocks, morph=False):
    """Полный разбор: решение, команды с кандидатами и пояснения."""
    index = lexicon_for(blocks, morph)
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


def lexicon_for(blocks, morph=False):
    """Индекс строится один раз на содержимое каталога: правка блока меняет ключ."""
    key = (morph, json.dumps(blocks, ensure_ascii=False, sort_keys=True))
    if key not in _CACHE:
        if len(_CACHE) >= 4:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = Lexicon(blocks, morph)
    return _CACHE[key]


class Lexicon:
    """Словарь блоков: фразы действий и спецкоманд, слова объектов, служебные слова."""

    def __init__(self, blocks, morph=False):
        self.blocks = {block['index']: block for block in blocks}
        self.operators = {}
        for kind, words in OPERATORS.items():
            for word in words:
                self.operators[tuple(tokens(word)) or (word,)] = kind
        function_words = {word for phrase in self.operators for word in phrase}
        self.phrases = {}          # слова фразы → [(вид, alias, множество блоков)]
        self.objects = []          # (блок, alias, значимые слова alias, alias — состояние, а не устройство)
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
                    # Состояние, а не устройство: «на паузу» (с предлога) или «громче», «тише» — у блока есть
                    # и действие («сделай»), и форма без него. К такому объекту можно добавить цель:
                    # «сделай музыку громче». Самостоятельная команда без действий («отмена») — не состояние.
                    optional = '' in actions and any(actions)
                    state = self.operators.get((tokens(alias)[0],)) == 'prep' or optional
                    self.objects.append((block['index'], alias, words, state))
        # Синонимы действий: группа → все блоки, где встречается любое её слово-действие. Слова группы,
        # которых нет в блоках, добавляются как действия без своих блоков — только через синонимию.
        self.group_of = {tokens(word)[0]: group for group, words in GROUPS.items() for word in words}
        self.group_blocks = {}
        for phrase, entries in self.phrases.items():
            group = self.group_of.get(phrase[0]) if len(phrase) == 1 else None
            for kind, _, indexes in entries:
                if group and kind == 'action':
                    self.group_blocks.setdefault(group, set()).update(indexes)
        for group, words in GROUPS.items():
            if group in self.group_blocks:
                for word in words:
                    phrase = tuple(tokens(word))
                    if not any(entry[0] == 'action' for entry in self.phrases.get(phrase, [])):
                        self.phrases.setdefault(phrase, []).append(('action', word, set()))
        # Полные наборы слов объектов: по ним узнаём цель разрывного действия («музыку» в «поставь музыку на паузу»).
        self.targets = {}
        for _, alias, words, _ in self.objects:
            self.targets.setdefault(frozenset(words), alias)
        self.longest = max([len(phrase) for phrase in list(self.phrases) + list(self.operators)] or [1])
        self.vocabulary = {word for phrase in self.phrases for word in phrase} | set(self.by_word)
        self.fuzzy = DeletionIndex(self.vocabulary - function_words)
        self.function_words = function_words
        # Лемма → слова каталога. Только действия и объекты: у спецкоманд леммы
        # опасны («далеко» и «дальше» — обе формы слова «далёкий»).
        self.by_lemma = {}
        if morph:
            words = {word for phrase, entries in self.phrases.items() for word in phrase
                     if any(entry[0] == 'action' for entry in entries)} | set(self.by_word)
            for word in words - function_words:
                for lemma in lemmas(word):
                    self.by_lemma.setdefault(lemma, set()).add(word)

    def synonyms(self, alias, own):
        """Блоки, куда ведёт действие через синонимию, кроме своих, и группа действия."""
        words = tokens(alias)
        group = self.group_of.get(words[0]) if len(words) == 1 else None
        return self.group_blocks.get(group, set()) - own, group

    def confusions(self, spans):
        """Пары антонимов, между которыми колеблется хотя бы одно слово запроса."""
        found = []
        for span in spans:
            groups = {}
            for alt in span.alts:
                groups.setdefault(self.group_of.get(alt.alias), alt.alias)
            for left, right in OPPOSITE:
                if left in groups and right in groups:
                    found.append(f'опечатка между противоположными: «{groups[left]}» / «{groups[right]}»')
        return found

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
        """Варианты слова `(слово каталога, опечаток, как совпало)`.

        Точное совпадение побеждает; затем та же лемма (если включена морфология);
        иначе ближайшие по OSA. `как`: exact | form | typo.
        """
        if word in self.vocabulary:
            return [(word, 0, 'exact')]
        if word in self.function_words or word.isdigit():
            return []
        if self.by_lemma:
            forms = {form for lemma in lemmas(word) for form in self.by_lemma.get(lemma, ())}
            forms = sorted(forms, key=lambda form: (osa(word, form), form))    # ближайшая форма — в текст ответа
            if forms:
                return [(form, 0, 'form') for form in forms][:6]
        found = self.fuzzy.lookup(word)
        if not found:
            return []
        best = found[0][1]
        return [(found_word, distance, 'typo') for found_word, distance in found if distance <= best + 1][:6]

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
                # Для одного слова смотрим все варианты: иначе ближайшие формы «выключ…» вытесняют
                # антоним «включить» и опечатка между ними выглядит уверенной.
                width = 6 if length == 1 else 3
                for combo in product(*[variants[start + shift][:width] for shift in range(length)]):
                    for kind, alias, indexes in self.phrases.get(tuple(word for word, _, _ in combo), []):
                        distance = sum(distance for _, distance, _ in combo)
                        typos = [(words[start + shift], word, how) for shift, (word, _, how) in enumerate(combo) if how != 'exact']
                        by_kind.setdefault(kind, []).append(Alt(alias, distance, typos, indexes))
                for kind, alts in by_kind.items():
                    alts = best_alternatives(alts)
                    quality = 1 - FUZZY_PENALTY * alts[0].distance
                    options[start].append((start + length, length * quality - 0.01, Span(kind, start, length, words, alts=alts)))
            if variants[start] and any(word in self.by_word for word, _, _ in variants[start]):
                alts = [Alt(word, distance, [(words[start], word, how)] if how != 'exact' else [], set())
                        for word, distance, how in variants[start] if word in self.by_word]
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
            own = mentions(part)
            if not own and any(span.kind == 'action' for span in part):
                for later in parts[number + 1:]:
                    if mentions(later):
                        current = {'mentions': mentions(later)}
                        notes.append('общий объект для нескольких действий')
                        break
            if number and any(span.kind == 'action' for span in part) and 'mentions' not in current:
                current = {**current, **ellipsis(own, parts[:number])}
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
        """Две уверенные команды над одним объектом с разными действиями: «открой и закрой шторы».

        Синонимы («включи и зажги свет») противоречием не считаются.
        """
        chosen = [command['candidates'][0] for command in commands if command['status'] == 'resolved' and command['candidates']]
        seen = {}
        for candidate in chosen:
            previous = seen.get(candidate['object'])
            if previous and previous['index'] != candidate['index'] and not (previous['group'] and previous['group'] == candidate['group']):
                return True
            seen[candidate['object']] = candidate
        return False

    def commands(self, spans, inherited, spread):
        result = self.clause(spans, inherited, spread)
        first = next((number for number, span in enumerate(spans) if span.kind in ('action', 'object', 'special')), len(spans))
        source = ' '.join(span.text for number, span in enumerate(spans)
                          if (span.kind != 'op' or span.op == 'prep') and not (span.kind == 'unknown' and number < first))
        for command in result:
            command['source'] = source          # для подсказок TF-IDF: без обращений и служебных слов
        return result

    def clause(self, spans, inherited, spread):
        index = self.index
        actions = [span for span in spans if span.kind == 'action'] or inherited.get('actions', [])
        specials = [span for span in spans if span.kind == 'special']
        ops = {span.op for span in spans if span.op}
        modifiers = [span.text for span in spans if span.op == 'mod']
        found = inherited.get('override') or mentions(spans) or inherited.get('mentions', [])
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
        addresses = [span.text for span in spans if span.op == 'address']
        if addresses:
            issues.append('пропущено обращение: ' + ', '.join(addresses))
        if inherited.get('note'):
            issues.append(inherited['note'])
        if 'anaphora' in ops and not found:
            issues.append('ссылка на прошлую команду без контекста')
        if len({alt.alias for span in actions for alt in span.alts[:1]}) > 1:
            issues.append('несколько действий без союза')
        issues.extend(index.confusions([span for span in spans if span.alts]))

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
            unknown_object = any(issue.startswith('неизвестный объект') for issue in issues)
            candidates = []
            for span in actions[:1] if not unknown_object else []:      # для незнакомого объекта — подсказки TF-IDF
                for alt in span.alts:
                    synonyms, group = index.synonyms(alt.alias, alt.indexes)
                    for item in sorted(alt.indexes | synonyms):
                        candidates.append(self.candidate(item, alt.alias, alt.quality * MISSING_ACTION, explain_typos(alt), '',
                                                         alt.distance > 0, group, item in synonyms))
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
                        synonyms, group = index.synonyms(alt.alias, alt.indexes)
                        if item in alt.indexes or item in synonyms:
                            note = [] if item in alt.indexes else                                 [f'«{alt.alias}» — то же действие, что «{index.blocks[item]["text"].split()[0]}»']
                            candidates.append(self.candidate(item, alt.alias, alt.quality * quality,
                                                             explain_typos(alt) + explain + note, alias, typo, group, bool(note)))
                        else:
                            others.append(self.candidate(item, alt.alias, alt.quality * quality * MISSING_ACTION,
                                                         explain_typos(alt) + explain, alias, typo, group))
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
            item, alias, alias_words, complement = index.objects[number]
            matched, typos, unexplained = {}, [], []
            for alts in words:
                hit = [alt for alt in alts if alt.alias in alias_words]
                if not hit:
                    unexplained.append(alts)
                    continue
                alt = min(hit, key=lambda alt: alt.distance)
                matched[alt.alias] = max(matched.get(alt.alias, 0), alt.quality)
                typos.extend(alt.typos)
            target = self.target(unexplained) if unexplained and complement else None
            if (unexplained and not target) or not matched:
                continue
            if target:
                alias = f'{target[0]} {alias}'          # «на паузу» + цель «музыку» → «музыку на паузу»
                typos.extend(target[1])
            completeness = len(matched) / len(set(alias_words))
            quality = sum(matched.values()) / len(matched) * (0.6 + 0.4 * completeness)
            explain = [describe(*typo) for typo in typos]
            if completeness < 1:
                explain.append(f'неполное название: совпало {len(matched)} из {len(set(alias_words))} слов «{alias}»')
            if target:
                explain.append(f'«{target[0]}» — цель действия, а не отдельная команда')
            if item not in best or quality > best[item][2]:
                best[item] = (item, alias, quality, explain, any(how == 'typo' for _, _, how in typos))
        return list(best.values())

    def target(self, unexplained):
        """Оставшиеся слова — ровно чей-то объект? Тогда это цель разрывного действия."""
        for words, alias in self.index.targets.items():
            if len(words) != len(unexplained):
                continue
            hits = [[alt for alt in alts if alt.alias in words] for alts in unexplained]
            if all(hits) and {min(hit, key=lambda alt: alt.distance).alias for hit in hits} == set(words):
                return alias, [typo for hit in hits for typo in min(hit, key=lambda alt: alt.distance).typos]
        return None

    def candidate(self, item, action, quality, explain, alias, fuzzy=False, group=None, via_synonym=False):
        block = self.index.blocks[item]
        text = ' '.join(part for part in (action, alias) if part) or block['text']
        objects = block.get('objects') or [block['text']]
        careful = any(word in CAREFUL for name in objects for word in tokens(name))
        return {'index': item, 'text': text, 'score': quality, 'explain': list(dict.fromkeys(explain)),
                'object': tuple(sorted(objects)), 'group': group, 'via_synonym': via_synonym,
                'careful': careful and (fuzzy or any(line.startswith('неполное') for line in explain))}

    def status(self, candidates, issues, incomplete=False, incompatible=False, missing=None, choice=False):
        # Блок со «своим» действием важнее блока-дубля, найденного через синоним («зажги свет на кухне»
        # и «включи свет на кухне» с тем же объектом) — иначе синонимия создаёт ложную ничью.
        direct = {(candidate['object'], candidate['group']) for candidate in candidates if not candidate['via_synonym']}
        candidates = [candidate for candidate in candidates
                      if not (candidate['via_synonym'] and (candidate['object'], candidate['group']) in direct)]
        unique = {}
        order = lambda candidate: (-candidate['score'], self.index.blocks[candidate['index']]['text'])   # ничья — по тексту, не по номеру
        for candidate in sorted(candidates, key=order):
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
        elif choice or any(issue.startswith(('несколько действий', 'непонятные слова', 'опечатка между противоположными'))
                           for issue in issues):
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


def ellipsis(own, previous_parts):
    """«включи свет на кухне, а в спальне выключи»: объект второй команды — из первой.

    Если у команды есть только место, слова объекта берутся из последнего
    упоминания предыдущих команд; если объекта нет совсем — упоминание целиком.
    """
    previous = next((mentions(part)[-1] for part in reversed(previous_parts) if mentions(part)), None)
    if previous is None or not previous.words:
        return {}
    note = 'объект взят из предыдущей команды'
    if not own:
        return {'mentions': [previous], 'note': note}
    if all(not mention.words for mention in own):
        copied = []
        for mention in own:
            copy = Mention(mention.link, previous.words, copied=True)
            copy.qualifiers = list(mention.qualifiers)
            copied.append(copy)
        return {'override': copied, 'note': note}
    return {}


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
    return [describe(*typo) for typo in alt.typos]


def describe(typed, word, how):
    if how == 'form':
        return f'«{typed}» → «{word}»: другая форма слова'
    edits = osa(typed, word)
    return f'«{typed}» → «{word}»: {edit_kind(typed, word) if edits == 1 else f"{edits} правки"}'
