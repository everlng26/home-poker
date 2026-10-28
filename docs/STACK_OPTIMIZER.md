# Starting Stack Optimizer

## Семантика турнира

Home Poker хранит существующее поле `Tournament.max_reentries_per_player`. Это лимит повторных входов для одного уникального игрока, не глобальный лимит турнира. Для planned players `P` и лимита `R`:

- maximum re-entry: `P × R`;
- maximum entries: `P × (1 + R)`.

Например, 8 игроков и 2 re-entry на игрока означают 16 потенциальных re-entry и 24 entry stacks всего. Optimizer не создаёт второй re-entry setting и никогда не меняет правило автоматически.

Coverage относится к `planned_players` на момент solve. Уникальный игрок, добавленный позднее во время late registration сверх planned count, не включён в сохранённую физическую гарантию.

## Combined Inventory

Пользователь выбирает один или несколько независимых `ChipSet`. Для одинакового номинала сервер суммирует quantities только во временном Combined Inventory. Повторный ID дедуплицируется. Optional exclusions удаляют номинал только из текущего request. Цветовые конфликты не анализируются.

Исходный `ChipSet`, denominations и quantities не меняются ни при solve, ни при применении результата.

## Hard constraints

Для initial distribution `x[d]`:

- `sum(d × x[d]) = starting_stack` точно;
- `players × x[d] <= combined_quantity[d]`;
- counts целые и неотрицательные.

Для одного re-entry pack `y[d]` и coverage `K`:

- `sum(d × y[d]) = starting_stack` точно;
- `players × x[d] + K × y[d] <= combined_quantity[d]`;
- `0 <= K <= players × max_reentries_per_player`.

Re-entry pack может отличаться от initial distribution. Резерв является общим и заранее не назначается конкретным игрокам.

## Solver

Перед поиском выполняются быстрые проверки total value и GCD. GCD используется только как necessary pre-check; bounded quantities проверяются exact search.

Основной поиск — детерминированный bounded DFS. Он сортирует denominations, ограничивает per-player counts физическим inventory и отсекает ветви по maximum suffix value, suffix GCD и достижимому chip count. Для каждого initial candidate отдельный поиск идёт от наибольшего разрешённого `K` вниз и подбирает exact re-entry pack. Unrestricted перебора `0..quantity` по всем номиналам нет; сторонний solver не используется.

Hard feasibility и soft scoring разделены. Математически корректный initial stack не становится impossible из-за неудобного score.

## Scoring и modes

Именованные настройки задают ориентиры:

- Comfortable: около 30–42 chips/player, target 35;
- Balanced: около 22–32, target 27;
- Compact: около 14–24, target 19.

Comfortable, Balanced и Compact — категории характера distribution, а не порядок качества. Для выбора лучшего представителя каждой категории используется `mode_score`: smooth distance до target/range, blind playability, coverage, re-entry quality, variety и depletion. Небольшой выход из preferred chip-count range не перекрывает сильное преимущество по играбельности.

Recommended выбирается независимо по `overall_score` среди всех уникальных evaluated candidates. Он учитывает coverage, blind playability, re-entry pack, разумное число chips/player и inventory efficiency. Coverage сохраняет большой вес: заметно более полное покрытие выигрывает у косметически более красивого стека, если оба остаются playable. При одинаковой coverage решающими становятся удобство обязательных ставок и качество reserve. Deterministic tie-breaker сравнивает coverage, blind score, re-entry score, chip count и stable distribution key.

Blind-aware score отдельно оценивает SB, BB и ante. Точное совпадение denomination получает наибольшую практическую ценность: отсутствие direct SB chip штрафуется сильно, 1–2 chips считаются недостаточными, 4 — приемлемыми, 6–8 — хорошим запасом с diminishing returns. Дополнительно bounded coin-change вычисляет минимальное число chips для exact payment: `25 × 1` лучше, чем `10 + 10 + 5`. Именованные profiles и weights находятся рядом с solver constants.

Re-entry pack использует противоположный приоритет: после exact value и maximum coverage предпочитаются крупные denominations, compactness и сохранение direct SB/BB/ante chips для стартовых стеков. Расход ранних denominations получает отдельный penalty; одинаковые initial distributions дедуплицируются.

## Full и Partial Coverage

`FULL COVERAGE` означает, что initial stacks и все `players × limit` разрешённых re-entry физически обеспечены.

`PARTIAL COVERAGE` означает, что initial seating обеспечена полностью, но общий физический резерв содержит только `K` дополнительных entry stacks. Это успешный solve. Tournament limit остаётся per-player значением `R`, а не становится равным `K`.

Дополнительно выводятся:

- uniform guarantee: `floor(K / players)` re-entry каждому в worst case;
- additional common reserve: `K mod players` stacks.

Если pack в основном крупный относительно starting stack/first blinds, показывается informational warning о возможном размене за столом.

## Diagnostics

Настоящий initial failure различает:

- недостаточную total value;
- exact stack, не кратный GCD;
- bounded quantity/denomination insufficiency;
- пустой или несуществующий selected inventory;
- некорректные players, stack, per-player limit или first blinds.

Недостаточная стоимость для полного worst-case вычисляется отдельно и не останавливает initial solve.

## Tournament Chip Plan snapshot

Мастер создания использует количество введённых уникальных players, существующий `starting_stack`, существующий `max_reentries_per_player` и первый игровой уровень. При submit сервер вызывает `evaluate_selection()`: заново проверяет exact value и bounded quantities выбранной initial distribution и тем же evaluator пересчитывает re-entry pack/coverage с актуальным первым уровнем. Ручное изменение blind score не заставляет выбранный plan снова попадать в top-3 и не заменяет его. Только после этой проверки одной транзакцией создаются tournament и snapshot.

`tournament_chip_plans` сохраняет selected ChipSet snapshots, combined inventory, planned players, stack, per-player limit, calculated maximum, physical coverage, initial/re-entry distributions, reserved quantities и remaining inventory. Таблица не имеет FK на `chip_sets`: edit/delete исходного набора не меняет исторический план. Единственная связь — cascade с Tournament. Никакого глобального складского reserve нет.

## Интеграция с Auto Tournament Builder

Auto Builder не заменяет solver. Он создает ограниченный список candidate stack values, а hard feasibility, physical distributions, re-entry pack, coverage и chip-quality score для каждого значения по-прежнему вычисляет этот service. Для promising first blinds Builder повторяет blind-aware solve и сохраняет именно returned initial distribution.

## Ограничения

- Сам Stack Optimizer по-прежнему требует starting stack; автоматический выбор реализован только верхнеуровневым Auto Tournament Builder.
- Цветовые конфликты наборов не анализируются.
- Позднее увеличение unique players не пересчитывает snapshot автоматически.
- Color-up и presets не входят в этап. Реализованный следующим этапом Structure Generator может читать номиналы применённого initial/re-entry plan, но не изменяет snapshot или inventory.

Следующий этап: **Color-up Assistant**.
