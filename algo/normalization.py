"""Нормализация текста перед поиском.

Одна и та же функция применяется к запросу и к формам каталога, чтобы обе
стороны сравнивались в одинаковом виде. Результат помнит, что было исправлено
и что выброшено, — это пригодится для объяснения выдачи.

Шаги:
1. нижний регистр, ё → е;
2. слово, набранное в английской раскладке, переводится в русскую: `cdtn` → `свет`;
3. дефисы и пунктуация режут слово: `робот-пылесос` → `робот пылесос`;
4. три и больше одинаковых буквы подряд сжимаются до двух: `теплеее` → `теплее`;
5. выбрасываются параметры: числа с единицами и временем (`на семь утра`,
   `на 22 градуса`) и время после предлога (`на завтра`). Одиночное «сегодня»
   в «какой сегодня день» остаётся — это не параметр команды;
6. выбрасываются слова-паразиты: `алиса`, `пожалуйста`, `можешь`;
7. повторы подряд схлопываются: `стоп стоп стоп` → `стоп`.

Частица «не» никогда не выбрасывается. Если за ней идёт глагол («не включай»,
«не надо»), запрос помечается `negated`, а решать, отказывать ли, должен алгоритм.
Опечатка вроде «поставь не паузу» отрицанием не считается.
"""

import re
from dataclasses import dataclass, field

_LAYOUT = str.maketrans(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,.`",
    'йцукенгшщзхъфывапролджэячсмитьбюе',
)
_LATIN = re.compile('[a-z]')
_LAYOUT_WORD = re.compile(r"[a-z\[\];',.`]+")
_NOT_WORD = re.compile('[^0-9a-zа-я]+')
_LONG_RUN = re.compile(r'(.)\1{2,}')

# Слова, которые не меняют смысл команды. «мне», «всё», «не» сюда добавлять нельзя:
# «позвони мне», «выключи всё», «не открывай дверь» значат другое без них.
FILLERS = frozenset({
    'алиса', 'алис', 'яндекс', 'эй', 'слушай', 'слушайте', 'окей', 'ок',
    'пожалуйста', 'плиз', 'будь', 'будьте', 'добра', 'добр', 'добры',
    'можешь', 'можете', 'можно', 'мог', 'могла', 'могли', 'бы', 'ты', 'вы',
    'ну', 'а', 'так', 'вот', 'уже', 'давай', 'давайте', 'ка', 'же', 'ли', 'ладно',
    'чуть', 'немного', 'немножко', 'слегка',
})
NEGATION_WORDS = frozenset({'нельзя'})
NEGATED_MODALS = frozenset({'надо', 'нужно', 'стоит', 'смей'})
VERB_ENDINGS = ('й', 'и', 'ь', 'те', 'ть', 'ти', 'чь')
NUMBER_WORDS = frozenset({
    'ноль', 'нуль', 'один', 'одна', 'одно', 'одну', 'два', 'две', 'три', 'четыре', 'пять',
    'шесть', 'семь', 'восемь', 'девять', 'десять', 'одиннадцать', 'двенадцать', 'тринадцать',
    'четырнадцать', 'пятнадцать', 'шестнадцать', 'семнадцать', 'восемнадцать', 'девятнадцать',
    'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят', 'семьдесят', 'восемьдесят',
    'девяносто', 'сто', 'полчаса', 'полтора', 'половину',
})
UNITS = frozenset({
    'градус', 'градуса', 'градусов', 'минута', 'минуту', 'минуты', 'минут', 'час', 'часа', 'часов',
    'секунда', 'секунду', 'секунды', 'секунд', 'процент', 'процента', 'процентов',
})
TIME_WORDS = frozenset({
    'утро', 'утра', 'утром', 'вечер', 'вечера', 'вечером', 'ночи', 'ночью', 'дня', 'днем',
    'сегодня', 'завтра', 'послезавтра',
})
PREPOSITIONS = frozenset({'на', 'в', 'во', 'до', 'через', 'к', 'по', 'около'})


@dataclass
class NormalizedText:
    text: str
    tokens: list
    negated: bool = False
    layout_fixed: list = field(default_factory=list)  # пары (как набрано, как исправлено)
    removed: list = field(default_factory=list)  # выброшенные слова по порядку


def _parameter_flags(tokens):
    """Какие слова — параметры команды (числа, единицы, время), а не её суть."""
    flags = [token.isdigit() or token in NUMBER_WORDS for token in tokens]
    for position, token in enumerate(tokens):
        if position and (token in UNITS or token in TIME_WORDS):
            previous = tokens[position - 1]
            if flags[position - 1] or previous in PREPOSITIONS:
                flags[position] = True
    for position in range(len(tokens) - 1):
        if tokens[position] in PREPOSITIONS and flags[position + 1]:
            flags[position] = True
    return flags


def _is_negated(tokens):
    if any(token in NEGATION_WORDS for token in tokens):
        return True
    return any(
        token == 'не' and (following in NEGATED_MODALS or following.endswith(VERB_ENDINGS))
        for token, following in zip(tokens, tokens[1:])
    )


def normalize_text(text):
    tokens, layout_fixed = [], []
    for word in text.lower().replace('ё', 'е').split():
        if _LATIN.search(word) and _LAYOUT_WORD.fullmatch(word):
            fixed = word.translate(_LAYOUT)
            layout_fixed.append((word, fixed))
            word = fixed
        tokens.extend(_LONG_RUN.sub(r'\1\1', piece) for piece in _NOT_WORD.split(word) if piece)

    kept, removed = [], []
    for token, is_parameter in zip(tokens, _parameter_flags(tokens)):
        if is_parameter or token in FILLERS:
            removed.append(token)
        elif not kept or kept[-1] != token:
            kept.append(token)
    if not kept:  # запрос из одних служебных слов оставляем как есть
        kept, removed = tokens, []

    return NormalizedText(
        text=' '.join(kept),
        tokens=kept,
        negated=_is_negated(kept),
        layout_fixed=layout_fixed,
        removed=removed,
    )
