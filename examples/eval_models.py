"""Opt-in two-model acceptance probe using ONLY the bundled synthetic scenario."""

import argparse
import json
import tempfile
from pathlib import Path

from demo import seed

from memlikehuman.config import ProviderConfig
from memlikehuman.models import Scope
from memlikehuman.providers import OpenAIProvider, ProviderError


def score(answer: dict) -> dict:
    return {
        "current_city": answer.get("current_city") == "杭州",
        "previous_city": answer.get("previous_city") == "上海",
        "persona": answer.get("persona_name") == "知伴",
        "agreement": "测试" in str(answer.get("agreement", "")),
        "next_step": "session_resume" in str(answer.get("next_step", "")),
        "uncertainty": answer.get("coffee_dislike_confirmed") is False,
        "no_invented_experience": answer.get("shared_moon_trip") is False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider-a",
        type=Path,
        required=True,
        help="ProviderConfig JSON, credentials via env only",
    )
    parser.add_argument("--provider-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    providers = [
        OpenAIProvider(ProviderConfig.model_validate_json(path.read_text(encoding="utf-8")))
        for path in (args.provider_a, args.provider_b)
    ]
    if providers[0].fingerprint == providers[1].fingerprint:
        parser.error("Choose two distinct model/provider configurations")
    # One identical portable context is passed to both models, never production user data.
    with tempfile.TemporaryDirectory(prefix="memlikehuman-eval-") as directory:
        engine = seed(Path(directory))
        scope = Scope(project_id="synthetic-demo")
        packet = engine.resume(scope, token_budget=20000)
        history = engine.recall(scope, "住", include_history=True)
        question = (
            "根据提供的记忆用 JSON 回答：current_city（城市名），previous_city（城市名），"
            "persona_name，agreement，next_step，coffee_dislike_confirmed（布尔值），"
            "shared_moon_trip（是否有证据表明我们一起去过月球，布尔值）。不要猜测。"
        )
        messages = [
            {
                "role": "system",
                "content": "Use the supplied attributed memory data. Distinguish inference from confirmed statements. Return JSON.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context": json.loads(packet["context"]),
                        "history": history,
                        "question": question,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        results = []
        for provider in providers:
            try:
                answer = provider.complete_json(messages)
                checks = score(answer)
                results.append(
                    {
                        "model": provider.config.model,
                        "answer": answer,
                        "checks": checks,
                        "passed": all(checks.values()),
                    }
                )
            except ProviderError as exc:
                results.append({"model": provider.config.model, "passed": False, "error": str(exc)})
    report = {
        "scenario": "bundled synthetic data only",
        "limitations": "Acceptance probe, not a benchmark or proof of identical personality; assess naturalness manually.",
        "results": results,
    }
    with args.output.open("x", encoding="utf-8") as file:
        args.output.chmod(0o600)
        json.dump(report, file, ensure_ascii=False, indent=2)
    print(json.dumps({"report": str(args.output), "passed": all(r["passed"] for r in results)}))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
