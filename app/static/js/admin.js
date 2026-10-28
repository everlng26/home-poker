import {command as sendCommand, connectTournament} from './live.js?v=20261028-1';
import {openDialog, showNotice} from './dialog.js?v=20261028-1';

const root = document.querySelector('#admin');
const id = root.dataset.tournamentId;
const message = root.querySelector('#message');
let state;
let structureDirty = false;
let payoutDirty = false;
let online = true;
let authenticated = false;

// Сессия админки могла истечь (например, после перезапуска или входа в другой турнир): ведём на ввод PIN.
async function command(url, body) {
  try {
    return await sendCommand(url, body);
  } catch (error) {
    if (error.code === 'auth_required' || error.status === 403) location.href = '/login/' + id;
    throw error;
  }
}

const plural = (value, one, few, many) => {
  const mod100 = value % 100; const mod10 = value % 10;
  return mod100 >= 11 && mod100 <= 14 ? many : mod10 === 1 ? one : mod10 >= 2 && mod10 <= 4 ? few : many;
};
const svgIcon = name => '<svg class="icon" aria-hidden="true"><use href="#i-' + name + '"/></svg>';

const clock = seconds => String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
const say = text => { message.textContent = text || ''; };
const money = value => Math.round(Number(value || 0)).toLocaleString('ru-RU') + ' ' + (state?.currency_label || '₽');
const localTime = value => {
  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/.test(value);
  const instant = new Date(hasTimezone ? value : value + 'Z');
  return instant.toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  });
};

function markStructureDirty() {
  structureDirty = true;
}

let draggedRow;
let dropTarget;
let dropPosition;

function structureEditor() {
  return root.querySelector('#level-editor');
}

function updateStructureSummary() {
  const rows = [...root.querySelectorAll('.level-edit')];
  const totalMinutes = rows.reduce((sum, row) => sum + Number(row.querySelector('[data-field="minutes"]')?.value || 0), 0);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  root.querySelector('#level-count').textContent = String(rows.length);
  root.querySelector('#structure-total').textContent = String(hours).padStart(2, '0') + ':' + String(minutes).padStart(2, '0');
}

function validateLateRegistrationEnd(report = false) {
  const input = root.querySelector('#late-registration-end');
  const playLevels = root.querySelectorAll('.level-edit[data-kind="play"]').length;
  input.max = String(playLevels);
  const value = Number(input.value);
  const valid = input.value !== '' && Number.isInteger(value) && value >= 1 && value <= playLevels;
  input.setCustomValidity(valid ? '' : 'Укажите номер существующего игрового уровня.');
  if (!valid && report) {
    input.reportValidity();
    input.scrollIntoView({behavior: 'smooth', block: 'center'});
    input.focus({preventScroll: true});
  }
  return valid ? value : null;
}

function renumberLevels() {
  let playNumber = 0;
  root.querySelectorAll('.level-edit').forEach(row => {
    const isBreak = row.dataset.kind === 'break';
    if (!isBreak) playNumber += 1;
    const number = row.querySelector('.level-number');
    number.textContent = isBreak ? '' : String(playNumber);
    number.hidden = isBreak;
    const kind = row.querySelector('.level-kind');
    kind.textContent = isBreak ? 'Перерыв' : '';
    kind.hidden = !isBreak;
  });
  updateStructureSummary();
  validateLateRegistrationEnd();
}

function moveRow(row, direction) {
  const editor = structureEditor();
  const sibling = direction < 0 ? row.previousElementSibling : row.nextElementSibling;
  if (!sibling) return;
  if (direction < 0) editor.insertBefore(row, sibling);
  else editor.insertBefore(sibling, row);
  markStructureDirty();
  renumberLevels();
}

function clearDropTarget() {
  if (dropTarget) {
    dropTarget.classList.remove('drop-before', 'drop-after');
    delete dropTarget.dataset.dropHint;
  }
  dropTarget = undefined;
  dropPosition = undefined;
}

function showDropTarget(row, position) {
  if (dropTarget === row && dropPosition === position) return;
  clearDropTarget();
  dropTarget = row;
  dropPosition = position;
  row.classList.add(position === 'before' ? 'drop-before' : 'drop-after');
  row.dataset.dropHint = position === 'before' ? 'Вставить перед' : 'Вставить после';
}

