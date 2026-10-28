const formatNumber = value => new Intl.NumberFormat('ru-RU').format(Number(value || 0));

const make = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const formatDuration = seconds => {
  const totalMinutes = Math.round(Number(seconds || 0) / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return '~' + hours + ':' + String(minutes).padStart(2, '0');
};

async function request(url, options = {}) {
  const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options});
  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const body = isJson ? await response.json() : null;
  if (!response.ok) {
    const fallback = response.status === 404
      ? 'Генератор ещё не загружен сервером. Перезапустите Home Poker и повторите расчёт.'
      : 'Не удалось сгенерировать структуру.';
    throw new Error(body?.detail?.message || fallback);
  }
  if (!isJson) throw new Error('Сервер вернул неожиданный ответ. Перезапустите Home Poker и повторите расчёт.');
  return body;
}

function parseDenominations(value) {
  const text = String(value || '').trim();
  if (!text) return [];
  const values = text.split(/[\s,;]+/).filter(Boolean).map(Number);
  if (values.some(value => !Number.isInteger(value) || value <= 0)) {
    throw new Error('Укажите положительные целые номиналы через запятую.');
  }
  return [...new Set(values)].sort((left, right) => left - right);
}

export function initStructureGenerator(root, options = {}) {
  const fields = Object.fromEntries([...root.querySelectorAll('[data-field]')].map(input => [input.dataset.field, input]));
  const resultBox = root.querySelector('[data-role="result"]');
  const summaryBox = root.querySelector('[data-role="summary"]');
  const diagnosticsBox = root.querySelector('[data-role="diagnostics"]');
  const levelsBox = root.querySelector('[data-role="levels"]');
  const error = root.querySelector('[data-role="error"]');
  const generateButton = root.querySelector('[data-action="generate"]');
  const applyButton = root.querySelector('[data-action="apply"]');
  const chipContext = root.querySelector('[data-role="chip-context"]');
  const manualAnte = root.querySelector('[data-role="manual-ante-level"]');
  let latestResult = null;
  let latestPayload = null;

  function updateChipContext() {
    const denominations = fields.chip_denominations.value.trim();
    chipContext.textContent = denominations
      ? 'Структура будет проверена по указанным физическим номиналам.'
      : 'Без номиналов используется универсальная poker-friendly ladder.';
  }

  function updateConditionalFields() {
    const bba = fields.ante_mode.value === 'big_blind';
    fields.ante_start_mode.disabled = !bba;
    manualAnte.hidden = !bba || fields.ante_start_mode.value !== 'manual';
    fields.ante_start_level.disabled = manualAnte.hidden;
    const breaksEnabled = Number(fields.break_every_levels.value) > 0;
    fields.break_duration_minutes.disabled = !breaksEnabled;
  }

  function fillInputs(values) {
    if (!values) return;
    Object.entries(values).forEach(([name, value]) => {
      if (!fields[name] || value === undefined) return;
      fields[name].value = Array.isArray(value) ? value.join(', ') : (value ?? '');
    });
    updateConditionalFields();
    updateChipContext();
  }

  function payload() {
    updateConditionalFields();
    for (const input of Object.values(fields)) {
      if (!input.disabled && !input.checkValidity()) {
        input.reportValidity();
        return null;
      }
    }
    return {
      players: Number(fields.players.value),
      starting_stack: Number(fields.starting_stack.value),
      expected_reentries: Number(fields.expected_reentries.value),
      max_reentries_per_player: fields.max_reentries_per_player.value === '' ? null : Number(fields.max_reentries_per_player.value),
      first_small_blind: Number(fields.first_small_blind.value),
      first_big_blind: Number(fields.first_big_blind.value),
      level_duration_minutes: Number(fields.level_duration_minutes.value),
      target_duration_minutes: Number(fields.target_duration_minutes.value),
      ante_mode: fields.ante_mode.value,
      ante_start_mode: fields.ante_start_mode.value,
      ante_start_level: fields.ante_start_level.disabled ? null : Number(fields.ante_start_level.value),
      break_every_levels: Number(fields.break_every_levels.value),
      break_duration_minutes: fields.break_duration_minutes.disabled ? 0 : Number(fields.break_duration_minutes.value),
      chip_denominations: parseDenominations(fields.chip_denominations.value),
    };
  }

  function addSummary(label, value) {
    const row = make('div');
    row.append(make('span', '', label), make('strong', '', value));
    summaryBox.append(row);
  }

  function renderSummary(result) {
    const summary = result.summary;
    summaryBox.replaceChildren();
    addSummary('Цель', formatDuration(summary.target_duration_seconds));
    addSummary('Ориентировочное окно', formatDuration(summary.finish_window.from_seconds) + '–' + formatDuration(summary.finish_window.to_seconds).slice(1));
    addSummary('Уровней до целевой зоны', String(summary.blind_levels_to_target));
    addSummary('Перерывы до цели', summary.breaks_before_target + ' × ' + Math.round(summary.break_duration_seconds / 60) + ' мин');
    addSummary('Стартовая глубина', formatNumber(summary.starting_depth_bb) + ' BB');
    addSummary('Плановый объём фишек', formatNumber(summary.planned_total_chips));
    addSummary('Ожидаемые re-entry', formatNumber(summary.expected_reentries));
    addSummary('Буфер после окна', summary.extension_levels + ' уровня');
  }

  function renderDiagnostics(result) {
    diagnosticsBox.replaceChildren();
    diagnosticsBox.hidden = !result.diagnostics.length;
    result.diagnostics.forEach(item => {
      const note = make('p', 'structure-diagnostic ' + item.severity, item.message);
      if (item.suggested_target_duration_minutes) {
        note.append(make('small', '', ' Рекомендуемая цель: не меньше ' + formatDuration(item.suggested_target_duration_minutes * 60) + '.'));
      }
      diagnosticsBox.append(note);
    });
  }

  function renderLevels(result) {
    levelsBox.replaceChildren();
    let number = 0;
    result.levels.forEach(level => {
      const row = make('div', 'structure-preview-level ' + level.kind);
      if (level.kind === 'break') {
        row.append(make('strong', '', 'Перерыв'), make('span', '', Math.round(level.duration_seconds / 60) + ' мин'));
      } else {
        number += 1;
        row.append(make('strong', '', String(number)));
        const blinds = formatNumber(level.small_blind) + ' / ' + formatNumber(level.big_blind);
        row.append(make('span', '', level.ante > 0 ? blinds + ' / ' + formatNumber(level.ante) + ' BBA' : blinds));
        row.append(make('small', '', Math.round(level.duration_seconds / 60) + ' мин'));
      }
      levelsBox.append(row);
    });
  }

  async function generate() {
    error.textContent = '';
    if (options.beforeGenerate && !(await options.beforeGenerate())) return;
    let data;
    try {
      data = payload();
    } catch (payloadError) {
      error.textContent = payloadError.message;
      return;
    }
    if (!data) return;
    generateButton.disabled = true;
    generateButton.textContent = 'Генерирую…';
    try {
      const result = await request('/api/v1/structure-generator', {method: 'POST', body: JSON.stringify(data)});
      latestResult = result;
      latestPayload = data;
      renderSummary(result);
      renderDiagnostics(result);
      renderLevels(result);
      resultBox.hidden = false;
      generateButton.textContent = 'Пересчитать';
      resultBox.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (requestError) {
      error.textContent = requestError.message;
      generateButton.textContent = latestResult ? 'Пересчитать' : 'Сгенерировать структуру';
    } finally {
      generateButton.disabled = false;
    }
  }

  fields.ante_mode.addEventListener('change', updateConditionalFields);
  fields.ante_start_mode.addEventListener('change', updateConditionalFields);
  fields.break_every_levels.addEventListener('input', updateConditionalFields);
  fields.chip_denominations.addEventListener('input', updateChipContext);
  generateButton.addEventListener('click', generate);
  if (applyButton) applyButton.addEventListener('click', () => {
    if (latestResult) options.onApply?.(latestResult, latestPayload);
  });
  const close = root.querySelector('[data-action="close"]');
  if (close) close.addEventListener('click', () => root.closest('dialog')?.close());
  updateConditionalFields();
  updateChipContext();

  return {
    open() {
      fillInputs(options.inputProvider?.());
      root.closest('dialog')?.showModal();
    },
    payload,
    latestResult: () => latestResult,
  };
}

document.querySelectorAll('[data-structure-generator-auto]').forEach(root => initStructureGenerator(root));
