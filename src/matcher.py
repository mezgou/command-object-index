import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from distance import damerau_levenshtein


class CommandMatcher:

    def __init__(self, vocab_path: Path, max_distance: int = 1):
        self.max_distance = max_distance
        self.word_map: Dict[str, Tuple[str, str]] = {}
        self._load_vocabulary(vocab_path)

    def _load_vocabulary(self, vocab_path: Path) -> None:
        """Загружает словарь и формирует плоскую таблицу поиска."""
        with open(vocab_path, "r", encoding="utf-8") as f:
            vocab = json.load(f)

        for action_name, words in vocab.get("actions", {}).items():
            synonyms = (
                words if isinstance(words, list) else words.get("synonyms", [])
            )
            for w in synonyms:
                self.word_map[w.lower()] = ("action", action_name)

        for target_name, words in vocab.get("targets", {}).items():
            synonyms = (
                words if isinstance(words, list) else words.get("synonyms", [])
            )
            for w in synonyms:
                self.word_map[w.lower()] = ("target", target_name)

    def find_candidates(
        self, token: str
    ) -> Tuple[Optional[Tuple[str, str]], bool]:
        """Ищет совпадение для одного слова.

        Возвращает:
          - (тип_слота, имя_сущности) или None
          - is_ambiguous: True при равной дистанции до конфликтующих команд
        """
        token = token.lower()

        # 1. Точный поиск O(1)
        if token in self.word_map:
            return self.word_map[token], False

        # 2. Нечеткий поиск (допускаем 1 опечатку)
        candidates: List[Tuple[str, Tuple[str, str]]] = []
        min_dist = self.max_distance + 1

        for dict_word, val in self.word_map.items():
            if abs(len(dict_word) - len(token)) > self.max_distance:
                continue

            dist = damerau_levenshtein(token, dict_word)
            if dist < min_dist:
                min_dist = dist
                candidates = [(dict_word, val)]
            elif dist == min_dist:
                candidates.append((dict_word, val))

        if not candidates or min_dist > self.max_distance:
            return None, False

        # Проверка на коллизию (например, слово одновременно похоже на turn_on и turn_off)
        unique_intents = {val for _, val in candidates}
        if len(unique_intents) > 1:
            return None, True

        return candidates[0][1], False

    def parse(self, query: str) -> Dict[str, Any]:
        """Разбирает строку запроса в пару (action, target)."""
        tokens = query.strip().split()
        res_action: Optional[str] = None
        res_target: Optional[str] = None

        for token in tokens:
            match, is_ambiguous = self.find_candidates(token)

            if is_ambiguous:
                return {
                    "status": "AMBIGUOUS_REJECT",
                    "action": None,
                    "target": None,
                    "error": f"Ambiguous token '{token}'",
                }

            if match:
                slot_type, name = match
                if slot_type == "action" and res_action is None:
                    res_action = name
                elif slot_type == "target" and res_target is None:
                    res_target = name

        if not res_action or not res_target:
            return {
                "status": "INCOMPLETE",
                "action": res_action,
                "target": res_target,
                "error": "Missing action or target slot",
            }

        return {
            "status": "SUCCESS",
            "action": res_action,
            "target": res_target,
            "error": None,
        }