function bindDrag(row) {
  row.addEventListener('dragstart', event => {
    draggedRow = row;
    row.classList.add('dragging');
    structureEditor().classList.add('is-dragging');
    event.dataTransfer?.setData('text/plain', 'level');
    if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
  });
  row.addEventListener('dragover', event => {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    if (!draggedRow || draggedRow === row) {
      clearDropTarget();
      return;
    }
    const before = event.clientY < row.getBoundingClientRect().top + row.offsetHeight / 2;
    showDropTarget(row, before ? 'before' : 'after');
  });
  row.addEventListener('drop', event => {
    event.preventDefault();
    if (!draggedRow || dropTarget !== row) return;
    structureEditor().insertBefore(draggedRow, dropPosition === 'before' ? row : row.nextElementSibling);
    const movedRow = draggedRow;
    clearDropTarget();
    movedRow.classList.add('just-dropped');
    setTimeout(() => movedRow.classList.remove('just-dropped'), 480);
    markStructureDirty();
    renumberLevels();
  });
  row.addEventListener('dragend', () => {
    clearDropTarget();
    structureEditor().classList.remove('is-dragging');
    row.classList.remove('dragging');
    draggedRow = undefined;
    renumberLevels();
  });
}

function levelRow(level, number = root.querySelectorAll('.level-edit').length + 1) {
  const row = document.createElement('article');
  row.className = 'level-edit';
  row.dataset.kind = level.kind;
  row.draggable = true;

  const head = document.createElement('header');
  head.className = 'level-edit-head';
  const handle = document.createElement('button');
  handle.type = 'button'; handle.className = 'drag-handle'; handle.innerHTML = svgIcon('grip'); handle.title = 'Перетащить уровень'; handle.setAttribute('aria-label', 'Перетащить уровень');
  const numberLabel = document.createElement('strong');
  numberLabel.className = 'level-number'; numberLabel.textContent = String(number);
  const kind = document.createElement('span');
  kind.className = 'level-kind'; kind.textContent = level.kind === 'break' ? 'Перерыв' : ''; kind.hidden = level.kind !== 'break';
  head.append(handle, numberLabel, kind);

  const ordering = document.createElement('div');
  ordering.className = 'level-order';
  const move = (direction, label, title) => {
    const button = document.createElement('button');
    button.type = 'button'; button.dataset.move = direction; button.innerHTML = svgIcon(label); button.title = title; button.setAttribute('aria-label', title); button.onclick = () => moveRow(row, direction === 'up' ? -1 : 1);
    ordering.append(button);
  };
  move('up', 'up', 'Переместить выше'); move('down', 'down', 'Переместить ниже');
  const remove = document.createElement('button');
  remove.type = 'button'; remove.className = 'remove-level'; remove.innerHTML = svgIcon('trash'); remove.title = 'Удалить строку'; remove.setAttribute('aria-label', 'Удалить строку');
  remove.onclick = () => { if (root.querySelectorAll('.level-edit').length > 1) { row.remove(); markStructureDirty(); renumberLevels(); } else say('Нужен хотя бы один уровень.'); };
  ordering.append(remove);
  row.append(head);

  const fields = document.createElement('div');
  fields.className = 'level-fields';
  const add = (field, label, value, minimum = 0, type = 'number') => {
    const wrapper = document.createElement('label');
    const caption = document.createElement('span'); caption.className = 'level-field-label'; caption.textContent = label; wrapper.append(caption);
    const input = document.createElement('input'); input.dataset.field = field; input.type = type; input.inputMode = type === 'number' ? 'numeric' : 'text'; input.min = String(minimum); input.value = String(value ?? '');
    wrapper.append(input); fields.append(wrapper);
  };
  add('minutes', 'Минуты', Math.round(level.duration_seconds / 60), 1);
  if (level.kind === 'play') {
    add('sb', 'SB', level.small_blind, 1);
    add('bb', 'BB', level.big_blind, 1);
    if (state.ante_enabled) add('ante', 'Ante', level.ante, 0);
  }
  row.append(fields, ordering);
  row.addEventListener('input', () => { markStructureDirty(); updateStructureSummary(); });
  bindDrag(row);
  return row;
}

function setStructureLocked(locked) {
  root.querySelectorAll('#level-editor input, #level-editor button, #save-levels, #add-play, #add-break').forEach(item => { item.disabled = locked; });
  root.querySelectorAll('.level-edit').forEach(row => { row.draggable = !locked; });
  const cutoff = root.querySelector('#late-registration-end');
  cutoff.disabled = locked;
  const editButton = root.querySelector('#edit-structure');
  editButton.disabled = locked;
  editButton.textContent = locked ? 'Структура зафиксирована' : 'Изменить структуру';
}

function drawLevels() {
  const editor = structureEditor();
  editor.innerHTML = '';
  state.levels.forEach((level, index) => editor.append(levelRow(level, index + 1)));
  const cutoff = root.querySelector('#late-registration-end');
  cutoff.value = state.late_registration_end_level_number === null || state.late_registration_end_level_number === undefined ? '' : String(state.late_registration_end_level_number);
  validateLateRegistrationEnd();
  structureDirty = false;
  renumberLevels();
  setStructureLocked(state.status === 'finished');
}

