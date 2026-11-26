"""Conservative evidence agreement; absent observations never become misses."""
import math


def collect_matches(refined: dict) -> list[dict]:
    matches = []
    for item in refined["results"]:
        if item["refined"]:
            matches.extend(item["refined"])
        else:
            matches.append({
                **item["coarse"], "verdict": "ambiguous", "coarse_crossing": True,
                "overlay": {"rim": item.get("rim_local", item.get("rim_original")),
                            "trajectory": item.get("fallback_trajectory", [])},
            })
    return matches


def classify_events(matches: list[dict], rim_checks: list[dict]) -> list[dict]:
    events = []
    for i, match in enumerate(matches):
        timestamp = float(match["time"])
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("事件时间无效")
        check = rim_checks[i] if i < len(rim_checks) else {"status": "skipped", "reason": "check_missing"}
        verdict, status = match.get("verdict"), check.get("status")
        positive = verdict == "made"
        negative = verdict == "missed"
        if positive and status == "made" and not match.get("coarse_crossing"):
            label, reason = "made", "trajectory_and_rim_agree"
        elif (positive and status == "rejected") or (negative and status == "made"):
            label, reason = "uncertain", "conflicting_evidence"
        elif negative and status == "rejected":
            label, reason = "missed", check.get("reason") or "negative_evidence"
        else:
            label, reason = "uncertain", check.get("reason") or "insufficient_evidence"
        overlay = match.get("overlay") or {}
        events.append({"time": timestamp, "label": label, "reason": reason,
                       "rim": overlay.get("rim"), "trajectory": overlay.get("trajectory", []),
                       "raw_evidence": [{"refined": match, "rim_check": check}]})
    # Merge observations of the same event; contradictions cannot disappear by ranking.
    groups = []
    for event in sorted(events, key=lambda item: item["time"]):
        if groups and event["time"] - groups[-1]["time"] <= 0.8:
            previous = groups[-1]
            previous["raw_evidence"].extend(event["raw_evidence"])
            if previous["label"] != event["label"]:
                previous.update(label="uncertain", reason="duplicate_evidence_disagrees")
            if len(event["trajectory"]) > len(previous["trajectory"]):
                previous["trajectory"] = event["trajectory"]
        else:
            groups.append(event)
    return [{"id": i + 1, **event} for i, event in enumerate(groups)]
