import {initStackOptimizer} from './stack-optimizer.js?v=20261028-1';
import {initStructureGenerator} from './structure-generator.js?v=20261028-1';
import {initAutoTournamentBuilder} from './auto-tournament-builder.js?v=20261028-1';

const svgIcon = name => '<svg class="icon" aria-hidden="true"><use href="#i-' + name + '"/></svg>';
import {openDialog} from './dialog.js?v=20261028-1';

const form = document.querySelector('#new-tournament');
const error = document.querySelector('#error');
const presetSelect = document.querySelector('#preset');
const editor = document.querySelector('#create-level-editor');
const playerInput = document.querySelector('#player-name');
const playerList = document.querySelector('#create-player-list');
const total = document.querySelector('#structure-total');
const freeroll = form.querySelector('[name="is_freeroll"]');
const freerollField = freeroll.closest('.freeroll-toggle');
const buyIn = form.querySelector('[name="buy_in_amount"]');
const bountyModes = [...form.querySelectorAll('[name="bounty_mode"]')];
const bountyField = form.querySelector('#bounty-field');
const bountyAmount = form.querySelector('[name="bounty_amount"]');
const bountyPreview = form.querySelector('#bounty-preview');
const noAnte = form.querySelector('#no-ante');
const lateRegistrationEnd = form.querySelector('#late-registration-end');
const createPage = document.querySelector('.create-page');
const payoutPanel = document.querySelector('#create-payout-panel');
const payoutList = document.querySelector('#create-payout-list');
let payoutPercentages = [50, 30, 20];
let presets = {};
let playerNames = [];
let draggedRow;
let dropTarget;
let dropPosition;
let appliedChipPlan = null;
let appliedChipPlanSignature = null;
let appliedChipPlanDenominations = [];
let appliedGeneratorSignature = null;
let appliedAutoSignature = null;
let appliedAutoContext = null;
let approvedAutoRegenerationSignature = null;
let autoDiagnosticsTimer = null;

function optimizerInputs() {
  const firstLevel = readLevels().find(level => level.kind === 'play') || {};
  const reentry = form.querySelector('[name="max_reentries_per_player"]').value;
  return {
    players: playerNames.length,
    starting_stack: form.querySelector('[name="starting_stack"]').value,
    max_reentries_per_player: reentry,
    first_small_blind: firstLevel.small_blind ?? '',
    first_big_blind: firstLevel.big_blind ?? '',
    first_ante: noAnte.checked ? 0 : (firstLevel.ante ?? ''),
  };
}

const optimizerSignature = (plannedPlayers = playerNames.length) => JSON.stringify({
  players: plannedPlayers,
  starting_stack: form.querySelector('[name="starting_stack"]').value,
  max_reentries_per_player: form.querySelector('[name="max_reentries_per_player"]').value,
});
const structureSignature = () => JSON.stringify(readLevels());

function autoBuilderInputs() {
  return {
    players: playerNames.length || 8,
    max_reentries_per_player: form.querySelector('[name="max_reentries_per_player"]').value || 2,
    target_duration_minutes: appliedAutoContext?.target_duration_minutes || 300,
    ante_mode: noAnte.checked ? 'none' : 'big_blind',
  };
}

const formatDraftDuration = seconds => {
  const value = Math.round(Number(seconds || 0) / 60);
  return '~' + Math.floor(value / 60) + ':' + String(value % 60).padStart(2, '0');
};

async function refreshAutoDraftDiagnostics() {
  if (!appliedAutoContext) return;
  const box = document.querySelector('#auto-draft-diagnostics');
  try {
    const response = await fetch('/api/v1/auto-tournament-builder/diagnostics', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({...appliedAutoContext, levels: readLevels()}),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail?.message || 'Не удалось обновить диагностику структуры.');
    const summary = body.summary;
    const window = summary.finish_window;
    box.replaceChildren(); box.hidden = false;
    const heading = document.createElement('strong'); heading.textContent = 'Информационный пересчёт';
    const estimate = document.createElement('p');
    estimate.textContent = 'Ориентировочное окно теперь ' + formatDraftDuration(window.from_seconds) + '–' + formatDraftDuration(window.to_seconds).slice(1) + '. Структура не изменена.';
    box.append(heading, estimate);
    body.diagnostics.forEach(item => {
      const note = document.createElement('p'); note.className = 'structure-diagnostic ' + item.severity; note.textContent = item.message; box.append(note);
    });
  } catch (diagnosticError) {
    box.hidden = false; box.textContent = diagnosticError.message;
  }
}