const eventMeta = {
  player_registered: {label: 'Игрок добавлен', tone: 'positive', icon: '+'},
  player_eliminated: {label: 'Игрок выбыл', tone: 'warning', icon: '↓'},
  player_out: {label: 'Игрок в ауте', tone: 'danger', icon: '×'},
  reentry_added: {label: 'Добавлен повторный вход', tone: 'positive', icon: '↻'},
  event_reversed: {label: 'Действие отменено', tone: 'neutral', icon: '↶'},
  timer_command: {label: 'Изменение таймера', tone: 'neutral', icon: '◷'},
  structure_replaced: {label: 'Структура изменена', tone: 'neutral', icon: '≡'},
  tournament_reopened: {label: 'Турнир возобновлён', tone: 'warning', icon: '↻'},
  tournament_finished: {label: 'Турнир окончен', tone: 'warning', icon: '✓'},
  tournament_created: {label: 'Турнир создан', tone: 'positive', icon: '+'},
  payout_structure_changed: {label: 'Выплаты изменены', tone: 'neutral', icon: '₽'},
  payouts_finalized: {label: 'Выплаты финализированы', tone: 'positive', icon: '₽'},
  bubble_reached: {label: 'Баббл', tone: 'warning', icon: '♠'},
  itm_reached: {label: 'Все оставшиеся в призах', tone: 'positive', icon: '₽'},
};
const timerStates = {running: 'Идёт', paused: 'Пауза', stopped: 'Остановлен'};
const payoutStages = {
  registration_open: 'Регистрация открыта',
  registration_closed: 'Регистрация закрыта',
  bubble: 'Баббл',
  itm: 'Все оставшиеся в призах',
  tournament_finished: 'Турнир завершён',
  configuration_error: 'Проверьте настройки',
};

function payoutBasisPoints(value) {
  const text = String(value).trim();
  if (!/^\d+(?:[.,]\d{1,2})?$/.test(text)) return null;
  return Math.round(Number(text.replace(',', '.')) * 100);
}

function readAdminPayouts() {
  return [...root.querySelectorAll('#admin-payout-list input')].map(input => Number(input.value.replace(',', '.')));
}

function updateAdminPayoutTotal() {
  const values = [...root.querySelectorAll('#admin-payout-list input')].map(input => payoutBasisPoints(input.value));
  const valid = values.length > 0 && values.every(value => value !== null && value > 0);
  const total = valid ? values.reduce((sum, value) => sum + value, 0) : 0;
  const label = root.querySelector('#admin-payout-total');
  label.textContent = valid ? (total / 100).toLocaleString('ru-RU') + '%' : '—';
  label.classList.toggle('is-invalid', !valid || total !== 10000);
  return valid && total === 10000;
}

function renderAdminPayoutEditor(percentages) {
  const list = root.querySelector('#admin-payout-list');
  const locked = state.payouts.status === 'final' || state.status === 'finished';
  list.replaceChildren();
  percentages.forEach((percentage, index) => {
    const line = state.payouts.lines[index];
    const row = document.createElement('div'); row.className = 'payout-edit-row';
    const place = document.createElement('strong'); place.textContent = (index + 1) + ' место';
    const field = document.createElement('label'); field.className = 'payout-percentage-field';
    const input = document.createElement('input');
    input.type = 'number'; input.inputMode = 'decimal'; input.min = '0.01'; input.max = '100'; input.step = '0.01'; input.value = String(percentage); input.disabled = locked;
    input.setAttribute('aria-label', 'Процент для ' + (index + 1) + ' места');
    input.addEventListener('input', () => { payoutDirty = true; updateAdminPayoutTotal(); });
    const suffix = document.createElement('span'); suffix.textContent = '%'; field.append(input, suffix);
    const amount = document.createElement('span'); amount.className = 'payout-calculated-amount'; amount.textContent = line ? money(line.amount) : '—';
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary-action payout-remove'; remove.textContent = 'Удалить'; remove.disabled = locked || percentages.length === 1;
    remove.onclick = () => { const next = readAdminPayouts(); next.splice(index, 1); payoutDirty = true; renderAdminPayoutEditor(next); };
    row.append(place, field, amount, remove); list.append(row);
  });
  root.querySelector('#admin-add-payout').disabled = locked;
  root.querySelector('#save-payouts').disabled = locked;
  updateAdminPayoutTotal();
}

function renderAdminPayoutSummary() {
  const summary = root.querySelector('#admin-payout-summary');
  summary.replaceChildren();
  if (!state.payouts.configured) {
    const empty = document.createElement('p');
    empty.className = 'admin-payout-empty';
    empty.textContent = 'Структура выплат не настроена.';
    summary.append(empty);
    return;
  }
  state.payouts.lines.forEach(line => {
    const item = document.createElement('div');
    const place = document.createElement('span');
    place.textContent = line.place + ' место · ' + Number(line.percentage).toLocaleString('ru-RU') + '%';
    const amount = document.createElement('strong');
    amount.textContent = money(line.amount);
    item.append(place, amount);
    summary.append(item);
  });
}

