# Стратег Фабрики продуктов

В репозитории находятся скрипты для ведения продуктовых кейсов, методика работы и завершённый учебный кейс `family-connectivity-demo`.

## Семейные группы и собственные номера

Выбран вариант A — подготовка ограниченного пилота предупреждений о низком остатке интернета для организаторов семейных групп. План действий версии 1 подтверждён, статус кейса — `done`. Решение о запуске принимается по итогам проверки к 31 марта, о расширении — после оценки эффекта и подтверждения соблюдения защитных условий.

| Материал | Содержание |
|---|---|
| [Исходный бриф](<projects/family-connectivity-demo/inputs/Пример брифа.pdf>) | Учебное задание и исходные показатели, 11 страниц |
| [Стратегия из пяти частей](projects/family-connectivity-demo/artifacts/strategy-v1.md) | Продукт, коммуникация, проверка пилота, экономика, квартальный план и ресурсы |
| [Исследование, расчёты и допущения](projects/family-connectivity-demo/artifacts/research-v1.md) | Сравнение аудиторий, размер выборки, чувствительность прогноза и условия смены приоритета |
| [Варианты для выбора](projects/family-connectivity-demo/artifacts/options-v1.md) | Сравнение вариантов A–E и обоснование выбора |
| [План действий v1](projects/family-connectivity-demo/artifacts/handoff-v1.md) · [Подтверждение](projects/family-connectivity-demo/state.json) | Ответственные, сроки, условия запуска и запись решения пользователя в `completed.handoff.approval` |
| [Отчёт о расходах](projects/family-connectivity-demo/artifacts/cost-report.md) | Учтённое время по этапам и сведения о фактических расходах |
| [Постановка задачи](projects/family-connectivity-demo/artifacts/brief-v1.md) · [План исследования](projects/family-connectivity-demo/artifacts/plan-v1.md) | Утверждённые рамки и порядок проверки |
| [Источники](projects/family-connectivity-demo/sources/index.json) · [Журнал утверждений](projects/family-connectivity-demo/claims.jsonl) | Паспорт и текстовый снимок брифа, цитаты, допущения и выводы |

## Проверка после распаковки

Для просмотра материалов откройте этот файл в режиме просмотра Markdown. Для проверки состояния и целостности из корня распакованной папки запустите следующие команды с Python 3.10 или новее. Дополнительные библиотеки для этих команд не нужны.

```text
python scripts/strategy.py status family-connectivity-demo
python scripts/strategy.py verify family-connectivity-demo
python scripts/strategy.py report family-connectivity-demo
```

Команда `status` покажет `stage: done`. Команда `verify` сверит сохранённые версии, снимок источника и цитаты. Команда `report` выведет журнал учтённых расходов.

Порядок ведения новых кейсов описан в [инструкциях репозитория](AGENTS.md), [методике работы](knowledge/workflow.md) и [правилах работы с источниками](knowledge/evidence.md).
