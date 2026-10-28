# Auto Tournament Builder

## Назначение

`AutoTournamentBuilderService` — stateless business boundary над уже существующими подсистемами. Он не содержит третьего stack solver или blind ladder и ничего не записывает в БД:

`Chip Inventory → Combined Inventory → Auto Tournament Builder → Stack Optimizer → Tournament Structure Generator → Editable Tournament Draft → Tournament Snapshot`.

Пользователь выбирает только:

- один или несколько физических `ChipSet`;
- planned players;
- `max_reentries_per_player`;
- целевую продолжительность в минутах;
- `none` или существующий BB Ante.

Starting stack, состав стека, re-entry pack, первый SB/BB, starting depth, длительность уровней, cadence/duration перерывов, BB Ante start и blind structure являются output Builder. Starting stack, blinds и level duration отсутствуют во входном контракте `build()` и HTTP request.

## Staged search

Поиск детерминирован и ограничен именованными constants:

1. `StackOptimizerService.combine_inventory()` агрегирует одинаковые номиналы выбранных наборов. Исходные rows и quantities не меняются.
2. Builder строит не более `STACK_CANDIDATE_LIMIT = 10` poker-friendly stack values. Значения выводятся из rational mantissas разных порядков и denomination × familiar chip-count anchors, затем выбираются около full-coverage, half-inventory и deeper capacity anchors. Каждое целое значение не перебирается.
3. Cheap total-value/GCD checks остаются внутри существующего Stack Optimizer; exact bounded feasibility и distribution строит только `StackOptimizerService.solve()`.
4. Не более пяти promising stack results переходят дальше. Coverage и уже рассчитанный `overall_score` Stack Optimizer определяют порядок pruning.
5. `TournamentStructureGeneratorService.starting_blind_candidates()` использует его существующий nice-value ladder и exact denomination payment model. Для каждого stack рассматривается не более двух first-blind pairs около soft depths 80/100/125/150 BB.
6. Stack Optimizer повторно запускается blind-aware, поэтому final initial distribution и re-entry pack учитывают первый SB/BB. Candidate отбрасывается, если его реальный per-player stack не может оплатить первый уровень точно.
7. Для всей структуры Structure Generator получает только union номиналов final initial distribution и re-entry pack. Неиспользованный номинал Combined Inventory не считается находящимся в игре и не может сделать искусственно точными значения вроде `37 / 75` только за счёт оставшейся в кейсе фишки `1`.
8. Builder рассматривает human-friendly level duration sets: 10/12/15 минут для коротких целей, 12/15/20 для обычных, 15/20/25 или 20/25/30 для длинных. Перерывы имеют только nice duration 10 или 15 минут и cadence около 60–90 минут; для очень короткой цели они отключаются.
9. Каждый surviving parameter set передаётся существующему `TournamentStructureGeneratorService.generate()`. Его blind ladder, BB Ante auto-start, duration model, finish window и четыре extension levels не дублируются.
10. Не более 30 целых tournament plans оцениваются и сортируются stable tie-breaker. Randomness отсутствует.

В типичном локальном тестовом inventory расчет занимает около 3–4 секунд на поддерживаемом Mac. Время зависит от denominations и exact-search branching; pool limits не дают росту превратиться в полный cross product.

## Re-entry semantics и duration forecast

Правило турнира не менялось:

`maximum_reentries = players × max_reentries_per_player`.

Для 8 игроков и лимита 2 theoretical maximum равен 16, а maximum entries — 24. Coverage Stack Optimizer всегда сравнивается с 16, не с 2. Full Coverage получает сильное преимущество, но Partial Coverage остается успешным вариантом и явно показывается.

Duration model не использует worst-case автоматически. Builder рассчитывает conservative planner-only forecast как 35–50% от planned players в зависимости от разрешенного per-player limit, округляет вверх и ограничивает tournament rule. Для конкретного chip plan forecast дополнительно не превышает физически покрытый reserve. Response объясняет использованное значение. Это не меняет `max_reentries_per_player` и не сохраняется как правило Tournament.

## Overall Tournament Score

Lower score wins. Все weights именованы рядом с service constants:

- `stack_quality`: существующий higher-is-better `StackOptimizer overall_score` с обратным знаком;
- `structure_quality`: существующий lower-is-better `Structure Generator score`;
- `coverage_shortfall`: явный penalty неполного reserve;
- `starting_depth`: logarithmic distance от 100 BB, при soft candidate depths;
- `level_duration`: distance от preferred 12/15/20 минут для длины турнира;
- `duration_window`: distance середины heuristic finish window от target;
- `first_blind_awkwardness`: существующий bounded blind-playability result стека;
- `inventory_usage`: доля физических chips в initial + reserve snapshot;
- `break_schedule`: distance от разумного количества breaks.

Recommended — минимальный stable score. До двух alternatives показываются только при meaningful difference: stack отличается минимум на 20%, depth минимум на 25 BB или level duration минимум на 5 минут. Поэтому UI не обязан искусственно показывать три похожих результата.

## Apply, ручные изменения и diagnostics

`Использовать этот вариант` заполняет существующую Tournament Creation form и вызывает тот же `renderLevels()` редактора. Generated rows сразу становятся обычным draft: SB, BB, ante, duration, add/delete, drag/drop, ↑/↓ и breaks работают прежними controls. Builder не имеет live dependency на editor и не пересчитывает stack plan после изменения blind structure.

После ручной правки клиент отправляет текущие rows в `TournamentStructureGeneratorService.analyze_draft()`. Этот read-only API возвращает только:

- новое heuristic finish window и total duration;
- starting depth / terminal-pressure context;
- exact-payment errors;
- practical-payment (сумма требует больше трех физических фишек) и aggressive-growth warnings.

Response намеренно не содержит `levels`, поэтому анализ не может подменить пользовательские rows. Exact impossible payment отображается как error; composed/awkward payment — warning. Manual values никогда не исправляются автоматически.

Автоматический SB не вычисляется округлением `BB / 2`. Generator выбирает denomination-aware poker-friendly пару, предпочитая точные отношения `1/2`, `2/5` и `1/3`. Поэтому для BB 75 возможны логичные `30 / 75` или `25 / 75` в зависимости от реально используемых номиналов, но не `37 / 75`.

Повторный Auto Build после ручных правок требует подтверждения собственным modal. Отмена оставляет draft без изменений. Новый Stack Optimizer plan также не меняет структуру: UI предупреждает о совместимости и только по отдельной команде открывает существующий Structure Generator.

## Snapshot semantics

Auto Builder metadata в Tournament не требуется. При submit существующий `TournamentSetupService` вызывает Stack Optimizer `evaluate_selection()`: заново проверяет exact value/bounded quantities выбранного plan и пересчитывает reserve/coverage с фактическими players, per-player limit и первым уровнем, не re-rank-ит и не заменяет manual stack. Затем одной транзакцией сохраняются:

- immutable `TournamentChipPlan` snapshot;
- обычные `BlindLevel`/break rows как tournament structure snapshot.

Редактирование/удаление исходного ChipSet или изменение алгоритма Builder не меняет созданный Tournament. Physical quantities не резервируются и не уменьшаются.

## Ограничения

- Duration и finish window остаются heuristic: стиль игры, скорость раздач и фактические re-entry не моделируются.
- Color conflicts и color-up не анализируются.
- Игроки, добавленные позже сверх planned count, не входят в исходную physical guarantee.
- Builder выбирает tournament-wide plan, но buy-in, payouts, bounty, names и late-registration cutoff остаются обычными настройками создания.

Следующий этап: **Color-up Assistant**.