function drawPayouts() {
  const panel = root.querySelector('#admin-payouts');
  panel.hidden = state.is_freeroll;
  if (state.is_freeroll) {
    payoutDirty = false;
    root.querySelector('#payout-editor').hidden = true;
    return;
  }
  root.querySelector('#admin-prize-pool').textContent = money(state.metrics.prize_pool);
  const bountyPoolItem = root.querySelector('#admin-bounty-pool-item');
  bountyPoolItem.hidden = state.bounty_mode !== 'fixed';
  root.querySelector('#admin-bounty-pool').textContent = money(state.metrics.bounty_pool);
  root.querySelector('#admin-payout-stage').textContent = payoutStages[state.payouts.stage] || state.payouts.stage;
  const badge = root.querySelector('#payout-status-badge');
  badge.textContent = state.payouts.status === 'final' ? 'Финальные' : 'Предварительные';
  badge.classList.toggle('is-final', state.payouts.status === 'final');
  badge.hidden = !state.payouts.configured;
  root.querySelector('#admin-payout-warning').textContent = state.payouts.configuration_error || '';
  renderAdminPayoutSummary();
  const locked = state.payouts.status === 'final' || state.status === 'finished';
  const editButton = root.querySelector('#edit-payouts');
  const editor = root.querySelector('#payout-editor');
  editButton.disabled = locked;
  editButton.textContent = locked ? 'Выплаты зафиксированы' : 'Изменить выплаты';
  if (locked) {
    payoutDirty = false;
    editor.hidden = true;
    editButton.hidden = false;
  }
  if (!payoutDirty) {
    const percentages = state.payouts.configured ? state.payouts.lines.map(line => line.percentage) : [100];
    renderAdminPayoutEditor(percentages);
  }
}
async function loadEvents() {
  const response = await fetch('/api/v1/tournaments/' + id + '/events');
  if (!response.ok) return;
  const events = await response.json();
  const list = root.querySelector('#events'); list.innerHTML = '';
  if (!events.length) { const empty = document.createElement('p'); empty.className = 'events-empty'; empty.textContent = 'Действий пока нет.'; list.append(empty); return; }
  // На телефоне журнал быстро становится длиннее всей админки: последние записи сразу, остальные по кнопке.
  const visibleEvents = 6;
  let olderEvents;
  if (events.length > visibleEvents) {
    olderEvents = document.createElement('details');
    olderEvents.className = 'event-older';
    const summary = document.createElement('summary');
    summary.textContent = 'Показать ещё ' + (events.length - visibleEvents);
    olderEvents.append(summary);
  }
  events.forEach((event, index) => {
    const meta = eventMeta[event.type] || {label: 'Событие турнира', tone: 'neutral', icon: '•'};
    const card = document.createElement('article'); card.className = 'event-item event-' + meta.tone;
    const marker = document.createElement('span'); marker.className = 'event-marker'; marker.textContent = meta.icon; marker.setAttribute('aria-hidden', 'true');
    const body = document.createElement('div'); body.className = 'event-body';
    const header = document.createElement('div'); header.className = 'event-header';
    const title = document.createElement('strong'); title.className = 'event-title'; title.textContent = meta.label;
    const time = document.createElement('time'); time.className = 'event-time'; time.dateTime = event.created_at; time.textContent = localTime(event.created_at);
    header.append(title, time); body.append(header);
    const details = document.createElement('div'); details.className = 'event-details';
    if (event.player_name) { const player = document.createElement('span'); player.className = 'event-player'; player.textContent = event.killer_name ? event.player_name + ' вылетает, баунти забирает ' + event.killer_name + ' (+' + money(event.bounty_amount_awarded) + ')' : event.player_name; details.append(player); }
    if (event.reversed_at) { const reversed = document.createElement('span'); reversed.className = 'event-reversed'; reversed.textContent = 'Отменено'; details.append(reversed); }
    if (details.childElementCount) body.append(details);
    card.append(marker, body);
    (index < visibleEvents || !olderEvents ? list : olderEvents).append(card);
  });
  if (olderEvents) list.append(olderEvents);
}