function markStructureEdited() {
  if (!appliedAutoContext) return;
  document.querySelector('#open-auto-tournament-builder').textContent = 'Сгенерировать заново';
  clearTimeout(autoDiagnosticsTimer);
  autoDiagnosticsTimer = setTimeout(refreshAutoDraftDiagnostics, 350);
}

function structureGeneratorInputs() {
  const firstLevel = readLevels().find(level => level.kind === 'play') || {};
  return {
    players: playerNames.length || undefined,
    starting_stack: form.querySelector('[name="starting_stack"]').value,
    max_reentries_per_player: form.querySelector('[name="max_reentries_per_player"]').value,
    first_small_blind: firstLevel.small_blind,
    first_big_blind: firstLevel.big_blind,
    level_duration_minutes: minutes(firstLevel.duration_seconds),
    ante_mode: noAnte.checked ? 'none' : 'big_blind',
    chip_denominations: appliedChipPlanDenominations,
  };
}

function updateFreeroll() {
  buyIn.disabled = freeroll.checked;
  if (freeroll.checked) buyIn.value = '0';
  else if (buyIn.value === '0') buyIn.value = '1000';
  payoutPanel.hidden = freeroll.checked;
  payoutPanel.querySelectorAll('input, button').forEach(control => { control.disabled = freeroll.checked; });
  bountyModes.forEach(control => { control.disabled = freeroll.checked; });
  if (freeroll.checked) bountyModes[0].checked = true;
  updateBounty();
}

function updateBounty() {
  const fixed = !freeroll.checked && form.querySelector('[name="bounty_mode"]:checked')?.value === 'fixed';
  freerollField.hidden = fixed;
  freeroll.disabled = fixed;
  bountyField.hidden = !fixed;
  bountyAmount.disabled = !fixed;
  if (!fixed) return true;
  const buyInValue = Number(buyIn.value);
  const bountyValue = Number(bountyAmount.value);
  const valid = Number.isInteger(buyInValue) && Number.isInteger(bountyValue) && bountyValue > 0 && bountyValue < buyInValue;
  bountyAmount.setCustomValidity(valid ? '' : 'Баунти должен быть больше нуля и меньше общего бай-ина.');
  bountyPreview.textContent = valid
    ? (buyInValue - bountyValue).toLocaleString('ru-RU') + ' ₽ в основной призовой фонд, ' + bountyValue.toLocaleString('ru-RU') + ' ₽ баунти за вход'
    : 'Баунти должен быть меньше общего бай-ина.';
  return valid;
}

const minutes = seconds => Math.max(1, Math.round(Number(seconds || 0) / 60));
const showError = text => { error.textContent = text || ''; };

function payoutBasisPoints(value) {
  const text = String(value).trim();
  if (!/^\d+(?:[.,]\d{1,2})?$/.test(text)) return null;
  return Math.round(Number(text.replace(',', '.')) * 100);
}

function updatePayoutTotal() {
  const values = [...payoutList.querySelectorAll('input')].map(input => payoutBasisPoints(input.value));
  const valid = values.every(value => value !== null && value > 0);
  const totalBasisPoints = valid ? values.reduce((sum, value) => sum + value, 0) : 0;
  const totalLabel = document.querySelector('#create-payout-total');
  totalLabel.textContent = valid ? (totalBasisPoints / 100).toLocaleString('ru-RU') + '%' : '—';
  totalLabel.classList.toggle('is-invalid', !valid || totalBasisPoints !== 10000);
  document.querySelector('#create-payout-error').textContent = !valid
    ? 'Укажите положительный процент с точностью не более 0,01%.'
    : totalBasisPoints === 10000 ? '' : 'Сумма должна составлять ровно 100%.';
  return valid && totalBasisPoints === 10000;
}

