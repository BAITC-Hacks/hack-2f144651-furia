# UI-LOGIC-01: подключение готовых API Logic к интерфейсу

- Статус: in_progress — реализация и проверки завершены; итоговое ревью
  документации и подтверждённая публикация выполняются интегратором.
- Цель: согласованные статусы риска в таблице, KPI, фильтрах и карточке;
  явная применимость детектора и результаты событий без изменения расчётов.
- Интегратор: Codex `/root`, сессия `01a0cdfc-d3c8-7c30-82fd-b27597a5c11e`.
- Frontend риска: `/root/risk_ui`; Frontend детектора и интеграция: `/root`.
- Reviewer: `/root/ui_review`, независимая проверка после фиксации итогового diff.
- Рабочая папка: `/home/ziyadin/Documents/ChatGPT/Hack`, общее дерево, `main`.
- База после `git status`, `rev-parse HEAD`, `fetch origin`:
  `f099198ea6c2d54ded05f020d8ae28be3316df31`, совпадает с origin/main.
  Fast-forward не требуется; чужая правка TASKS и локальные файлы сохранены.
- Зависимости: готовые `engine.classify_risk`, `demand.detector_status`,
  [передача Logic](../handoffs/engine.md), действующие Calculation/Bundle.
- Точные файлы Frontend `/root/risk_ui`: `src/ekt_ui/presentation.py`,
  `src/ekt_ui/layout.py`, `src/ekt_ui/results.py`, `src/ekt_ui/review.py`
  (только цвет нового статуса в таблице),
  `tests/frontend/test_risk_integration.py`.
- Точные файлы Frontend `/root`: `src/ekt_ui/details.py`,
  `tests/frontend/test_detector_integration.py`, `docs/DASHBOARD.md`,
  `docs/handoffs/frontend.md`. Handoff риска передаётся интегратору сообщением,
  итоговую запись Frontend добавляет `/root`, сохраняя предыдущие записи.
- Точные общие файлы интегратора: `docs/tasks/UI-LOGIC-01.md`,
  `docs/INTERFACES.md`; после передачи CI-02 — `docs/TASKS.md`, `docs/STATUS.md`.
- Reviewer: только `docs/handoffs/review.md`, после передачи CI-02.
- Координация: CI-02 (сессия `01a0cdf9-e355-7da0-aee9-8394488dd894`)
  подтвердил владение TASKS/STATUS/review.md и Git до завершения своего этапа.
  Эти файлы и Git не меняются UI-исполнителями; CI-02 уведомлён о независимой UI-работе.
  Запись-ссылка в TASKS и передача общих файлов согласуются сообщением между сессиями.
  CI-02 завершён; на согласованной паузе записей опубликованы только CI/docs.
  Получен HEAD `016c2cfbf34f84c916de594ab779f8c5bbd26666` = origin/main.
  Git, TASKS, STATUS и review.md явно переданы этому интегратору; работа возобновлена.
  Общие проверки ниже выполняются уже поверх этого HEAD.
- Контракт: только вызовы существующих helpers с config.as_of и
  config.remove_oneoffs; продажи одного supplier/SKU/scope. Формулы, количество,
  ручной ноль, row_id, утверждение и глобальный состав экспорта сохраняются.
- Приёмка: пять подписей риска, граница 6/7, риск при Q=0, Q>0 без риска;
  disabled / n<12 / evaluated, отсутствие результатов и applied=False;
  cutoff и изоляция трёх ключей; предупреждения движка.
- Проверки: результаты и команды ниже; пропуски не считаются успешной проверкой.
- Ограничения: оригиналы/точность модели, удалённый CI, деплой и официальная
  сдача не подтверждаются этой интеграцией. Сырые данные не публикуются.
- Итоговый commit/push: Git передан CI-02; после финального ревью и проверки
  удалённой базы. SHA и подтверждение публикации фиксируются итоговым сообщением
  и последующей записью результата, без самоссылочного SHA в собственном коммите.

## Фактический результат

Таблица, карточка, фильтры и KPI риска используют classify_risk с config.as_of.
Недоступный расчёт и неизвестный риск разделены; unknown имеет приоритет над
положительным заказом. KPI/фильтр дефицита учитывают critical/risk; предупреждения,
unknown и unavailable входят в перепроверку. Исходные Calculation.rows не меняются.

Детектор получает только выбранные supplier/SKU/scope, cutoff и remove_oneoffs.
Отдельно видны disabled, n из 12, evaluated с завершённым DemandResult и
применимость без доступного результата. Monthly-only даёт 0 событий. Найденные
события и applied-исключения разделены, предупреждения сохранены в «Источниках».

Среда: Linux, Python 3.12.14, отдельная `/tmp/ekt-ui-logic-01-venv`, 44 зависимости
из неизменённого requirements.lock. Команды ниже с Python этой среды, из корня repo.
Проверяемая версия: `016c2cfbf34f84c916de594ab779f8c5bbd26666` + назначенный UI-diff.

| Проверка | Факт |
|---|---|
| `python -m pytest -q tests/frontend/test_risk_integration.py tests/frontend/test_presentation.py -p no:cacheprovider` | 29 passed, 8.90s |
| `python -m pytest tests/frontend/test_detector_integration.py -q` | 9 passed, 10.56s |
| `python -m pytest tests/frontend -q -p no:cacheprovider` | 66 passed, 88.80s |
| `python -m pytest -q` | 301 passed, 20 skipped, 116.82s |
| `python scripts/smoke.py` | synthetic, 4 позиции / 2 поставщика, manual_zero=0, approved; CSV 6406 / XLSX 8532 байт |
| `uv pip check --python /tmp/ekt-ui-logic-01-venv/bin/python` | 44 пакета совместимы |
| Независимый Reviewer | 91 passed; M1–M5, edges/review/workflow, новые состояния и отдельные числовые сценарии; [отчёт](../handoffs/review.md) |
| Браузер Codex, localhost:18502 | Desktop 1440×1000: demo/расчёт/KPI/таблица/карточка, evaluated с 0 событий, disabled, короткая история 11/12; mobile 390×844: карточка, перенос сообщений, фильтр «Критично» 1 из 4, список 5 статусов; ширина документа и диалога 390px |

В браузере использовались demo и временный синтетический ZIP вне репозитория.
Числовые границы, unknown и events.applied=False дополнительно покрыты AppTest,
а не выдаются за браузерные сценарии. 26 новых поведенческих тестов также
проверяют сохранение row_id/ручного нуля/approved/глобального экспорта.

20 opt-in тестов пропущены без EKT_PARTNER_ARCHIVE_DIR; оригиналы этой задачей
не проверялись. Удалённый CI остаётся внешне ограничен billing lock и после CI-02
запускается вручную; локальные результаты не означают зелёный удалённый запуск.
Чистый старт браузерного сервера проверен; отдельная чистая копия приложения,
Windows и нагрузочная проверка в этом этапе не выполнялись. Деплой, официальная
сдача и отправка заказов не выполнялись.