function draw(next) {
  if (!next?.id) return;
  state = next;
  const manuallyFinished = Boolean(state.is_manually_finished);
  root.classList.toggle('tournament-locked', manuallyFinished);
  root.classList.toggle('structure-no-ante', !state.ante_enabled);
  root.querySelector('#admin-title').textContent = state.name;
  document.title = state.name + ' · Админка';
  renderConnection();
  root.querySelector('#time').textContent = clock(state.remaining_seconds);
  root.querySelector('#dock-time').textContent = clock(state.remaining_seconds);
  const level = state.current_level;
  const levelLabel = root.querySelector('#level');
  levelLabel.replaceChildren();
  if (!level) levelLabel.textContent = 'Нет уровней';
  else if (level.kind === 'break') levelLabel.textContent = 'Перерыв';
  else {
    const blinds = document.createElement('b');
    blinds.textContent = number(level.small_blind) + ' / ' + number(level.big_blind) + (state.ante_enabled && level.ante ? ', анте ' + number(level.ante) : '');
    levelLabel.append('Уровень ' + level.level_number + ': ', blinds);
  }
  root.querySelector('#dock-level').textContent = levelLabel.textContent;
  const isFreeroll = Boolean(state.is_freeroll);
  root.querySelector('#freeroll-badge').hidden = !isFreeroll;
  drawMetrics(isFreeroll);
  drawTimerToggle();
  drawPayouts();
  const finishButton = root.querySelector('#finish-tournament');
  finishButton.hidden = manuallyFinished;
  finishButton.disabled = manuallyFinished;
  root.querySelectorAll('.admin-live-panel .controls button, #player-form input, #player-form button, .player-row button').forEach(button => {
    button.disabled = manuallyFinished;
  });
  const finalResults = root.querySelector('#final-results');
  finalResults.hidden = state.status !== 'finished';
  if (state.status === 'finished') {
    const standings = root.querySelector('#standings');
    standings.innerHTML = '';
    state.standings.forEach(player => {
      const row = document.createElement('article');
      row.className = 'admin-standing-row';
      const place = document.createElement('span');
      place.className = 'standing-place' + (player.place ? ' place-' + player.place : '');
      place.textContent = player.place || '—';
      const identity = document.createElement('div');
      identity.className = 'standing-identity';
      const name = document.createElement('strong');
      name.textContent = player.name;
      identity.append(name);
      if (!isFreeroll) {
        const entries = document.createElement('small');
        entries.textContent = 'Входов: ' + player.entries_count;
        identity.append(entries);
      }
      if (state.bounty_mode === 'fixed') {
        const bounty = document.createElement('small');
        bounty.textContent = 'K.O.: ' + player.ko_count + ' · Bounties: ' + money(player.bounty_winnings);
        identity.append(bounty);
      }
      row.append(place, identity);
      if (isFreeroll || player.winnings > 0) {
        const result = document.createElement('span');
        result.className = 'standing-reentries';
        result.textContent = isFreeroll ? 'Входов: ' + player.entries_count : money(player.winnings);
        row.append(result);
      } else {
        row.classList.add('without-payout');
      }
      standings.append(row);
    });
  }
  drawPlayers();
  root.querySelectorAll('.player-row button').forEach(button => { button.disabled = manuallyFinished; });
  const structureOpen = !root.querySelector('#structure-editor').hidden;
  if (!structureOpen || state.status === 'finished') drawLevels();
  else { setStructureLocked(false); updateStructureSummary(); }
  if (authenticated) loadEvents();
}

function number(value) {
  return Math.round(Number(value || 0)).toLocaleString('ru-RU');
}

function renderConnection() {
  const pill = root.querySelector('#connection');
  if (!online) {
    pill.textContent = 'Нет связи, переподключаюсь…';
    pill.dataset.state = 'offline';
    return;
  }
  if (!state) return;
  const finished = state.status === 'finished';
  pill.textContent = finished ? 'Завершён' : state.status === 'draft' ? 'Не начат' : state.current_level?.kind === 'break' && state.timer_status === 'running' ? 'Перерыв' : timerStates[state.timer_status] || state.timer_status;
  pill.dataset.state = finished ? 'finished' : state.timer_status;
}

function drawMetrics(isFreeroll) {
  const metrics = root.querySelector('#metrics');
  metrics.replaceChildren();
  const add = (value, label, before = false) => {
    const item = document.createElement('span');
    const strong = document.createElement('b'); strong.textContent = value;
    if (before) item.append(label + ' ', strong); else item.append(strong, ' ' + label);
    metrics.append(item);
  };
  if (state.status === 'draft') add(String(state.metrics.registered_players), plural(state.metrics.registered_players, 'игрок записан', 'игрока записаны', 'игроков записаны'));
  else add(state.metrics.active_players + ' из ' + state.metrics.registered_players, 'в игре');
  add(number(state.metrics.total_entries), plural(state.metrics.total_entries, 'вход', 'входа', 'входов'));
  if (state.metrics.average_stack_bb) add(Math.round(state.metrics.average_stack_bb) + ' BB', 'средний стек', true);
  if (!isFreeroll) add(money(state.metrics.prize_pool), 'фонд', true);
  if (state.bounty_mode === 'fixed') add(money(state.metrics.bounty_pool), 'баунти', true);
}