function readPayoutPercentages() {
  return [...payoutList.querySelectorAll('input')].map(input => Number(input.value.replace(',', '.')));
}

function renderPayouts() {
  payoutList.replaceChildren();
  payoutPercentages.forEach((percentage, index) => {
    const row = document.createElement('div');
    row.className = 'payout-edit-row';
    const place = document.createElement('strong');
    place.textContent = (index + 1) + ' место';
    const field = document.createElement('label');
    field.className = 'payout-percentage-field';
    const input = document.createElement('input');
    input.type = 'number'; input.inputMode = 'decimal'; input.min = '0.01'; input.max = '100'; input.step = '0.01'; input.value = String(percentage);
    input.setAttribute('aria-label', 'Процент для ' + (index + 1) + ' места');
    const suffix = document.createElement('span'); suffix.textContent = '%';
    input.addEventListener('input', updatePayoutTotal);
    field.append(input, suffix);
    const remove = document.createElement('button');
    remove.type = 'button'; remove.className = 'secondary-action payout-remove'; remove.innerHTML = svgIcon('trash'); remove.title = 'Убрать ' + (index + 1) + ' место'; remove.setAttribute('aria-label', remove.title);
    remove.disabled = payoutPercentages.length === 1;
    remove.onclick = () => {
      payoutPercentages = readPayoutPercentages();
      payoutPercentages.splice(index, 1);
      renderPayouts();
    };
    row.append(place, field, remove);
    payoutList.append(row);
  });
  updatePayoutTotal();
  updateFreeroll();
}

function updateTotal() {
  const rows = [...editor.querySelectorAll('.level-edit')];
  const value = rows.flatMap(row => [...row.querySelectorAll('[data-field="minutes"]')])
    .reduce((sum, input) => sum + Number(input.value || 0), 0);
  document.querySelector('#level-count').textContent = String(rows.length);
  total.textContent = String(Math.floor(value / 60)).padStart(2, '0') + ':' + String(value % 60).padStart(2, '0');
}

function validateLateRegistrationEnd(report = false) {
  const playLevels = editor.querySelectorAll('.level-edit[data-kind="play"]').length;
  lateRegistrationEnd.max = String(playLevels);
  const value = Number(lateRegistrationEnd.value);
  const valid = lateRegistrationEnd.value !== '' && Number.isInteger(value) && value >= 1 && value <= playLevels;
  lateRegistrationEnd.setCustomValidity(valid ? '' : 'Укажите номер существующего игрового уровня.');
  if (!valid && report) {
    lateRegistrationEnd.reportValidity();
    lateRegistrationEnd.scrollIntoView({behavior: 'smooth', block: 'center'});
    lateRegistrationEnd.focus({preventScroll: true});
  }
  return valid ? value : null;
}

function renumber() {
  let number = 0;
  editor.querySelectorAll('.level-edit').forEach(row => {
    const isBreak = row.dataset.kind === 'break';
    if (!isBreak) number += 1;
    const numberLabel = row.querySelector('.level-number');
    numberLabel.textContent = isBreak ? '' : String(number);
    numberLabel.hidden = isBreak;
    const kind = row.querySelector('.level-kind');
    kind.textContent = isBreak ? 'Перерыв' : '';
    kind.hidden = !isBreak;
  });
  updateTotal();
  validateLateRegistrationEnd();
}

