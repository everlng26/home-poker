from fastapi.testclient import TestClient

from app.main import app


def test_health_and_home_page() -> None:
    with TestClient(app) as client:
        health = client.get("/health")
        home = client.get("/")
        create_page = client.get("/tournaments/new")
        internal_pages = [client.get(path) for path in ("/login/1", "/admin/1", "/display/1")]
        display_script = client.get("/static/js/display.js")
        admin_script = client.get("/static/js/admin.js")
        create_script = client.get("/static/js/create.js")
        home_script = client.get("/static/js/home.js")
        dialog_script = client.get("/static/js/dialog.js")
        app_css = client.get("/static/css/app.css")
    assert health.json() == {"status": "ok"}
    assert home.status_code == 200
    assert create_page.status_code == 200
    assert "Создание турнира" in create_page.text
    assert 'id="new-tournament"' in create_page.text
    assert 'id="create-level-editor"' in create_page.text
    assert 'class="level-builder"' in create_page.text
    assert 'id="level-count"' in create_page.text
    assert 'id="no-ante"' in create_page.text
    assert 'id="create-player-list"' in create_page.text
    assert "Создать турнир и открыть экран" in create_page.text
    assert "перетаскивайте строки за ручку" in create_page.text
    assert "create.js?v=20260816-4" in create_page.text
    assert 'id="create-payout-panel"' in create_page.text
    assert 'id="create-payout-list"' in create_page.text
    assert 'id="create-payout-total"' in create_page.text
    assert 'id="add-payout-place"' in create_page.text
    assert '>Добавить место</button>' in create_page.text
    assert 'name="bounty_mode" value="fixed"' in create_page.text
    assert ">Bounty</strong>" in create_page.text
    assert ">Fixed Bounty</strong>" not in create_page.text
    assert "Фиксированная награда за каждый K.O." in create_page.text
    assert 'id="bounty-field" hidden' in create_page.text
    assert "Домашний покер" in home.text
    assert "Домой" in home.text
    assert "Создать турнир" not in home.text
    assert "home.js?v=20260814-2" in home.text
    assert "app.css?v=20260816-3" in home.text
    assert all(page.status_code == 200 and "Домой" in page.text for page in internal_pages)
    assert 'class="display-action"' in internal_pages[2].text
    assert "/login/1" in internal_pages[2].text
    assert 'id="display-activate"' in internal_pages[2].text
    assert 'id="display-sound"' in internal_pages[2].text
    assert 'class="sound-icon-muted"' in internal_pages[2].text
    assert 'class="sound-icon-waves"' in internal_pages[2].text
    assert 'id="finish-celebration"' in internal_pages[2].text
    assert 'id="finish-celebration-confetti"' in internal_pages[2].text
    assert 'id="display-event-popup"' in internal_pages[2].text
    assert 'id="display-event-popup-player"' in internal_pages[2].text
    assert 'id="display-admin-qr"' in internal_pages[2].text
    assert "/api/v1/tournaments/1/qr/admin" in internal_pages[2].text
    assert "finish-celebration-fireworks" not in internal_pages[2].text
    assert "finish-celebration-particles" not in internal_pages[2].text
    assert 'id="display-ticker-track"' in internal_pages[2].text
    assert 'id="display-winner-name"' in internal_pages[2].text
    assert 'class="display-standings"' in internal_pages[2].text
    assert "display.js?v=20260813-5" in internal_pages[2].text
    assert 'id="display-payouts"' in internal_pages[2].text
    assert 'id="display-ko-leader"' in internal_pages[2].text
    assert 'id="display-final-ko-leader"' in internal_pages[2].text
    assert 'class="admin-actions"' in internal_pages[1].text
    assert "/display/1" in internal_pages[1].text
    assert 'id="admin-qr"' in internal_pages[1].text
    assert "admin.js?v=20260813-7" in internal_pages[1].text
    assert 'id="admin-payouts"' in internal_pages[1].text
    assert 'id="admin-bounty-pool"' in internal_pages[1].text
    assert 'id="edit-payouts"' in internal_pages[1].text
    assert 'id="payout-editor" class="admin-payout-editor" hidden' in internal_pages[1].text
    assert 'id="save-payouts"' in internal_pages[1].text
    assert 'id="finalize-payouts"' not in internal_pages[1].text
    assert internal_pages[1].text.index('admin-players') < internal_pages[1].text.index('id="admin-payouts"')
    assert 'id="confirm-dialog"' not in internal_pages[1].text
    assert 'id="warning-dialog"' not in internal_pages[1].text
    assert 'id="finish-dialog"' not in internal_pages[1].text
    assert "/api/v1/tournaments/1/qr/admin" in internal_pages[1].text
    assert "Изменить структуру" in internal_pages[1].text
    required_cutoff = 'id="late-registration-end" type="number" min="1" inputmode="numeric" placeholder="например, 3" required'
    assert required_cutoff in create_page.text
    assert required_cutoff in internal_pages[1].text
    assert "Конструктор уровней" in internal_pages[1].text
    assert "перетаскивайте строки" in internal_pages[1].text
    assert "Минуты" in internal_pages[1].text
    assert "SB" in internal_pages[1].text
    assert "BB" in internal_pages[1].text
    assert "Ante" in internal_pages[1].text
    assert 'id="pin"' in internal_pages[0].text and "autofocus" in internal_pages[0].text
    assert display_script.status_code == 200
    assert create_script.status_code == 200
    assert "data.bounty_mode" in create_script.text
    assert "freerollField.hidden = fixed" in create_script.text
    assert "killer_tournament_player_id" in admin_script.text
    assert "app-dialog-select" in dialog_script.text
    assert "Нажмите, чтобы выбрать игрока" in dialog_script.text
    assert "(pin ? input : confirm).focus()" in dialog_script.text
    assert "row.className = 'level-edit'" in create_script.text
    assert "handle.className = 'drag-handle'" in create_script.text
    assert "document.createElement('span')" in create_script.text
    assert "handle.draggable = true" in create_script.text
    assert "handle.addEventListener('dragstart'" in create_script.text
    assert "row.addEventListener('dragover'" in create_script.text
    assert "row.addEventListener('drop'" in create_script.text
    assert "row.dataset.dropHint = position === 'before' ? 'Вставить перед' : 'Вставить после'" in create_script.text
    assert "dropTarget !== row" in create_script.text
    assert "row.addEventListener('drop'" in admin_script.text
    assert "dropTarget !== row" in admin_script.text
    assert "function validateLateRegistrationEnd(report = false)" in create_script.text
    assert "function validateLateRegistrationEnd(report = false)" in admin_script.text
    assert "move('up', '↑', 'Переместить выше')" in create_script.text
    assert "move('down', '↓', 'Переместить ниже')" in create_script.text
    assert ".create-page.structure-no-ante .level-edit" in app_css.text
    assert "#admin.structure-no-ante .level-edit" in app_css.text
    assert "grid-template-columns: 52px 52px minmax(0, 1fr)" in app_css.text
    assert ".level-edit.dragging" in app_css.text
    assert ".level-edit.drop-before" in app_css.text
    assert ".level-edit.drop-after" in app_css.text
    assert "content: attr(data-drop-hint)" in app_css.text
    assert "playerName + ' ВХОДИТ В ИГРУ'" in display_script.text
    assert "playerName + ' ВЫЛЕТАЕТ'" in display_script.text
    assert "playerName + ' ДЕЛАЕТ РЕ-ЭНТРИ'" in display_script.text
    assert "const tickerItems = state.status === 'finished'" in display_script.text
    assert "'ПОБЕДИТЕЛЬ — ' + winnerName.toUpperCase()" in display_script.text
    assert "row.className = 'display-standing-row'" in display_script.text
    assert "Повторных входов:" not in display_script.text
    assert "Без повторных входов" not in display_script.text
    assert "Повторных входов:" not in admin_script.text
    assert "Без повторных входов" not in admin_script.text
    assert "return 'LIVE';" not in display_script.text
    assert "playCue('minute')" in display_script.text
    assert "playCue('level')" in display_script.text
    assert "playCue('breakStart')" in display_script.text
    assert "playCue('breakEnd')" in display_script.text
    assert "let audioEnabled = true;" in display_script.text
    assert "if (audioEnabled && !audioContext) await enableAudio(false);" in display_script.text
    assert "document.addEventListener('pointerdown'" in display_script.text
    assert "updateAudioButton();\nconnectTournament" in display_script.text
    assert "playCue('pause')" in display_script.text
    assert "playCue('resume')" in display_script.text
    assert "playCue('finished')" in display_script.text
    assert "playCue('playerRegistered')" in display_script.text
    assert "playCue('playerEliminated')" in display_script.text
    assert "playCue('reentry')" in display_script.text
    assert display_script.text.count('playPublicEventCue(event);') == 1
    assert "clearPublicEventPopups();" in display_script.text
    assert "if (state.status === 'finished') clearPublicEventPopups();" not in display_script.text
    assert "queuePublicEventPopup(publicEvent)" in display_script.text
    assert "player_registered: {label: 'Входит в игру'" in display_script.text
    assert "player_eliminated: {label: 'Вылетает'" in display_script.text
    assert "reentry_added: {label: 'Делает ре-энтри'" in display_script.text
    assert "late_registration_closing: {label: 'Поздняя регистрация'" in display_script.text
    assert "player_name: 'Заканчивается после этого уровня'" in display_script.text
    assert "ПОЗДНЯЯ РЕГИСТРАЦИЯ ЗАКАНЧИВАЕТСЯ ПОСЛЕ СЛЕДУЮЩЕГО УРОВНЯ" in display_script.text
    assert "ПОЗДНЯЯ РЕГИСТРАЦИЯ ЗАКАНЧИВАЕТСЯ ПОСЛЕ ЭТОГО УРОВНЯ" in display_script.text
    assert "late_registration_closing" in display_script.text
    assert "bubble_reached: {label: 'Баббл'" in display_script.text
    assert "itm_reached: {label: 'В призах'" in display_script.text
    assert "newPayoutEvent" in display_script.text
    assert "display-event-popup-bounty" in display_script.text
    assert "label.append(document.createTextNode('K.O.'))" not in display_script.text
    assert "ticker-ko-badge" in display_script.text
    assert "bounty_amount_awarded) + ' BOUNTY'" in display_script.text
    assert "return {kind: 'ko'" in display_script.text
    assert "finishCelebrationPending" in display_script.text
    assert "state.ko_leader.names[0]" in display_script.text
    assert "root.querySelector('#display-admin-qr').hidden = !showAdminQr" in display_script.text
    assert "'Ре-энтри: ' + player.reentries" not in display_script.text
    assert "'re-entry: ' + player.reentries" not in admin_script.text
    assert "state.is_freeroll ? 'Входов: ' + player.entries_count : money(player.winnings)" in display_script.text
    assert "isFreeroll ? 'Входов: ' + player.entries_count : money(player.winnings)" in admin_script.text
    assert '.display-event-popup[data-tone="registration"]' in app_css.text
    assert '.display-event-popup[data-tone="bubble"]' in app_css.text
    assert '.display-event-popup[data-tone="itm"]' in app_css.text
    assert ".display-event-popup-ko-name" in app_css.text
    assert ".display-event-popup-bounty" in app_css.text
    assert ".ticker-ko-badge" in app_css.text
    assert ".freeroll-toggle[hidden]" in app_css.text
    assert ".ticker-ko-event strong" in app_css.text
    assert "TV layout must follow available height" in app_css.text
    assert ".display.display-has-payouts .display-info { overflow: visible; }" in app_css.text
    assert ".display-side { max-height: min(62vh, 620px); }" in app_css.text
    assert "@media (max-height: 800px) and (min-width: 701px)" in app_css.text
    assert "--display-pad-top: clamp(24px, 3vh, 42px);" in app_css.text
    assert "grid-auto-rows: 48px;" in app_css.text
    assert ".display { --display-pad-top: 18px; --display-pad-bottom: 18px; }" in app_css.text
    assert "margin-bottom: 12px;" in app_css.text
    assert ".display-admin-qr" in app_css.text
    assert ".tournament-type-field label:has(input:checked)" in app_css.text
    assert ".payout-editor-panel" in app_css.text
    assert ".create-page .payout-editor-heading" in app_css.text
    assert "width: min(calc(100vw - 32px), 760px)" in app_css.text
    assert "text-wrap: balance; white-space: normal" in app_css.text
    assert "piece.style.setProperty('--delay'" in display_script.text
    assert "launchFinishCelebration()" in display_script.text
    assert "renderFinishConfetti()" in display_script.text
    assert "renderFinishFireworks" not in display_script.text
    assert "renderFinishCelebrationWave" not in display_script.text
    assert "upcomingStructureSignature" in display_script.text
    assert "scrollUpcomingToCurrent" in display_script.text
    assert "function scheduleUpcomingAlignment" in display_script.text
    assert "if (active) scheduleUpcomingAlignment(120);" in display_script.text
    assert "behavior: 'auto'" in display_script.text
    assert "container.replaceChildren(fragment)" in display_script.text
    assert home_script.status_code == 200
    assert dialog_script.status_code == 200
    assert "dialog.js?v=20260811-2" in home_script.text
    assert "dialog.js?v=20260813-3" in admin_script.text
    assert "export function openDialog" in dialog_script.text
    assert "export function showNotice" in dialog_script.text
    assert "dialog.showModal()" in dialog_script.text
    assert "input.reportValidity()" in dialog_script.text
    assert "icon = tone" in dialog_script.text
    assert "iconByTone[safeIcon]" in dialog_script.text
    assert ".app-dialog-field[hidden]" in app_css.text
    assert "delete-dialog" not in home_script.text
    assert "confirm-dialog" not in admin_script.text
    assert "warning-dialog" not in admin_script.text
