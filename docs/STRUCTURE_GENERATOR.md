# Tournament Structure Generator

## Назначение и границы

`TournamentStructureGeneratorService` строит детерминированное предложение структуры по параметрам домашнего турнира. Результат содержит те же элементы `play` и `break`, которые уже принимает `BlindLevel`/`TournamentSetupService`; отдельной модели структуры и новых таблиц нет.

Standalone-страница показывает read-only preview. В мастере создания кнопка «Использовать эту структуру» передаёт уровни существующему редактору. После этого SB, BB, ante, длительность, порядок, перерывы и состав строк меняются обычными инструментами. При создании турнира сохраняется только итоговый snapshot уровней, без generator parameters и без live dependency на алгоритм.

Generator не меняет buy-in, payouts, bounty, late registration, starting stack, players или `max_reentries_per_player`. Если прежний номер окончания late registration отсутствует в применённой структуре, UI показывает предупреждение и требует ручного выбора существующего игрового уровня.

## Целевая продолжительность

Целевая продолжительность — ориентир, а не обещание. Одинаковая структура может завершиться раньше или позже из-за темпа игры, поэтому UI показывает:

- цель;
- расчётный target level;
- ориентировочное окно окончания;
- несколько уровней-буферов после окна.

Количество игровых уровней до target выбирается детерминированно по минимальной разнице:

`level count × level duration + breaks before target ≈ target duration`.

Перерыв после последнего учитываемого игрового уровня не входит во время target. Если cadence попадает точно после target level, этот перерыв не вставляется непосредственно в расчётную точку окончания; cadence буфера начинается заново. Ориентировочное окно равно target level ± 2 игровых уровня и переводится в wall-clock time с фактически вставленными перерывами.

Это heuristic window, не confidence interval и не статистическая вероятность.

## Planned chips и expected re-entry

Planner-only поле `expected_reentries` по умолчанию равно нулю. Оно не является правилом турнира, не заменяет per-player limit и не сохраняется в Tournament:

`planned_entries = players + expected_reentries`

`planned_total_chips = planned_entries × starting_stack`

Если известен `max_reentries_per_player`, сервис проверяет:

`expected_reentries <= players × max_reentries_per_player`.

При лимите ноль ожидаемые re-entry также обязаны быть нулевыми. Unlimited/unknown rule не заставляет generator придумывать прогноз.

## Terminal pressure heuristic

Именованный constant `TARGET_FINAL_TOTAL_CHIPS_IN_BB = 20` означает, что около target point весь planned chip volume должен составлять примерно двадцать больших блайндов:

`target_terminal_bb ≈ planned_total_chips / TARGET_FINAL_TOTAL_CHIPS_IN_BB`.

Это прозрачная оценка короткого late-game / heads-up pressure, а не условие фактического окончания турнира. Больше planned chips повышает terminal BB. Target duration определяет, за сколько уровней структура подходит к этой зоне.

Стартовая глубина выводится как `starting_stack / first_bb`. Глубина меньше 20 BB создаёт warning, но не запрещается; глубина больше 200 BB отмечается informational diagnostic.

## Nice values и scoring

Кандидаты BB берутся не из механического `previous × fixed percentage`, а из poker-friendly ladder с mantissa вида:

`1, 1.2, 1.5, 1.6, 2, 2.5, 3, 4, 5, 6, 7.5, 8 × 10ⁿ`.

Поэтому ladder содержит привычные значения `75/150`, `100/200`, `150/300`, `300/600`, `600/1 200`, `800/1 600`, `1 000/2 000` и продолжение в следующих разрядах. Первый введённый уровень сохраняется точно.

SB также выбирается из poker-friendly values, а не округлением `BB / 2`. Приоритет имеют точные отношения `1/2`, `2/5` и `1/3`, совместимые с физическими номиналами. Например, BB 75 получает SB 30 или 25, но никогда автоматически не превращается в `37 / 75` из-за наличия номинала 1.

Сервис строит небольшое ограниченное множество вариантов с разным terminal factor и curve exponent. Именованные scoring weights оценивают:

- близость BB target level к terminal pressure;
- preferred рост около 25–50%;
- tiny steps и abrupt jumps;
- изменение growth ratio между соседними уровнями;
- точную физическую оплату;
- starting depth;
- разницу рассчитанного target wall-clock time и цели.

Lower score wins; tie-breaker сравнивает стабильную последовательность BB. Randomness отсутствует. В обычной конфигурации строгий рост BB сохраняется, повторяющихся уровней нет.

Если для цели появляются скачки выше warning threshold, diagnostics рекомендует минимальную более длинную target duration. Если средний рост становится почти незаметным, предлагается увеличить duration одного уровня вместо дублирования блайндов.

## Physical denomination awareness

Без Chip Plan generator использует универсальную ladder. При интеграции с применённым Tournament Chip Plan мастер передаёт union номиналов, реально используемых initial distribution и re-entry pack.

Сервис проверяет exact unbounded representability SB и BB. Сначала применяется GCD-нормализация, затем shortest-path по остаткам; GCD не считается достаточным доказательством для неканонического набора. Кандидаты, которые нельзя оплатить точно, исключаются. Стартовые блайнды, которые нельзя оплатить выбранными номиналами, возвращают `starting_blinds_unrepresentable`.

Generator не меняет quantities, не резервирует inventory и не планирует color-up.

## Ante

Поддерживаются `none` и существующий BB Ante. На ante-enabled уровне `ante = BB`; нового ante mechanism нет.

В `auto` режиме BB Ante начинается не раньше третьего уровня и после того, как nominal starting stack становится не глубже `AUTO_ANTE_START_DEPTH_BB = 50` текущих BB. В manual режиме пользователь задаёт номер игрового уровня. До начала ante сохраняется ноль.

## Extension levels и automatic end

Окно заканчивается на target + 2 уровня. После верхней границы сервис всегда добавляет `EXTENSION_LEVELS_AFTER_WINDOW = 4` возрастающих игровых уровня. Они не входят в целевую продолжительность и нужны, чтобы затянувшаяся игра не упёрлась сразу в существующий automatic end after final structure item.

## Diagnostics и performance

Domain errors различают invalid players/stack/blinds/durations/breaks/ante, expected re-entry over limit, невозможные стартовые ставки и невозможность построить возрастающую ladder. Non-blocking diagnostics сообщают о shallow/deep start, агрессивном или слишком медленном росте.

Candidate space ограничен именованными factors/exponents и familiar ladder. Обычная генерация занимает миллисекунды и не использует simulation, ML, scientific stack или внешний optimizer.

Для Auto Tournament Builder public helper `starting_blind_candidates()` переиспользует тот же nice-value ladder, `_PaymentModel` и SB construction. `analyze_draft()` применяет terminal-pressure и physical-payment model к уже отредактированным rows, возвращает новое informational window/warnings и принципиально не возвращает replacement `levels`.

## Известная неопределённость

Алгоритм не моделирует стиль игроков, скорость раздач, размеры фактических re-entry, skill edge, сделки или длительность heads-up. Ориентировочное окно описывает структуру и pressure model, а не гарантирует время реального турнира.

Следующий этап: **Color-up Assistant**.