function moveRow(row, direction) {
  const sibling = direction < 0 ? row.previousElementSibling : row.nextElementSibling;
  if (!sibling) return;
  if (direction < 0) editor.insertBefore(row, sibling);
  else editor.insertBefore(sibling, row);
  renumber();
  markStructureEdited();
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

function bindDrag(row, handle) {
  handle.draggable = true;
  handle.addEventListener('dragstart', event => {
    draggedRow = row;
    row.classList.add('dragging');
    editor.classList.add('is-dragging');
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
    editor.insertBefore(draggedRow, dropPosition === 'before' ? row : row.nextElementSibling);
    const movedRow = draggedRow;
    clearDropTarget();
    movedRow.classList.add('just-dropped');
    setTimeout(() => movedRow.classList.remove('just-dropped'), 480);
    renumber();
    markStructureEdited();
  });
  handle.addEventListener('dragend', () => {
    clearDropTarget();
    editor.classList.remove('is-dragging');
    row.classList.remove('dragging');
    draggedRow = undefined;
    renumber();
  });
}

function addField(container, field, label, value, min = 0) {
  const wrapper = document.createElement('label');
  const caption = document.createElement('span'); caption.className = 'level-field-label'; caption.textContent = label; wrapper.append(caption);
  const input = document.createElement('input');
  input.type = 'number'; input.inputMode = 'numeric'; input.min = String(min); input.value = String(value ?? ''); input.dataset.field = field;
  wrapper.append(input); container.append(wrapper);
}

function createLevelRow(level) {
  const row = document.createElement('article');
  row.className = 'level-edit'; row.dataset.kind = level.kind;
  row.dataset.ante = String(level.ante ?? level.big_blind ?? 0);
  const heading = document.createElement('header'); heading.className = 'level-edit-head';
  const handle = document.createElement('span');
  handle.className = 'drag-handle'; handle.innerHTML = svgIcon('grip'); handle.title = 'Перетащить уровень'; handle.setAttribute('aria-hidden', 'true');
  const number = document.createElement('strong'); number.className = 'level-number';
  const kind = document.createElement('span'); kind.className = 'level-kind';
  heading.append(handle, number, kind);
  const fields = document.createElement('div'); fields.className = 'level-fields';
  addField(fields, 'minutes', 'Минуты', minutes(level.duration_seconds), 1);
  if (level.kind === 'play') {
    addField(fields, 'sb', 'SB', level.small_blind, 1);
    addField(fields, 'bb', 'BB', level.big_blind, 1);
    if (!noAnte.checked) addField(fields, 'ante', 'Ante', row.dataset.ante, 0);
  }
  const ordering = document.createElement('div'); ordering.className = 'level-order';
  const move = (direction, label, title) => {
    const button = document.createElement('button');
    button.type = 'button'; button.dataset.move = direction; button.innerHTML = svgIcon(label); button.title = title; button.setAttribute('aria-label', title); button.onclick = () => moveRow(row, direction === 'up' ? -1 : 1);
    ordering.append(button);
  };
  move('up', 'up', 'Переместить выше');
  move('down', 'down', 'Переместить ниже');
  const remove = document.createElement('button');
  remove.type = 'button'; remove.className = 'remove-level'; remove.innerHTML = svgIcon('trash'); remove.title = 'Удалить строку'; remove.setAttribute('aria-label', 'Удалить строку');
  remove.onclick = () => { if (editor.querySelectorAll('.level-edit').length > 1) { row.remove(); renumber(); markStructureEdited(); } else showError('Нужен хотя бы один уровень.'); };
  ordering.append(remove);
  row.append(heading, fields, ordering);
  row.addEventListener('input', event => {
    if (event.target.dataset.field === 'ante') row.dataset.ante = event.target.value;
    updateTotal();
    markStructureEdited();
  });
  bindDrag(row, handle);
  return row;
}

function renderLevels(levels) {
  editor.innerHTML = '';
  levels.forEach(level => editor.append(createLevelRow({...level})));
  renumber();
}

function addLevel(kind) {
  const lastPlay = [...editor.querySelectorAll('.level-edit')].reverse().find(row => row.dataset.kind === 'play');
  const bb = Number(lastPlay?.querySelector('[data-field="bb"]')?.value || 200);
  const level = kind === 'break'
    ? {kind, duration_seconds: 900}
    : {kind, duration_seconds: 1500, small_blind: bb, big_blind: bb * 2, ante: bb * 2};
  editor.append(createLevelRow(level)); renumber();
  markStructureEdited();
}

function renderPlayers() {
  playerList.innerHTML = '';
  if (!playerNames.length) { playerList.innerHTML = '<p class="create-empty">Игроки пока не добавлены.</p>'; return; }
  playerNames.forEach((name, index) => {
    const row = document.createElement('div'); row.className = 'create-player-row';
    const label = document.createElement('span'); label.textContent = name;
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary-action'; remove.innerHTML = svgIcon('close'); remove.title = 'Убрать ' + name; remove.setAttribute('aria-label', 'Убрать ' + name);
    remove.onclick = () => { playerNames.splice(index, 1); renderPlayers(); };
    row.append(label, remove); playerList.append(row);
  });
}

function readLevels() {
  return [...editor.querySelectorAll('.level-edit')].map(row => {
    const value = field => row.querySelector('[data-field="' + field + '"]')?.value;
    const duration = Number(value('minutes')) * 60;
    if (row.dataset.kind === 'break') return {kind: 'break', duration_seconds: duration};
    return {kind: 'play', duration_seconds: duration, small_blind: Number(value('sb')), big_blind: Number(value('bb')), ante: Number(value('ante') ?? row.dataset.ante ?? 0)};
  });
}

function selectPreset() {
  const levels = presets[presetSelect.value];
  if (!levels) { showError('Типовая структура ещё загружается.'); return; }
  showError('');
  renderLevels(levels);
  markStructureEdited();
}
presetSelect.addEventListener('change', selectPreset);
presetSelect.addEventListener('input', selectPreset);
document.querySelector('#add-play').onclick = () => addLevel('play');
document.querySelector('#add-break').onclick = () => addLevel('break');
document.querySelector('#add-payout-place').onclick = () => {
  payoutPercentages = readPayoutPercentages();
  payoutPercentages.push(1);
  renderPayouts();
};
document.querySelector('#add-player').onclick = () => {
  const name = playerInput.value.trim();
  if (!name) return;
  if (playerNames.some(item => item.toLocaleLowerCase() === name.toLocaleLowerCase())) { showError('Такой игрок уже добавлен.'); return; }
  playerNames.push(name); playerInput.value = ''; showError(''); renderPlayers(); playerInput.focus();
};
freeroll.addEventListener('change', updateFreeroll);
bountyModes.forEach(control => control.addEventListener('change', updateBounty));
buyIn.addEventListener('input', updateBounty);
bountyAmount.addEventListener('input', updateBounty);
noAnte.addEventListener('change', () => {
  const levels = readLevels();
  createPage.classList.toggle('structure-no-ante', noAnte.checked);
  renderLevels(levels);
  markStructureEdited();
});
playerInput.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); document.querySelector('#add-player').click(); } });
lateRegistrationEnd.addEventListener('input', () => validateLateRegistrationEnd());

