import math
import re
from datetime import datetime
from pathlib import Path

from sources import normalized, source_index, source_lines
from storage import atomic_write, digest, now, read_json, read_jsonl, read_text, write_json, write_jsonl


STAGES = ("brief", "plan", "research", "options", "strategy", "handoff")
GATES = {"brief", "plan", "options", "handoff"}
CLAIM_KINDS = {"fact", "hypothesis", "forecast", "inference", "decision", "synthetic"}
STATE = "state.json"
CLAIMS = "claims.jsonl"
USAGE = "usage.jsonl"


def open_project(project):
    if not (project / STATE).is_file():
        raise ValueError("Проект не создан. Используйте start.")
    state = read_json(project / STATE)
    if state.get("schema") != 1:
        raise ValueError("Эта версия скрипта не поддерживает формат состояния.")
    return state


def start(project, request, demo):
    if (project / STATE).exists():
        raise ValueError("Проект уже существует. Используйте status для продолжения.")
    request = request.strip()
    if not request:
        raise ValueError("Укажите исходный запрос.")
    timestamp = now()
    state = {
        "schema": 1, "project": project.name, "request": request, "demo": demo,
        "created_at": timestamp, "updated_at": timestamp, "stage": STAGES[0],
        "pending": None, "completed": {}, "events": [],
    }
    (project / "inputs").mkdir(exist_ok=True)
    write_json(project / STATE, state)
    return state


def status(project, state):
    return {
        **state,
        "sources": len(source_index(project)),
        "claims": len(read_jsonl(project / CLAIMS)),
        "usage_events": len(read_jsonl(project / USAGE)),
    }


def save_event(project, state, event):
    timestamp = now()
    state["updated_at"] = timestamp
    state["events"].append({"at": timestamp, **event})
    write_json(project / STATE, state)
    return state


def advance(state, artifact, approval=None):
    stage = state["stage"]
    state["completed"][stage] = {**artifact, "approval": approval}
    index = STAGES.index(stage) + 1
    state["stage"] = STAGES[index] if index < len(STAGES) else "done"
    state["pending"] = None


def submit(project, state, stage, path):
    if stage != state["stage"]:
        raise ValueError(f"Сейчас этап {state['stage']}, получен {stage}.")
    content = read_text(path).strip() + "\n"
    if not content.strip() or len(content) > 150_000:
        raise ValueError("Материал этапа должен содержать от 1 до 150 000 символов.")
    previous = state["pending"]
    if previous and previous["sha256"] == digest(content):
        return state
    version = previous["version"] + 1 if previous else 1
    artifact = {
        "file": f"artifacts/{stage}-v{version}.md",
        "version": version,
        "sha256": digest(content),
    }
    atomic_write(project / artifact["file"], content)
    if stage in GATES:
        state["pending"] = artifact
    else:
        advance(state, artifact)
    return save_event(project, state, {"action": "submit", "stage": stage, **artifact})


def approve(project, state, stage, version, note, actor):
    pending = state["pending"]
    if state["stage"] != stage or not pending or pending["version"] != version:
        raise ValueError("Нет ожидающего подтверждения с указанным этапом и версией.")
    if actor == "demo" and not state["demo"]:
        raise ValueError("Имитация решения разрешена только в демонстрационном проекте.")
    if not note.strip():
        raise ValueError("Запишите, что именно было подтверждено.")
    if digest(read_text(project / pending["file"])) != pending["sha256"]:
        raise ValueError("Материал изменился вне процесса. Заново подайте его на подтверждение.")
    approval = {"actor": actor, "note": note.strip(), "at": now()}
    advance(state, pending, approval)
    return save_event(
        project, state, {"action": "approve", "stage": stage, "version": version, **approval}
    )


def validate_claim(project, raw, prior, index, snapshots):
    key = raw.get("id")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,31}", key):
        raise ValueError("ID утверждения должен состоять из 2–32 заглавных букв, цифр, _ и -.")
    kind = raw.get("kind")
    if kind not in CLAIM_KINDS or not isinstance(raw.get("text"), str) or not raw["text"].strip():
        raise ValueError(f"{key}: укажите допустимый вид и непустой текст.")
    dependencies = raw.get("depends_on", [])
    if (
        not isinstance(dependencies, list)
        or any(not isinstance(dep, str) or dep not in prior or dep == key for dep in dependencies)
        or len(dependencies) != len(set(dependencies))
    ):
        raise ValueError(f"{key}: основания должны быть ранее записанными ID без повторов.")
    if kind == "inference" and not dependencies:
        raise ValueError(f"{key}: у вывода должны быть указаны основания.")
    evidence = raw.get("evidence", [])
    if not isinstance(evidence, list) or (kind == "fact" and not evidence):
        raise ValueError(f"{key}: для факта нужна проверяемая цитата.")
    for item in evidence:
        entry = index.get(item.get("source"))
        first, last = item.get("line_start"), item.get("line_end")
        quote = item.get("quote")
        if not entry or type(first) is not int or type(last) is not int or not isinstance(quote, str):
            raise ValueError(f"{key}: укажите ID источника, номера строк и цитату.")
        if kind == "fact" and entry["trust"] == "synthetic":
            raise ValueError(f"{key}: синтетический источник не подтверждает факт.")
        source = entry["id"]
        if source not in snapshots:
            snapshots[source] = source_lines(project, entry)
        lines = snapshots[source]
        if not (1 <= first <= last <= len(lines)) or not normalized(quote):
            raise ValueError(f"{key}: неверный диапазон строк или пустая цитата.")
        if normalized(quote) not in normalized(" ".join(lines[first - 1:last])):
            raise ValueError(f"{key}: цитата не найдена в указанных строках {source}.")
    return {"id": key, "kind": kind, "text": raw["text"].strip(), "depends_on": dependencies, "evidence": evidence}


