import random
import json

# Словарь
ACTIONS = {
    "turn_on": ["включи", "включить", "зажги", "вруби", "активируй"],
    "turn_off": ["выключи", "выключить", "погаси", "выруби", "отключи"],
    "open": ["открой", "открыть", "распахни", "отопри"],
    "close": ["закрой", "закрыть", "прикрой", "запри"],
}

TARGETS = {
    "light": ["свет", "лампа", "люстра", "ночник", "подсветка"],
    "door": ["дверь", "замок", "калитку", "окно"],
    "vacuum": ["пылесос", "робот", "уборщик"],
    "tv": ["телевизор", "телик", "тв", "экран"],
}


def add_typo(word: str) -> str:
    """Вносит одну случайную опечатку"""
    if len(word) < 4:
        return word

    chars = list(word)
    op = random.choice(["swap", "delete", "replace"])

    if op == "swap":
        idx = random.randint(0, len(chars) - 2)
        chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
    elif op == "delete":
        idx = random.randint(0, len(chars) - 1)
        chars.pop(idx)
    elif op == "replace":
        idx = random.randint(0, len(chars) - 1)
        chars[idx] = random.choice("абвгдежзийклмнопрстуфхцчшщыэюя")

    return "".join(chars)


def generate_dataset():
    dataset = []

    for act_key, act_words in ACTIONS.items():
        for tgt_key, tgt_words in TARGETS.items():
            for act in act_words:
                for tgt in tgt_words:
                    # 1. Прямой порядок ("включи свет")
                    dataset.append(
                        {
                            "query": f"{act} {tgt}",
                            "action": act_key,
                            "target": tgt_key,
                            "label": "exact",
                        }
                    )

                    # 2. Обратный порядок ("свет включи")
                    dataset.append(
                        {
                            "query": f"{tgt} {act}",
                            "action": act_key,
                            "target": tgt_key,
                            "label": "inverted",
                        }
                    )

                    # 3. Вариант с опечаткой в одном из слов
                    noisy_act = add_typo(act) if random.random() > 0.5 else act
                    noisy_tgt = (
                        add_typo(tgt) if noisy_act == act else tgt
                    )  # опечатка только в одном месте

                    dataset.append(
                        {
                            "query": f"{noisy_act} {noisy_tgt}",
                            "action": act_key,
                            "target": tgt_key,
                            "label": "typo",
                        }
                    )

    return dataset


data = generate_dataset()
print(f"Всего сгенерировано запросов: {len(data)}")

for sample in random.sample(data, 5):
    print(sample)


# Сохраняем в JSON
with open("dataset.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Всего сгенерировано запросов: {len(data)}")
print("Сохранено в файл dataset.json")