form.addEventListener('submit', async event => {
  event.preventDefault(); showError('');
  const cutoff = validateLateRegistrationEnd(true);
  if (cutoff === null) return;
  if (!updateBounty()) { bountyAmount.reportValidity(); return; }
  if (appliedChipPlan && appliedChipPlanSignature !== optimizerSignature()) {
    showError('Параметры турнира изменились после подбора фишек. Рассчитайте план повторно.');
    document.querySelector('#open-stack-optimizer').scrollIntoView({behavior: 'smooth', block: 'center'});
    return;
  }
  const submit = form.querySelector('.create-submit'); submit.disabled = true;
  const data = Object.fromEntries(new FormData(form));
  data.is_freeroll = freeroll.checked;
  data.bounty_mode = freeroll.checked ? 'none' : form.querySelector('[name="bounty_mode"]:checked').value;
  data.bounty_amount = data.bounty_mode === 'fixed' ? Number(bountyAmount.value) : 0;
  data.ante_enabled = !noAnte.checked;
  data.max_reentries_per_player = data.max_reentries_per_player === '' ? null : Number(data.max_reentries_per_player);
  data.late_registration_end_level_number = cutoff;
  if (!freeroll.checked && !updatePayoutTotal()) {
    showError('Проверьте распределение призового фонда.');
    submit.disabled = false;
    payoutPanel.scrollIntoView({behavior: 'smooth', block: 'center'});
    return;
  }
  data.payout_percentages = freeroll.checked ? null : readPayoutPercentages();
  data.levels = readLevels(); data.players = playerNames;
  data.chip_plan = appliedChipPlan;
  try {
    const response = await fetch('/api/v1/tournaments', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
    if (!response.ok) { const body = await response.json(); throw new Error(body.detail?.message || 'Не удалось создать турнир.'); }
    const result = await response.json(); window.location.href = '/display/' + result.id;
  } catch (requestError) {
    showError(requestError.message); submit.disabled = false;
  }
});

renderPlayers();
renderPayouts();
updateFreeroll();
createPage.classList.toggle('structure-no-ante', noAnte.checked);
const optimizerDialog = document.querySelector('#create-stack-optimizer');
const optimizer = initStackOptimizer(optimizerDialog.querySelector('[data-stack-optimizer]'), {
  inputProvider: optimizerInputs,
  lockInputs: true,
  async onApply(selection) {
    appliedChipPlan = {
      chip_set_ids: selection.chip_set_ids,
      excluded_denominations: selection.excluded_denominations,
      initial_distribution: selection.initial_distribution,
    };
    appliedChipPlanSignature = optimizerSignature();
    const candidate = selection.candidate;
    appliedChipPlanDenominations = [...new Set([
      ...selection.initial_distribution,
      ...candidate.reentry_pack,
    ].filter(item => item.quantity > 0).map(item => item.value))].sort((left, right) => left - right);
    document.querySelector('#create-chip-plan-summary').textContent = candidate.label + ': ' + candidate.covered_reentries + ' / ' + candidate.max_allowed_reentries + ' re-entry обеспечено. Наборы фишек не меняются.';
    optimizerDialog.close();
    if (appliedAutoContext) {
      appliedAutoContext.chip_denominations = appliedChipPlanDenominations;
      markStructureEdited();
      const recalculate = await openDialog({
        tone: 'warning',
        eyebrow: 'Новый план фишек',
        title: 'Пересчитать структуру?',
        message: 'Новый план фишек может изменить совместимость текущей структуры. Текущие уровни не будут изменены без отдельного применения.',
        confirmLabel: 'Открыть генератор',
      });
      if (recalculate) structureGenerator.open();
    }
  },
});
document.querySelector('#open-stack-optimizer').addEventListener('click', () => optimizer.open());
const structureGeneratorDialog = document.querySelector('#create-structure-generator');
const structureGenerator = initStructureGenerator(structureGeneratorDialog.querySelector('[data-structure-generator]'), {
  inputProvider: structureGeneratorInputs,
  async beforeGenerate() {
    if (!appliedGeneratorSignature || appliedGeneratorSignature === structureSignature()) return true;
    return Boolean(await openDialog({
      tone: 'warning',
      eyebrow: 'Ручные изменения',
      title: 'Сгенерировать заново?',
      message: 'Текущая структура была изменена вручную. Новый расчёт создаст другой preview; редактор изменится только после отдельного применения.',
      confirmLabel: 'Сгенерировать заново',
    }));
  },
  onApply(result, payload) {
    noAnte.checked = payload.ante_mode === 'none';
    createPage.classList.toggle('structure-no-ante', noAnte.checked);
    renderLevels(result.levels);
    appliedGeneratorSignature = structureSignature();
    if (appliedAutoContext) {
      appliedAutoContext.target_duration_minutes = payload.target_duration_minutes;
      appliedAutoContext.expected_reentries = payload.expected_reentries;
      appliedAutoSignature = structureSignature();
      refreshAutoDraftDiagnostics();
    }
    const summary = result.summary;
    document.querySelector('#create-structure-generator-summary').textContent = 'Цель ' + Math.round(summary.target_duration_seconds / 60) + ' мин, окончание на уровнях ' + summary.finish_window.from_level + '-' + summary.finish_window.to_level + ', запас ' + summary.extension_levels + ' уровня.';
    const lateRegistrationLevel = Number(lateRegistrationEnd.value);
    const playCount = readLevels().filter(level => level.kind === 'play').length;
    if (lateRegistrationEnd.value !== '' && lateRegistrationLevel > playCount) {
      showError('Уровень окончания поздней регистрации отсутствует в новой структуре. Выберите существующий игровой уровень.');
    } else {
      showError('');
    }
    structureGeneratorDialog.close();
  },
});
document.querySelector('#open-structure-generator').addEventListener('click', () => structureGenerator.open());
const autoBuilderDialog = document.querySelector('#create-auto-tournament-builder');
const autoBuilder = initAutoTournamentBuilder(autoBuilderDialog.querySelector('[data-auto-tournament-builder]'), {
  inputProvider: autoBuilderInputs,
  async beforeGenerate() {
    if (!appliedAutoSignature || appliedAutoSignature === structureSignature()) return true;
    const currentSignature = structureSignature();
    const confirmed = Boolean(await openDialog({
      tone: 'warning',
      eyebrow: 'Ручные изменения',
      title: 'Сгенерировать заново?',
      message: 'Текущие ручные изменения структуры будут заменены новым автоматически рассчитанным вариантом после его применения.',
      confirmLabel: 'Пересчитать',
    }));
    if (confirmed) approvedAutoRegenerationSignature = currentSignature;
    return confirmed;
  },
  async beforeApply() {
    if (!appliedAutoSignature || appliedAutoSignature === structureSignature() || approvedAutoRegenerationSignature === structureSignature()) return true;
    return Boolean(await openDialog({
      tone: 'warning',
      eyebrow: 'Ручные изменения',
      title: 'Заменить текущую структуру?',
      message: 'Текущие ручные изменения структуры будут заменены новым автоматически рассчитанным вариантом.',
      confirmLabel: 'Пересчитать',
    }));
  },
  onApply(plan) {
    form.querySelector('[name="starting_stack"]').value = String(plan.starting_stack);
    form.querySelector('[name="max_reentries_per_player"]').value = String(plan.max_reentries_per_player);
    noAnte.checked = plan.ante_mode === 'none';
    createPage.classList.toggle('structure-no-ante', noAnte.checked);
    appliedChipPlan = plan.chip_plan;
    appliedChipPlanDenominations = [...plan.structure_denominations];
    renderLevels(plan.levels);
    appliedChipPlanSignature = optimizerSignature(plan.players);
    appliedGeneratorSignature = structureSignature();
    appliedAutoSignature = structureSignature();
    approvedAutoRegenerationSignature = null;
    appliedAutoContext = {
      players: plan.players,
      starting_stack: plan.starting_stack,
      expected_reentries: plan.expected_reentries,
      target_duration_minutes: plan.target_duration_minutes,
      chip_denominations: appliedChipPlanDenominations,
    };
    document.querySelector('#create-chip-plan-summary').textContent = plan.label + ': ' + plan.reentry_coverage.covered + ' / ' + plan.reentry_coverage.maximum + ' re-entry обеспечено. Наборы фишек не меняются.';
    document.querySelector('#create-structure-generator-summary').textContent = 'Автоподбор: стек ' + plan.starting_stack.toLocaleString('ru-RU') + ', первый уровень ' + plan.first_small_blind.toLocaleString('ru-RU') + ' / ' + plan.first_big_blind.toLocaleString('ru-RU') + ', уровни по ' + plan.level_duration_minutes + ' мин, ориентировочно ' + formatDraftDuration(plan.finish_window.from_seconds) + '–' + formatDraftDuration(plan.finish_window.to_seconds).slice(1) + '.';
    document.querySelector('#open-auto-tournament-builder').textContent = 'Сгенерировать заново';
    autoBuilderDialog.close();
    refreshAutoDraftDiagnostics();
    document.querySelector('#create-level-editor').scrollIntoView({behavior: 'smooth', block: 'start'});
  },
});
document.querySelector('#open-auto-tournament-builder').addEventListener('click', () => autoBuilder.open());
fetch('/api/v1/structure-presets')
  .then(response => { if (!response.ok) throw new Error('Не удалось загрузить типовые структуры.'); return response.json(); })
  .then(data => { presets = data; selectPreset(); })
  .catch(requestError => showError(requestError.message));
