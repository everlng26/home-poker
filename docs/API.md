# HTTP API

Административные команды турнира требуют входа по PIN и CSRF-заголовок. Локальный каталог фишек доступен с главной страницы приложения. Ошибки возвращаются как JSON с понятным сообщением.

## Chip Inventory

- GET /api/v1/chip-sets — список наборов.
- GET /api/v1/chip-sets/{id} — один набор со всеми номиналами.
- POST /api/v1/chip-sets — создать набор.
- PUT /api/v1/chip-sets/{id} — изменить название, default и полный список номиналов.
- DELETE /api/v1/chip-sets/{id} — удалить набор и его дочерние строки.
- POST /api/v1/chip-sets/{id}/default — назначить единственный default-набор.
- POST /api/v1/stack-optimizer — рассчитать exact initial stacks, re-entry packs и physical coverage для одного или нескольких наборов.

Запись принимает `name`, optional `is_default` и `denominations: [{value, quantity}]`. Ответ содержит `id`, `name`, `is_default`, серверные `total_chips`/`total_value`, отсортированные `denominations`, `created_at` и `updated_at`. Номинал должен быть целым и больше нуля, количество — целым и не меньше нуля; повтор одного номинала внутри набора возвращает `duplicate_denomination`.

Optimizer принимает `chip_set_ids`, `players`, существующий per-player `max_reentries_per_player`, `starting_stack`, optional `excluded_denominations` и optional первый SB/BB/ante. Сервер выводит `max_total_reentries = players × max_reentries_per_player`, combined inventory, diagnostics и до трёх дедуплицированных candidates. `feasible=false` относится только к невозможности initial stacks. Candidate с `coverage_status=partial` остаётся успешным результатом и сообщает фактический общий резерв.

## Structure Generator

- POST /api/v1/structure-generator — построить детерминированный BlindLevel-compatible preview без сохранения состояния.

Request принимает `players`, `starting_stack`, planner-only `expected_reentries`, optional существующий `max_reentries_per_player`, `first_small_blind`, `first_big_blind`, `level_duration_minutes`, `target_duration_minutes`, `ante_mode` (`none`/`big_blind`), `ante_start_mode` (`auto`/`manual`), optional `ante_start_level`, `break_every_levels`, `break_duration_minutes` и optional `chip_denominations`.

Response содержит `levels`, `summary`, non-blocking `diagnostics`, deterministic `score` и public heuristic metadata. `levels` использует существующие поля `kind`, `small_blind`, `big_blind`, `ante`, `duration_seconds` и optional break `title`. `summary.finish_window` — ориентировочное wall-clock окно, не гарантия. Endpoint ничего не записывает в БД; после Apply клиент передаёт уровни обычному Tournament create/levels workflow.

## Auto Tournament Builder

- POST /api/v1/auto-tournament-builder — построить до трех целых tournament plans из физических наборов.
- POST /api/v1/auto-tournament-builder/diagnostics — read-only анализ вручную измененного draft без replacement rows.

Build request содержит только `chip_set_ids`, `players`, существующий `max_reentries_per_player`, `target_duration_minutes` и `ante_mode` (`none`/`big_blind`). Starting stack, SB/BB и level duration не принимаются. Response содержит theoretical per-player re-entry totals, conservative `expected_reentries` с объяснением, Combined Inventory snapshot, search diagnostics и candidates. Каждый candidate включает initial/re-entry distributions, `structure_denominations` из реально используемых номиналов, coverage, first blinds/depth, levels/breaks/BBA start, finish window, extension levels, score components и готовый `chip_plan` payload для обычного Tournament create.

Diagnostics request принимает текущие `levels`, planned players/stack, planner-only expected re-entry, target duration и physical denominations. Response содержит `summary`, warnings/errors и heuristic metadata, но намеренно не содержит `levels`; endpoint не записывает БД и не меняет draft.

## Турниры

- GET /health — состояние приложения.
- GET, POST /api/v1/tournaments — список и создание турниров.
- POST /api/v1/tournaments/{id}/delete — удалить турнир после подтверждения PIN.
- GET /api/v1/tournaments/{id}/state — полный снимок состояния.
- POST /api/v1/tournaments/{id}/login — вход по PIN.
- POST /api/v1/tournaments/{id}/players — добавить игрока.
- POST /api/v1/tournament-players/{id}/eliminate — отметить вылет; для Fixed Bounty обязателен `killer_tournament_player_id` активного другого участника.
- POST /api/v1/tournament-players/{id}/reenter — сделать re-entry.
- POST /api/v1/tournament-players/{id}/out — зафиксировать окончательный аут без re-entry.
- POST /api/v1/tournaments/{id}/timer — команда таймера (`resume` запускает новый турнир; `start` оставлен для совместимости со старыми клиентами).
- POST /api/v1/tournaments/{id}/finish — завершить турнир вручную по PIN администратора и заблокировать дальнейшие изменения таймера, структуры и игроков.
- POST /api/v1/tournaments/{id}/undo — отменить последнее безопасное действие.
- GET /api/v1/tournaments/{id}/events — последние действия.
- POST /api/v1/tournaments/{id}/levels — сохранить структуру до завершения турнира; требуется `late_registration_end_level_number` — номер существующего игрового уровня, после которого заканчивается поздняя регистрация. Старое поле `late_registration_end_level_index` поддерживается для совместимости, но также не может быть пустым и должно указывать на игровой уровень.
- POST /api/v1/tournaments/{id}/payouts — сохранить проценты выплат до их финализации; сумма должна быть ровно 100%.
- POST /api/v1/tournaments/{id}/payouts/finalize — явно закрыть регистрацию и финализировать выплаты, в том числе когда дедлайн уровня не задан.
- GET /api/v1/tournaments/{id}/chip-plan — получить сохранённый historical snapshot плана фишек.

