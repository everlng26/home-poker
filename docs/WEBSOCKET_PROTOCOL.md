# WebSocket-синхронизация

Endpoint: /ws/tournaments/{tournament_id}.

Сразу после соединения сервер отправляет полный снимок с protocol_version=1, type=state_snapshot, tournament_id, event_id и payload.

После изменения таймера, игроков, структуры или выплат сервер рассылает tournament_updated. Тот же snapshot содержит payout structure, Bubble/ITM, Fixed Bounty pools, K.O. attribution, event-derived player results и K.O. Leader; отдельный polling или клиентское вычисление не используются. Клиент также отправляет heartbeat; при возвращении из фонового режима Safari он заново получает полный снимок. Неизвестная версия или неизвестный тип сообщения игнорируются.
