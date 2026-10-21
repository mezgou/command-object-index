import json
from pathlib import Path
import time
from matcher import CommandMatcher


def run_benchmark():
    base_dir = Path(__file__).resolve().parent.parent
    vocab_file = base_dir / "data" / "vocabulary.json"
    dataset_file = base_dir / "data" / "dataset.json"

    matcher = CommandMatcher(vocab_file)

    with open(dataset_file, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    stats = {
        "total": len(dataset),
        "exact_matches": 0,
        "ambiguous_rejects": 0,
        "errors": 0,
        "by_label": {},
    }

    ambiguous_examples = []
    failed_examples = []
    start_time = time.perf_counter()

    for item in dataset:
        query = item["query"]
        expected_act = item["action"]
        expected_tgt = item["target"]
        label = item.get("label", "unknown")

        stats["by_label"].setdefault(label, {"total": 0, "correct": 0})
        stats["by_label"][label]["total"] += 1

        result = matcher.parse(query)

        if (
            result["status"] == "SUCCESS"
            and result["action"] == expected_act
            and result["target"] == expected_tgt
        ):
            stats["exact_matches"] += 1
            stats["by_label"][label]["correct"] += 1
        elif result["status"] == "AMBIGUOUS_REJECT":
            stats["ambiguous_rejects"] += 1
            ambiguous_examples.append(query)
        else:
            stats["errors"] += 1
            failed_examples.append(
                f"'{query}' -> status: {result['status']}, got: ({result['action']}, {result['target']}), expected: ({expected_act}, {expected_tgt})"
            )

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    avg_latency = elapsed_ms / len(dataset)

    print("=== ОТЧЕТ О ТЕСТИРОВАНИИ ИНДЕКСА ===")
    print(f"Всего тестовых сценариев: {stats['total']}")
    print(
        f"Успешно распознано:       {stats['exact_matches']}/{stats['total']} ({stats['exact_matches']/stats['total']:.2%})"
    )
    print(
        f"Безопасных отказов:       {stats['ambiguous_rejects']} (перехваченные коллизии)"
    )
    print(f"Ошибок распознавания:     {stats['errors']}")
    print(f"Средняя задержка:         {avg_latency:.3f} мс / запрос\n")

    print("Точность по категориям:")
    for cat, data in stats["by_label"].items():
        acc = data["correct"] / data["total"] if data["total"] else 0
        print(f"  • {cat:<10}: {data['correct']}/{data['total']} ({acc:.2%})")

    if ambiguous_examples:
        print(f"\nСписок перехваченных коллизий ({len(ambiguous_examples)}):")
        for q in ambiguous_examples:
            print(f"  [AMBIGUOUS_REJECT] -> '{q}'")

    if failed_examples:
        print(f"\nСписок ошибок ({len(failed_examples)}):")
        for err in failed_examples:
            print("  -", err)


if __name__ == "__main__":
    run_benchmark()