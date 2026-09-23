# Задание ENGINE

Ты агент расчёта EKT. Продолжи существующий движок. Прочитай AGENTS.md,
START_HERE.md, docs/STATUS.md, docs/AGENT_PLAN.md, docs/INTERFACES.md,
docs/kit/ENGINE_SPEC.md и docs/kit/ACCEPTANCE.md. Сверь SHA с ведущим.

Меняй только: src/ekt/demand.py, src/ekt/forecast.py, src/ekt/engine.py,
tests/test_demand.py, tests/test_forecast.py, tests/test_engine_regressions.py,
scripts/evaluate_forecast.py, docs/handoffs/engine.md. schema.py, conftest.py,
test_acceptance.py, test_edges.py, UI, импорт и зависимости не редактируй.

Выполни E1–E3 из AGENT_PLAN; после обязательного покрытия — E4, ограниченный backtest.
Начни с проверок:

```bash
python -m pytest -q tests/test_acceptance.py tests/test_edges.py
```

Используй общий Bundle, demo_bundle и небольшие fixtures в своих тестах; не жди
Excel-адаптеров. Приоритет: три сходных крупных заказа разных разовых клиентов
не равны регулярному крупному клиенту; на истории <12 групп отключение детектора
должно быть явно видно. Сохрани T11 для регулярного клиента и широкого сезонного пика.

Проверь stockout с пересечениями/частичными продажами, отсутствие доступных дней,
несходящиеся месячные итоги, cutoff, ETA, reserve/available, рост и MOQ/multiple.
Неизвестная потребность не равна нулю; нулевую потребность MOQ не превращает в заказ.
Для каждого дефекта — вход, независимое ожидание, факт до правки и регрессия.

Формы DemandResult, ForecastResult, Calculation и rows/details сохраняй. Изменение
контракта заранее согласуй с LEAD. В движке нет внешних API/Streamlit/чтения Excel.
Не добавляй необязательный ML/LLM, не заявляй качество на оригиналах без измерения.

Первая передача — E1/E2 с числами. Финальная — новые тесты, весь
`python -m pytest -q`, статус E1–E4 и ограничения в docs/handoffs/engine.md по TEMPLATE.
В общем дереве Git-состояние не меняй; в своей ветке допустим локальный commit своих
файлов. Push/деплой — только по отдельному указанию.
