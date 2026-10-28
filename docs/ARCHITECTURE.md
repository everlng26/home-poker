# Архитектура

Приложение — один FastAPI-процесс на компьютере, SQLite в `data/poker.db` и браузеры в локальной сети. Сервер является единственным источником истины; пользовательские интерфейсы получают HTTP-снимки и WebSocket-обновления.

Основа использует SQLAlchemy 2, Alembic, Jinja2 и обычные ES-модули. Node.js, облачные сервисы и отдельные процессы очередей не используются.

Изменения доменных данных выполняются сервисами в коротких SQLite-транзакциях. Идемпотентность команд обеспечивается уникальными request ID в журнале событий.

`PayoutService` валидирует структуру, рассчитывает выплаты из существующего prize pool и определяет серверные Bubble/ITM-переходы. Клиенты получают payout state и публичные события в том же snapshot/WebSocket-потоке. Подробности: [PAYOUTS.md](PAYOUTS.md).

`BountyService` валидирует Fixed Bounty split и выводит K.O., bounty winnings и K.O. Leader из неизменяемого журнала событий. Champion surviving bounty записывается отдельным идемпотентным событием. Клиенты только отображают готовый server snapshot. Подробности: [BOUNTY.md](BOUNTY.md).

`ChipInventoryService` управляет независимым агрегатом физических наборов `ChipSet → ChipDenomination`. Сервис одной транзакцией валидирует и заменяет состав набора, вычисляет `total_chips` и `total_value`, а также хранит единственный optional default через существующую таблицу `app_settings`. Наборы не связаны с турнирами и не изменяются во время игры. Подробности: [CHIP_INVENTORY.md](CHIP_INVENTORY.md).

`StackOptimizerService` читает один или несколько `ChipSet`, агрегирует одинаковые номиналы во временный Combined Inventory и решает bounded integer-задачу на сервере. Exact initial stack является hard constraint. Re-entry pack решается отдельно, а максимальный резерв ограничивается правилом `planned_players × max_reentries_per_player`; отсутствие полного worst-case coverage остаётся warning, а не solve failure. Поиск детерминирован, использует suffix-value, GCD и chip-count pruning и не требует внешнего solver. Применённый результат сохраняется как независимый `TournamentChipPlan` snapshot без внешнего ключа на изменяемые наборы. Подробности: [STACK_OPTIMIZER.md](STACK_OPTIMIZER.md).

`TournamentStructureGeneratorService` детерминированно строит `play`/`break` payload существующей BlindLevel-архитектуры. Target duration переводится в число уровней с учётом перерывов; terminal BB выводится из planner-only planned chip volume и документированной late-game pressure heuristic. Кандидаты используют poker-friendly ladder, scoring и optional exact denomination representability. После Apply generator parameters не сохраняются: мастер передаёт итоговые строки существующему editor, а Tournament получает обычный structure snapshot. Подробности: [STRUCTURE_GENERATOR.md](STRUCTURE_GENERATOR.md).

`AutoTournamentBuilderService` является stateless orchestration boundary: физический Combined Inventory проходит через существующий Stack Optimizer, небольшой denomination-aware first-blind search и существующий Structure Generator. Builder сравнивает целые tournament plans, но не записывает состояние и не создает parallel Tournament Creation. Apply передает chip-plan payload и BlindLevel-compatible rows в обычную форму и редактор; ручной diagnostics API ничего не регенерирует. Подробности: [AUTO_TOURNAMENT_BUILDER.md](AUTO_TOURNAMENT_BUILDER.md).

Таймер работает в управляемой asyncio-задаче FastAPI и не зависит от открытой страницы. Новый турнир создаётся на паузе и запускается командой `resume`; отдельная кнопка «Старт» интерфейсу не нужна. После сна компьютера таймер сверяет сохранённое UTC-время и проходит пропущенные уровни на сервере. Ручные и автоматические команды сериализуются блокировкой турнира. При чтении SQLite временные значения дополнительно приводятся к UTC, потому что SQLite может вернуть их без информации о часовом поясе.

Сетевой модуль показывает все подходящие активные частные IPv4-адреса и локальный адрес компьютера. Пользователь сам выбирает адрес для QR-кодов; QR-коды генерируются локальной библиотекой `qrcode==8.2` в SVG.