// Одна большая кнопка вместо пары «Пауза/Продолжить»: показывает только доступное действие.
function drawTimerToggle() {
  const running = state.timer_status === 'running';
  const action = running ? 'pause' : 'resume';
  const label = running ? 'Пауза' : state.status === 'draft' ? 'Начать турнир' : 'Продолжить';
  const toggle = root.querySelector('#timer-toggle');
  toggle.dataset.action = action;
  toggle.innerHTML = svgIcon(running ? 'pause' : 'play') + '<span>' + label + '</span>';
  toggle.hidden = state.status === 'finished';
  const dockToggle = root.querySelector('.dock-toggle');
  dockToggle.dataset.action = action;
  dockToggle.innerHTML = svgIcon(running ? 'pause' : 'play') + '<span>' + (running ? 'Пауза' : 'Старт') + '</span>';
  dockToggle.hidden = state.status === 'finished';
  root.classList.toggle('is-paused', !running);
}

function playerRow(player) {
  const row = document.createElement('div');
  row.className = 'player-row is-' + player.status;
  const info = document.createElement('div'); info.className = 'player-info';
  const name = document.createElement('strong'); name.className = 'player-name'; name.textContent = player.name;
  const details = document.createElement('div'); details.className = 'player-details';
  const detail = (text, className = '') => { const item = document.createElement('span'); item.className = className; item.textContent = text; details.append(item); };
  detail(player.entries_count + ' ' + plural(player.entries_count, 'вход', 'входа', 'входов'), 'player-entries');
  if (player.status === 'eliminated' && player.elimination_place) detail(player.elimination_place + ' место');
  if (player.status === 'out') detail(player.elimination_place ? 'аут, ' + player.elimination_place + ' место' : 'аут');
  if (state.bounty_mode === 'fixed' && player.ko_count) detail(player.ko_count + ' K.O., +' + money(player.bounty_winnings), 'player-ko');
  info.append(name, details);
  row.append(info);
  const actions = document.createElement('div'); actions.className = 'player-actions';
  const action = (label, className, handler) => {
    const button = document.createElement('button'); button.type = 'button'; button.className = className; button.textContent = label; button.onclick = handler; actions.append(button);
  };
  if (player.status === 'active') action('Вылет', 'player-bust', () => playerCommand(player.id, 'eliminate'));
  if (player.status === 'eliminated') {
    action('Аут', 'player-out', () => playerCommand(player.id, 'out'));
    action('Ре-энтри', 'player-reentry', () => playerCommand(player.id, 'reenter'));
  }
  if (player.status === 'out') action('Ре-энтри', 'secondary-action player-reentry', () => playerCommand(player.id, 'reenter'));
  if (actions.childElementCount) row.append(actions);
  return row;
}

// Сначала те, кто за столом, затем вылетевшие (их можно вернуть через re-entry), в конце окончательный аут.
function drawPlayers() {
  const players = root.querySelector('#players');
  players.replaceChildren();
  const playerCount = root.querySelector('#player-count');
  playerCount.textContent = state.status === 'draft' ? String(state.metrics.registered_players) : state.metrics.active_players + ' из ' + state.metrics.registered_players;
  playerCount.setAttribute('aria-label', 'Игроки в игре: ' + state.metrics.active_players + ' из ' + state.metrics.registered_players);
  const byPlace = (left, right) => (left.elimination_place || 0) - (right.elimination_place || 0);
  const groups = [
    ['За столом', state.players.filter(player => player.status === 'active' || player.status === 'registered')],
    ['Вылетели', state.players.filter(player => player.status === 'eliminated').sort(byPlace)],
    ['Аут', state.players.filter(player => player.status === 'out').sort(byPlace)],
  ].filter(([, items]) => items.length);
  groups.forEach(([label, items]) => {
    if (groups.length > 1) {
      const heading = document.createElement('p'); heading.className = 'player-group-label'; heading.textContent = label + ': ' + items.length;
      players.append(heading);
    }
    items.forEach(player => players.append(playerRow(player)));
  });
  if (!state.players.length) {
    const empty = document.createElement('p'); empty.className = 'create-empty'; empty.textContent = 'Игроков пока нет. Добавьте первого через поле выше.';
    players.append(empty);
  }
}

