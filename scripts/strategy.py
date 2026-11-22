#!/usr/bin/env python3
import argparse
import json
import sys
import zipfile
from pathlib import Path
from xml.etree.ElementTree import ParseError

from sources import TRUST_LEVELS, add_source, source_index, source_lines
from storage import project_lock, project_path, read_jsonl
from workflow import (
    CLAIMS, GATES, STAGES, add_claims, add_usage, approve, open_project,
    report, start, status, submit, verify,
)


def cli():
    parser = argparse.ArgumentParser(description="Состояние и источники Стратега Фабрики продуктов")
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name, description):
        result = commands.add_parser(name, help=description)
        result.add_argument("project", help="Короткое имя проекта латиницей")
        return result

    new = command("start", "Создать проект")
    new.add_argument("--request", required=True)
    new.add_argument("--demo", action="store_true", help="Разрешить явно помеченные демо-решения")
    command("status", "Узнать следующий этап и ожидающее подтверждение")

    draft = command("submit", "Сохранить Markdown текущего этапа")
    draft.add_argument("stage", choices=STAGES)
    draft.add_argument("--file", required=True, type=Path)

    decision = command("approve", "Записать полученное решение человека")
    decision.add_argument("stage", choices=sorted(GATES))
    decision.add_argument("--version", required=True, type=int)
    decision.add_argument("--note", required=True)
    decision.add_argument("--actor", choices=("human", "demo"), default="human")

    source = command("source-add", "Снять текстовый слепок разрешённого источника")
    origin = source.add_mutually_exclusive_group(required=True)
    origin.add_argument("--url")
    origin.add_argument("--file", type=Path)
    source.add_argument("--title", required=True)
    source.add_argument("--trust", choices=TRUST_LEVELS)
    source.add_argument("--origin", help="Публичная ссылка оригинала для локальной выдержки")
    source.add_argument("--allow-host", action="append", default=[])
    source.add_argument("--refresh", action="store_true")
    command("sources", "Показать доступные источники")

    read = command("source-show", "Показать диапазон строк источника")
    read.add_argument("source_id")
    read.add_argument("--start", type=int, default=1)
    read.add_argument("--end", type=int)

    claims = command("claims-add", "Записать JSON-массив проверяемых утверждений")
    claims.add_argument("--file", type=Path, required=True)
    command("claims", "Показать журнал утверждений")

    usage = command("usage-add", "Добавить измерение времени или расходов из JSON")
    usage.add_argument("--file", type=Path, required=True)
    command("report", "Показать известные расходы и пробелы")
    command("verify", "Проверить артефакты, источники и ссылки на цитаты")
    return parser


def execute(project, args):
    if args.command == "start":
        return start(project, args.request, args.demo)
    state = open_project(project)
    match args.command:
        case "status":
            return status(project, state)
        case "submit":
            return submit(project, state, args.stage, args.file)
        case "approve":
            return approve(project, state, args.stage, args.version, args.note, args.actor)
        case "source-add":
            if args.file and not args.trust:
                raise ValueError("Для локального файла явно укажите --trust public, own или synthetic.")
            if args.url and (args.trust not in {None, "public"} or args.origin):
                raise ValueError("Скачиваемый URL должен быть публичным источником.")
            return add_source(project, args)
        case "sources":
            return list(source_index(project).values())
        case "source-show":
            entry = source_index(project).get(args.source_id)
            if not entry:
                raise ValueError("Источник не найден.")
            lines = source_lines(project, entry)
            end = args.end if args.end is not None else min(len(lines), args.start + 99)
            if not (1 <= args.start <= end <= len(lines)) or end - args.start >= 300:
                raise ValueError("Укажите существующий диапазон длиной не более 300 строк.")
            return {
                "source": entry, "total_lines": len(lines),
                "lines": {str(n): lines[n - 1] for n in range(args.start, end + 1)},
            }
        case "claims-add":
            return add_claims(project, args.file)
        case "claims":
            return read_jsonl(project / CLAIMS)
        case "usage-add":
            return add_usage(project, args.file)
        case "report":
            return report(project, state)
        case "verify":
            return verify(project, state)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    args = cli().parse_args()
    try:
        project = project_path(args.project)
        if args.command != "start":
            open_project(project)
        with project_lock(project):
            result = execute(project, args)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, RuntimeError, zipfile.BadZipFile, ParseError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