При создании турнира можно передать `levels`, `players`, `max_reentries_per_player`, `is_freeroll`, `ante_enabled`, `payout_percentages`, `bounty_mode` (`none`/`fixed`), `bounty_amount` и optional `chip_plan`; `late_registration_end_level_number` является обязательным. `chip_plan` содержит выбранные IDs, optional exclusions и initial distribution. Сервер заново проверяет exact value/bounded quantities этой distribution и тем же Stack Optimizer evaluator пересчитывает reserve/coverage с фактическими значениями формы. Изменение soft blind score не заменяет выбранный stack plan; изменившийся physical inventory по-прежнему отклоняет устаревший вариант. Для Fixed Bounty сумма должна быть больше нуля и меньше общего бай-ина; freeroll и bounty несовместимы. Сервер сохраняет первоначальную настройку одной операцией. При `is_freeroll=true` бай-ин становится нулевым, payout structure игнорируется, а публичный экран скрывает призовой фонд.

Если игрок уже исчерпал лимит re-entry или был отмечен как окончательный аут, первый запрос re-entry возвращает предупреждение `reentry_warning` без изменения данных. После обычного подтверждения интерфейс повторяет запрос с `allow_warnings=true`, и игрок возвращается в игру. После окончания поздней регистрации добавление игрока и re-entry аналогично возвращают `late_registration_warning` до изменения данных. Исключение: если сразу после контрольного уровня идёт перерыв, поздняя регистрация остаётся доступной без предупреждения на весь этот перерыв.

В редакторе игровым уровням присваиваются видимые порядковые номера; их можно менять перетаскиванием или кнопками вверх/вниз, а номера пересчитываются автоматически. Перерыв отображается отдельной строкой без номера и названия, а следующий игровой уровень продолжает нумерацию. Этот номер используется для выбора уровня окончания поздней регистрации. На странице входа поле PIN автоматически получает фокус.

Если структура была изменена, но ещё не сохранена, кнопка возврата на главную страницу временно заблокирована, чтобы случайно не потерять изменения.

Снимок состояния содержит `late_registration_ended`, фазу `late_registration_phase`, `payouts`, `bounty_mode`, `bounty_amount`, `metrics.bounty_pool`, `metrics.total_collected`, event-derived `ko_count`/`bounty_winnings`, `ko_leader`, публичные события и итоговый список `standings`. При равном максимальном K.O. `ko_leader` содержит одного игрока, который первым достиг текущего максимума. Фаза `next_level` начинается за один игровой уровень до контрольного, `closing` действует только на самом контрольном уровне, `grace_break` — на следующем за ним перерыве, а `closed` — после этого. `public_stage` сообщает о трёх оставшихся игроках, хедз-апе или победителе; в публичное событие попадают только актуальные входы в игру, сделанные после выхода турнира из статуса подготовки, вылеты и re-entry. Для стартового состава событие регистрации сохраняется в журнале с `public_feed=false`, но не передаётся в бегущую строку.

Когда в ауте остаются все игроки, кроме одного, сервер автоматически определяет победителя и показывает итоги, но оставляет `is_manually_finished=false`: администратор ещё может исправить ошибочно внесённое действие. Команды восстановления таймера (`previous`, `jump`, `reset`, `add_60`) возвращают такой турнир в состояние паузы, убирают временно присвоенное первое место и снова показывают обычное табло. Кнопка «Завершить турнир» остаётся доступной на экране итогов; после подтверждения PIN endpoint ручного завершения устанавливает `is_manually_finished=true` и блокирует команды таймера, игроков, отмену действий и изменение структуры.

Удаление игрока из текущей игры можно отменить через «Отменить действие»: игрок возвращается в игру с прежним местом вылета и временем. Окончательный аут не отменяется. Отмена re-entry восстанавливает прежнее количество входов.
- GET /api/v1/network — подходящие LAN-адреса (служебный endpoint).
- POST /api/v1/network/preferred — сохранение адреса для совместимости со старыми клиентами.
- GET /api/v1/tournaments/{id}/qr/admin — локальный SVG QR-код админки.
