# Что проверяется автоматически

- Миграции SQLite и структурные ограничения.
- Регистрация, защита от дублей, вылет, re-entry, лимит и отмена.
- Расчёт фонда, среднего стека и BB.
- Таймер: продолжение нового турнира, пауза, продолжение, переход и восстановление сервисом.
- Генерация локального QR-кода.
- Полный тестовый сценарий турнира в отдельной временной базе.
- Формат первого WebSocket-снимка.
- Точная сумма выплат, rounding residual, предварительный/финальный статус, Bubble/ITM, Undo и обновление v1-базы.
- Chip Inventory CRUD, валидация номиналов, zero quantity, server totals, единственный optional default, каскадное удаление и локальная Alembic-миграция.
- Structure Generator: planned re-entry arithmetic, target/break duration, nice values, growth, BB Ante, finish window, extension levels, exact denomination compatibility, API и editable snapshot regression.
- Auto Tournament Builder: minimal API inputs, per-player re-entry arithmetic, Combined Inventory immutability, deterministic staged search, duration/ante adaptation, editable Apply, read-only diagnostics и chip/structure snapshots.

# Что требует проверки на мобильном устройстве

- Доступность по Wi‑Fi, работа QR-кода и возможные ограничения роутера.
- Поведение Safari после блокировки, смены приложения и пропажи сети.
- Размеры элементов, safe area и полноэкранный режим.
- Звуковые сигналы, так как браузер требует реального пользовательского нажатия.
- Эргономика строк номиналов на iPhone Safari, цифровая клавиатура, safe area и отсутствие горизонтальной прокрутки при редактировании набора.
- Generator в normal/fast/deep, no-ante и physical-plan сценариях; после Apply — ручные change/reorder/break move/delete/add, создание турнира и неизменность структуры после перезапуска.
- Auto Builder на фактическом Chip Inventory: normal/fast/long/low-inventory/multi-set, mobile preview, modal regeneration и отсутствие silent changes после ручного редактирования.