async function refresh() { const response = await fetch('/api/v1/tournaments/' + id + '/state'); draw(await response.json()); }
async function timer(action) { try { draw(await command('/api/v1/tournaments/' + id + '/timer', {action})); say(''); } catch (error) { say(error.message); } }
async function playerCommand(entry, action, allowWarnings = false) {
  const playerName = state.players.find(player => player.id === entry)?.name || 'Игрок';
  if (action === 'eliminate') {
    if (state.bounty_mode === 'fixed') {
      const killerOptions = state.players.filter(player => player.status === 'active' && player.id !== entry);
      const killer = await openDialog({
        tone: 'danger',
        eyebrow: 'Вылет: ' + playerName,
        title: 'Кто забирает баунти?',
        message: 'Выберите игрока, который сделал K.O.',
        confirmLabel: 'Подтвердить вылет',
        select: {label: 'Выбил', placeholder: 'Выберите игрока', options: killerOptions.map(player => ({value: String(player.id), label: player.name}))},
        icon: 'player',
      });
      if (killer === null) return;
      try { draw(await command('/api/v1/tournament-players/' + entry + '/eliminate', {killer_tournament_player_id: Number(killer)})); say(''); }
      catch (error) { say(error.message); }
      return;
    }
    const confirmed = await openDialog({
      tone: 'danger',
      eyebrow: playerName,
      title: 'Отметить вылет?',
      message: 'Игрок попадёт в список вылетевших. Потом можно оформить re-entry или окончательный аут.',
      confirmLabel: 'Вылет',
      icon: 'player',
    });
    if (!confirmed) return;
  }
  if (action === 'out') {
    const confirmed = await openDialog({
      tone: 'danger',
      eyebrow: 'Окончательный аут',
      title: 'Зафиксировать аут?',
      message: playerName + ' останется в истории и итогах турнира, но больше не будет участвовать в игре.',
      confirmLabel: 'Перевести в аут',
      icon: 'player',
    });
    if (!confirmed) return;
  }
  try {
    const result = await command('/api/v1/tournament-players/' + entry + '/' + action, action === 'reenter' ? {allow_warnings: allowWarnings} : {});
    draw(result);
    say('');
  } catch (error) {
    if (action === 'reenter' && ['reentry_warning', 'late_registration_warning'].includes(error.code) && !allowWarnings) {
      const lateRegistration = error.code === 'late_registration_warning';
      const confirmed = await openDialog({
        tone: 'warning',
        eyebrow: lateRegistration ? 'Поздняя регистрация завершена' : 'Ограничение re-entry',
        title: lateRegistration ? 'Всё равно оформить re-entry?' : 'Всё равно вернуть игрока?',
        message: error.message.replace(/\s*Продолжить re-entry\?\s*$/i, ''),
        confirmLabel: lateRegistration ? 'Оформить re-entry' : 'Всё равно вернуть',
        icon: 'reentry',
      });
      if (confirmed) return playerCommand(entry, action, true);
      return;
    }
    say(error.message);
  }
}