def add_claims(project, path):
    batch = read_json(path)
    if not isinstance(batch, list) or not batch:
        raise ValueError("Ожидается непустой JSON-массив утверждений.")
    claims = read_jsonl(project / CLAIMS)
    prior = {claim["id"]: claim for claim in claims}
    index, snapshots = source_index(project), {}
    added = 0
    for candidate in batch:
        claim = validate_claim(project, candidate, prior, index, snapshots)
        key = claim["id"]
        if key in prior:
            if prior[key] != claim:
                raise ValueError(f"{key}: этот ID уже занят другим утверждением.")
            continue
        prior[key] = claim
        claims.append(claim)
        added += 1
    if added:
        write_jsonl(project / CLAIMS, claims)
    return {"added": added, "total": len(claims)}


def add_usage(project, path):
    event = read_json(path)
    key = event.get("id")
    if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", key):
        raise ValueError("Запись расхода требует уникальный ID.")
    if event.get("stage") not in (*STAGES, "run") or not str(event.get("note", "")).strip():
        raise ValueError("Укажите этап (или run) и пояснение к записи.")
    for field in ("seconds", "input_tokens", "output_tokens", "searches", "retries", "human_actions", "usd"):
        value = event.get(field)
        if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or value < 0):
            raise ValueError(f"{field}: ожидается неотрицательное число или null.")
        if field in {"input_tokens", "output_tokens", "searches", "retries", "human_actions"} and value is not None and type(value) is not int:
            raise ValueError(f"{field}: ожидается целое число.")
    events = read_jsonl(project / USAGE)
    for recorded in events:
        if recorded["id"] == key:
            if {name: value for name, value in recorded.items() if name != "recorded_at"} != event:
                raise ValueError(f"Запись {key} уже существует с другими данными.")
            return recorded
    if "recorded_at" in event:
        raise ValueError("Поле recorded_at заполняется автоматически.")
    event["recorded_at"] = now()
    write_jsonl(project / USAGE, [*events, event])
    return event


def report(project, state):
    events = read_jsonl(project / USAGE)
    totals = {}
    for field in ("seconds", "input_tokens", "output_tokens", "searches", "retries", "human_actions", "usd"):
        known = [row[field] for row in events if row.get(field) is not None]
        totals[field] = {"known_total": sum(known) if known else None, "unknown_entries": len(events) - len(known)}
    span = datetime.fromisoformat(state["updated_at"]) - datetime.fromisoformat(state["created_at"])
    return {
        "project": project.name, "workflow_elapsed_seconds": int(span.total_seconds()),
        "totals": totals, "entries": events,
        "approval_events": [event for event in state["events"] if event["action"] == "approve"],
    }


def verify(project, state):
    completed = list(state["completed"])
    if completed != list(STAGES[:len(completed)]):
        raise ValueError("Нарушен порядок завершённых этапов.")
    expected_stage = STAGES[len(completed)] if len(completed) < len(STAGES) else "done"
    if state["stage"] != expected_stage:
        raise ValueError("Текущий этап не соответствует завершённым этапам.")
    for stage in completed:
        if stage in GATES and not state["completed"][stage]["approval"]:
            raise ValueError(f"Отсутствует подтверждение этапа {stage}.")
    artifacts = list(state["completed"].values())
    if state["pending"]:
        artifacts.append(state["pending"])
    for artifact in artifacts:
        if digest(read_text(project / artifact["file"])) != artifact["sha256"]:
            raise ValueError(f"Файл этапа изменился: {artifact['file']}.")
    index = source_index(project)
    snapshots = {key: source_lines(project, entry) for key, entry in index.items()}
    claims = {}
    for raw in read_jsonl(project / CLAIMS):
        claim = validate_claim(project, raw, claims, index, snapshots)
        if claim["id"] in claims:
            raise ValueError(f"Повтор ID: {claim['id']}.")
        claims[claim["id"]] = claim
    return {
        "verified": True, "current_stage": state["stage"], "artifacts": len(artifacts),
        "sources": len(snapshots), "source_kinds": sorted({entry["kind"] for entry in index.values()}),
        "claims": len(claims), "facts": sum(claim["kind"] == "fact" for claim in claims.values()),
    }
