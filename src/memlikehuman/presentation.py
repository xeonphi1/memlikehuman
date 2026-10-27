"""Age changes what is surfaced, never what is preserved in the diary."""

from datetime import datetime

from .config import Settings
from .store import terms

EPISODIC_KINDS = {"episode", "observation", "emotion"}


def age_days(when: str, at: str) -> float:
    return max(
        0, (datetime.fromisoformat(at) - datetime.fromisoformat(when)).total_seconds() / 86400
    )


def period(when: str, age: float, settings: Settings) -> str:
    year = datetime.fromisoformat(when).year
    return f"{year // 10 * 10}年代" if age >= settings.distant_after_days else f"{year}年"


def topic_gist(content: str) -> str:
    # Extractive cue labels only. Do not fabricate a story or truncate a sentence into a false claim.
    stop = {
        "用户",
        "助手",
        "我们",
        "他们",
        "一个",
        "一次",
        "现在",
        "记录",
        "当时",
        "已经",
        "没有",
        "可能",
        "不是",
        "知道",
    }
    cues = list(
        dict.fromkeys(
            t
            for t in terms(content)
            if len(t) >= 2 and not any(c.isdigit() for c in t) and t not in stop
        )
    )[:4]
    return (
        "旧记录的主题线索：" + "、".join(cues) if cues else "曾有一段记录，具体内容需要查阅原文。"
    )


def render_memory(row: dict, at: str, settings: Settings, detail: str = "auto") -> dict:
    age = age_days(row["valid_at"], at)
    fuzzy = (
        row["kind"] in EPISODIC_KINDS
        and detail != "detailed"
        and (detail == "gist" or age >= settings.gist_after_days)
    )
    if not fuzzy:
        keys = (
            "id",
            "event_id",
            "content",
            "kind",
            "basis",
            "source_quote",
            "confidence",
            "subject",
            "fact_key",
            "valid_at",
            "invalid_at",
            "status",
        )
        return {**{key: row[key] for key in keys}, "resolution": "detailed"}
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "content": row.get("gist") or topic_gist(row["content"]),
        "kind": row["kind"],
        "basis": row["basis"],
        "confidence": row["confidence"],
        "resolution": "distant_gist" if age >= settings.distant_after_days else "gist",
        "period": period(row["valid_at"], age, settings),
        "gist_method": "authored" if row.get("gist") else "extractive_topic_cues",
        "details_available": True,
        "detail_tool": "memory_read",
        "notice": "模糊概览，不是逐字记忆；具体人物、日期和细节须查原文。",
    }