root.querySelectorAll('[data-action]').forEach(button => { button.onclick = () => timer(button.dataset.action); });
root.querySelector('#undo').onclick = async () => {
  const confirmed = await openDialog({
    tone: 'warning',
    eyebrow: 'Журнал действий',
    title: 'Отменить последнее действие?',
    message: 'Если последним был «Аут», первая отмена вернёт игрока в список вылетевших. Нажмите отмену ещё раз, чтобы снять «Вылет» и вернуть его в игру без re-entry. Каждая отмена останется в журнале.',
    confirmLabel: 'Отменить действие',
    icon: 'undo',
  });
  if (!confirmed) return;
  try { draw(await command('/api/v1/tournaments/' + id + '/undo', {})); say(''); }
  catch (error) { say(error.message); }
};
root.querySelector('#finish-tournament').onclick = async () => {
  const pin = await openDialog({
    tone: 'danger',
    eyebrow: 'Опасное действие',
    title: 'Завершить турнир?',
    message: 'После подтверждения нельзя будет менять таймер, структуру или игроков. Итоговые места останутся доступны на табло и в админке.',
    confirmLabel: 'Завершить турнир',
    pin: true,
    icon: 'finish',
  });
  if (pin === null) return;
  try { draw(await command('/api/v1/tournaments/' + id + '/finish', {pin})); say(''); }
  catch (error) {
    say(error.message);
    await showNotice({
      tone: 'danger',
      eyebrow: 'Подтверждение не выполнено',
      title: 'Не удалось завершить турнир',
      message: error.message,
    });
  }
};
root.querySelector('#player-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const addPlayer = async allowWarnings => {
    try {
      const result = await command('/api/v1/tournaments/' + id + '/players', {
        name: new FormData(form).get('name'),
        allow_warnings: allowWarnings,
      });
      form.reset();
      draw(result);
      say('');
    } catch (error) {
      if (error.code === 'late_registration_warning' && !allowWarnings) {
        const confirmed = await openDialog({
          tone: 'warning',
          eyebrow: 'Поздняя регистрация завершена',
          title: 'Всё равно добавить игрока?',
          message: error.message.replace(/\s*Всё равно добавить игрока\?\s*$/i, ''),
          confirmLabel: 'Добавить игрока',
          icon: 'player',
        });
        if (confirmed) await addPlayer(true);
        return;
      }
      say(error.message);
    }
  };
  await addPlayer(false);
};
document.querySelector('.global-nav a[href="/"]')?.addEventListener('click', event => {
  if (!structureDirty && !payoutDirty) return;
  event.preventDefault();
  showNotice({
    tone: 'warning',
    eyebrow: 'Несохранённые изменения',
    title: 'Сначала сохраните изменения',
    message: payoutDirty
      ? 'Изменения выплат ещё не записаны. Нажмите «Сохранить выплаты», затем вернитесь на главную.'
      : 'Изменения уровней ещё не записаны. Нажмите «Сохранить структуру», затем вернитесь на главную.',
  });
});
root.querySelector('#edit-structure').onclick = () => { root.querySelector('#structure-editor').hidden = false; root.querySelector('#edit-structure').hidden = true; };
root.querySelector('#edit-payouts').onclick = () => {
  root.querySelector('#payout-editor').hidden = false;
  root.querySelector('#edit-payouts').hidden = true;
};
root.querySelector('#late-registration-end').addEventListener('input', markStructureDirty);
root.querySelector('#late-registration-end').addEventListener('input', () => validateLateRegistrationEnd());
root.querySelector('#admin-add-payout').onclick = () => {
  const next = readAdminPayouts(); next.push(1); payoutDirty = true; renderAdminPayoutEditor(next);
};
root.querySelector('#save-payouts').onclick = async () => {
  if (!updateAdminPayoutTotal()) { say('Сумма выплат должна составлять ровно 100%.'); return; }
  try {
    const result = await command('/api/v1/tournaments/' + id + '/payouts', {percentages: readAdminPayouts()});
    payoutDirty = false;
    draw(result);
    root.querySelector('#payout-editor').hidden = true;
    root.querySelector('#edit-payouts').hidden = false;
    say('');
  } catch (error) { say(error.message); }
};
root.querySelector('#add-play').onclick = () => { structureEditor().append(levelRow({kind: 'play', small_blind: 100, big_blind: 200, ante: 200, duration_seconds: 1500})); markStructureDirty(); renumberLevels(); };
root.querySelector('#add-break').onclick = () => { structureEditor().append(levelRow({kind: 'break', duration_seconds: 900, title: 'Перерыв'})); markStructureDirty(); renumberLevels(); };
root.querySelector('#save-levels').onclick = async () => {
  const cutoff = validateLateRegistrationEnd(true);
  if (cutoff === null) return;
  try {
    const levels = [...root.querySelectorAll('.level-edit')].map(row => {
      const value = field => row.querySelector('[data-field="' + field + '"]')?.value;
      const minutes = Number(value('minutes'));
      if (row.dataset.kind === 'break') return {kind: 'break', duration_seconds: minutes * 60, title: 'Перерыв'};
      return {
        kind: 'play',
        small_blind: Number(value('sb')),
        big_blind: Number(value('bb')),
        ante: Number(value('ante') || 0),
        duration_seconds: minutes * 60,
      };
    });
    draw(await command('/api/v1/tournaments/' + id + '/levels', {levels, late_registration_end_level_number: cutoff}));
    structureDirty = false;
    say('');
    root.querySelector('#structure-editor').hidden = true;
    root.querySelector('#edit-structure').hidden = false;
  } catch (error) { say(error.message); }
};

connectTournament(id, draw, text => { online = text === 'Онлайн'; renderConnection(); });
setInterval(() => {
  if (state?.timer_status !== 'running') return;
  state.remaining_seconds = Math.max(0, state.remaining_seconds - 1);
  root.querySelector('#time').textContent = clock(state.remaining_seconds);
  root.querySelector('#dock-time').textContent = clock(state.remaining_seconds);
}, 1000);

// Когда большой пульт уходит за верх экрана, сверху появляется короткая панель с часами и паузой.
const dock = root.querySelector('#admin-dock');
if ('IntersectionObserver' in window) {
  new IntersectionObserver(([entry]) => {
    const visible = !entry.isIntersecting && entry.boundingClientRect.top < 0;
    dock.classList.toggle('is-visible', visible);
    dock.setAttribute('aria-hidden', String(!visible));
    dock.querySelector('button').tabIndex = visible ? 0 : -1;
  }, {threshold: 0}).observe(root.querySelector('#timer-toggle'));
}

fetch('/api/v1/tournaments/' + id + '/session')
  .then(response => response.ok ? response.json() : null)
  .then(session => {
    if (session && !session.authenticated) { location.href = '/login/' + id; return; }
    authenticated = true;
    if (state) loadEvents();
  })
  .catch(() => {});
