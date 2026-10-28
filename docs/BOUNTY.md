# Fixed Bounty subsystem

Home Poker поддерживает только `none` и `fixed`. PKO, Mystery Bounty, split bounty и несколько killers намеренно не реализованы.

## Money split

Общий `buy_in_amount` остаётся суммой, которую платит игрок. Для Fixed Bounty:

- `main_prize_contribution = buy_in_amount - bounty_amount`;
- `main_prize_pool = entries_count × main_prize_contribution`;
- `bounty_pool = entries_count × bounty_amount`;
- `total_collected = entries_count × buy_in_amount`.

Обычная payout structure применяется только к main prize pool. Все суммы целые; отдельного счётчика entries нет.

## K.O. events и re-entry

Fixed Bounty elimination требует одного активного killer, отличного от выбывшего. `player_eliminated` хранит eliminated entry, killer, номер текущего entry и snapshot `bounty_amount_awarded`. Каждый действительный event даёт killer один K.O. и одну bounty-выплату. Re-entry увеличивает существующий `entries_count`; следующий bust создаёт новый отдельный K.O. и новый bounty.

K.O. count, bounty winnings и leader вычисляются из неотменённых событий. При одинаковом максимальном числе K.O. лидером считается игрок, который первым достиг этого значения; поэтому TV всегда показывает одно имя. Undo пересчитывает этот порядок по оставшимся событиям. Отдельный mutable leaderboard не существует.

## Undo и завершение

Undo использует существующий reversal: восстановление player state и `reversed_at` автоматически исключают K.O. и bounty из derived результатов и пересчитывают leader. Если после elimination уже сделан re-entry или другое зависимое действие, действует прежний запрет cascade rollback.

Последний surviving entry не может быть выбит, поэтому при определении champion сервер один раз создаёт `champion_bounty_awarded`. Эта сумма входит в bounty winnings, но не увеличивает K.O. При повторном чтении или рестарте событие не дублируется; при безопасном переоткрытии автоматически завершённого турнира создаётся reversal.

После завершения соблюдаются инварианты:

- main payouts total = main prize pool;
- bounty winnings total = bounty pool;
- main prize pool + bounty pool = total collected.

Итог игрока содержит entries, total buy-ins, main prize winnings, bounty winnings, total winnings, net result и K.O. count. Lifetime-агрегаты не сохраняются.
