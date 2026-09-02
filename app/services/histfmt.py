"""이력 표시용 포맷터 (FR-10-2)."""
from __future__ import annotations

from ..core import HIST_LABELS, jload
from .assets import FIELD_LABELS


def _disp(v) -> str:
    if v is None or v == "":
        return "(없음)"
    return str(v)


def format_history(row) -> dict:
    r = dict(row)
    before = jload(r.get("before_json"))
    after = jload(r.get("after_json"))
    extra = jload(r.get("extra_json"))

    keys = list(dict.fromkeys(list(before.keys()) + list(after.keys())))
    changes = [{
        "field": k,
        "label": FIELD_LABELS.get(k, k),
        "before": before.get(k),
        "after": after.get(k),
    } for k in keys]

    summary = " / ".join(
        f"{c['label']}: {_disp(c['before'])} → {_disp(c['after'])}" for c in changes
    ) or (extra.get("note") or "")

    return {
        "id": r["id"],
        "asset_id": r["asset_id"],
        "asset_no": r["asset_no"],
        "hist_type": r["hist_type"],
        "hist_type_label": HIST_LABELS.get(r["hist_type"], r["hist_type"]),
        "occurred_at": r["occurred_at"],
        "actor": r["actor"],
        "reason": r.get("reason"),
        "changes": changes,
        "extra": extra,
        "summary": summary,
    }
