import importlib.util
from pathlib import Path

from active_memory.models import Message

spec = importlib.util.spec_from_file_location(
    "import_chatgpt_export", Path(__file__).parent.parent / "scripts" / "import_chatgpt_export.py"
)
imp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imp)


def node(mid, parent, role, parts, t=1760000000.0, ctype="text"):
    message = {
        "id": mid,
        "author": {"role": role},
        "create_time": t,
        "content": {"content_type": ctype, "parts": parts},
    }
    return {"id": mid, "parent": parent, "message": message}


def sample():
    mapping = {
        "root": {"id": "root", "parent": None, "message": None},
        "a": node("a", "root", "system", ["x"]),
        "b": node("b", "a", "user", ["Ahoj"], 1760000001.0),
        "c": node("c", "b", "assistant", ["stará větev"], 1760000002.0),  # abandoned branch
        "d": node("d", "b", "assistant", ["Dobrý den"], 1760000003.0),
        "e": node("e", "d", "user", [""], 1760000004.0),
        "f": node("f", "e", "assistant", [{"asset": 1}], 1760000005.0, "multimodal_text"),
        "g": node("g", "f", "user", ["Díky"], 1760000006.0),
        "h": node("h", "g", "assistant", ["x" * 50001], 1760000007.0),
    }
    return [{"conversation_id": "conv-1", "mapping": mapping, "current_node": "h"}]


def test_current_branch_in_order_with_original_times_and_counts():
    bodies, skipped = imp.convert(sample())
    assert [b["content"] for b in bodies] == ["Ahoj", "Dobrý den", "Díky"]
    assert bodies[0]["occurred_at"].endswith("Z") and bodies[0]["message_id"] == "b"
    assert skipped == {"empty_or_not_text": 2, "other_role": 1, "too_long": 1}
    for body in bodies:
        Message(**body)  # the API accepts exactly these


def test_cycle_and_missing_ids_do_not_hang_or_crash():
    loop = {"x": {"id": "x", "parent": "x", "message": None}}
    assert imp.branch({"mapping": loop, "current_node": "x"}) == [loop["x"]]
    assert imp.convert([{"mapping": {}, "current_node": None}]) == (
        [],
        {"empty_or_not_text": 0, "other_role": 0, "too_long": 0},
    )
