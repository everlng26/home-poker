const formatNumber = value => new Intl.NumberFormat('ru-RU').format(Number(value || 0));

const levelsWord = value => {
  const mod100 = value % 100; const mod10 = value % 10;
  return mod100 >= 11 && mod100 <= 14 ? 'уровней' : mod10 === 1 ? 'уровень' : mod10 >= 2 && mod10 <= 4 ? 'уровня' : 'уровней';
};
const make = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const formatDuration = seconds => {
  const totalMinutes = Math.round(Number(seconds || 0) / 60);
  return '~' + Math.floor(totalMinutes / 60) + ':' + String(totalMinutes % 60).padStart(2, '0');
};

async function request(url, options = {}) {
  const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options});
  const body = (response.headers.get('content-type') || '').includes('application/json') ? await response.json() : null;
  if (!response.ok) throw new Error(body?.detail?.message || 'Не удалось автоматически подобрать турнир.');
  if (!body) throw new Error('Сервер вернул неожиданный ответ. Перезапустите Home Poker и повторите расчёт.');
  return body;
}

export function initAutoTournamentBuilder(root, options = {}) {
  const setList = root.querySelector('[data-role="chip-sets"]');
  const fields = Object.fromEntries([...root.querySelectorAll('[data-field]')].map(input => [input.dataset.field, input]));
  const error = root.querySelector('[data-role="error"]');
  const forecast = root.querySelector('[data-role="forecast"]');
  const candidates = root.querySelector('[data-role="candidates"]');
  const generateButton = root.querySelector('[data-action="generate"]');
  let chipSets = [];
  let latestResult = null;

  const selectedIds = () => [...setList.querySelectorAll('input:checked')].map(input => Number(input.value));

  function renderSets() {
    setList.replaceChildren();
    if (!chipSets.length) {
      setList.append(make('p', 'create-empty', 'Сначала создайте хотя бы один набор в разделе «Фишки».'));
      const link = make('a', 'secondary', 'Открыть раздел «Фишки»'); link.href = '/chips';
      setList.append(link); generateButton.disabled = true; return;
    }
    chipSets.forEach(chipSet => {
      const label = make('label', 'auto-builder-chip-set');
      const input = document.createElement('input'); input.type = 'checkbox'; input.value = String(chipSet.id); input.checked = chipSet.is_default;
      const copy = make('span', 'auto-builder-chip-copy');
      copy.append(make('strong', '', chipSet.name), make('small', '', formatNumber(chipSet.total_chips) + ' фишек на ' + formatNumber(chipSet.total_value)));
      label.append(input, copy); setList.append(label);
    });
    if (!selectedIds().length) setList.querySelector('input').checked = true;
  }

  function fillInputs(values) {
    Object.entries(values || {}).forEach(([name, value]) => {
      if (fields[name] && value !== undefined && value !== null && value !== '') fields[name].value = value;
    });
  }

  function payload() {
    for (const input of Object.values(fields)) {
      if (!input.checkValidity()) { input.reportValidity(); return null; }
    }
    return {
      chip_set_ids: selectedIds(),
      players: Number(fields.players.value),
      max_reentries_per_player: Number(fields.max_reentries_per_player.value),
      target_duration_minutes: Number(fields.target_duration_minutes.value),
      ante_mode: fields.ante_mode.value,
    };
  }

  function distribution(title, rows) {
    const block = make('div', 'auto-builder-distribution');
    block.append(make('strong', '', title));
    const values = make('div', 'auto-builder-distribution-values');
    rows.forEach(item => values.append(make('span', '', formatNumber(item.value) + ' × ' + formatNumber(item.quantity))));
    if (!rows.length) values.append(make('span', '', 'Не требуется'));
    block.append(values); return block;
  }

  function structurePreview(plan) {
    const details = make('details', 'auto-builder-structure');
    const summary = document.createElement('summary');
    summary.textContent = 'Посмотреть структуру'; details.append(summary);
    const rows = make('div', 'auto-builder-levels');
    let number = 0;
    plan.levels.forEach(level => {
      const row = make('div', 'structure-preview-level ' + level.kind);
      if (level.kind === 'break') row.append(make('strong', '', 'Перерыв'), make('span', '', Math.round(level.duration_seconds / 60) + ' мин'));
      else {
        number += 1;
        const blinds = formatNumber(level.small_blind) + ' / ' + formatNumber(level.big_blind);
        row.append(make('strong', '', String(number)), make('span', '', level.ante ? blinds + ' / ' + formatNumber(level.ante) + ' BBA' : blinds), make('small', '', Math.round(level.duration_seconds / 60) + ' мин'));
      }
      rows.append(row);
    });
    details.append(rows); return details;
  }

  function renderCandidates(result) {
    candidates.replaceChildren();
    forecast.hidden = false;
    forecast.textContent = result.expected_reentries_explanation;
    result.candidates.forEach(plan => {
      const card = make('article', 'auto-builder-candidate' + (plan.recommended ? ' is-recommended' : ''));
      const heading = make('header', 'auto-builder-candidate-heading');
      const title = make('div');
      title.append(make('h3', '', plan.label));
      const coverage = plan.reentry_coverage.status === 'full' ? 'Полное покрытие' : 'Частичное покрытие';
      heading.append(title, make('span', 'stack-coverage-badge ' + plan.reentry_coverage.status, coverage));
      const stats = make('div', 'auto-builder-stats');
      const stat = (label, value) => { const row = make('div'); row.append(make('span', '', label), make('strong', '', value)); stats.append(row); };
      stat('Стартовый стек', formatNumber(plan.starting_stack));
      stat('Первый уровень', formatNumber(plan.first_small_blind) + ' / ' + formatNumber(plan.first_big_blind));
      stat('Стартовая глубина', formatNumber(plan.starting_depth_bb) + ' BB');
      stat('Уровни', plan.level_duration_minutes + ' мин');
      stat('Запас на re-entry', plan.reentry_coverage.covered + ' из ' + plan.reentry_coverage.maximum);
      stat('Окно окончания', formatDuration(plan.finish_window.from_seconds) + '–' + formatDuration(plan.finish_window.to_seconds).slice(1));
      stat('BB-анте', plan.ante_start_level ? 'с уровня ' + plan.ante_start_level : 'выключено');
      stat('Перерывы', plan.break_schedule.every_levels ? 'каждые ' + plan.break_schedule.every_levels + ' ' + levelsWord(plan.break_schedule.every_levels) + ' по ' + plan.break_schedule.duration_minutes + ' мин' : 'без перерывов');
      card.append(heading, stats, distribution('Стек игрока', plan.stack_distribution_per_player), distribution('Набор для re-entry', plan.reentry_pack));
      if (plan.diagnostics.length) {
        const notes = make('div', 'auto-builder-diagnostics');
        plan.diagnostics.forEach(item => notes.append(make('p', 'structure-diagnostic ' + item.severity, item.message)));
        card.append(notes);
      }
      card.append(structurePreview(plan));
      const apply = make('button', 'auto-builder-apply', 'Использовать этот вариант'); apply.type = 'button';
      apply.addEventListener('click', async () => {
        if (options.beforeApply && !(await options.beforeApply(plan, result))) return;
        await options.onApply?.(plan, result);
      });
      card.append(apply); candidates.append(card);
    });
  }

  async function generate() {
    error.textContent = '';
    if (options.beforeGenerate && !(await options.beforeGenerate())) return;
    const data = payload(); if (!data) return;
    if (!data.chip_set_ids.length) { error.textContent = 'Выберите хотя бы один набор фишек.'; return; }
    generateButton.disabled = true; generateButton.textContent = 'Подбираю…'; candidates.replaceChildren(); forecast.hidden = true;
    try {
      latestResult = await request('/api/v1/auto-tournament-builder', {method: 'POST', body: JSON.stringify(data)});
      renderCandidates(latestResult);
      generateButton.textContent = 'Сгенерировать заново';
      candidates.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (requestError) {
      error.textContent = requestError.message;
      generateButton.textContent = latestResult ? 'Сгенерировать заново' : 'Сгенерировать турнир';
    } finally {
      generateButton.disabled = false;
    }
  }

  generateButton.addEventListener('click', generate);
  root.querySelector('[data-action="close"]').addEventListener('click', () => root.closest('dialog')?.close());
  const loaded = request('/api/v1/chip-sets').then(data => { chipSets = data; renderSets(); }).catch(loadError => { error.textContent = loadError.message; });

  return {
    async open() {
      await loaded; fillInputs(options.inputProvider?.()); root.closest('dialog')?.showModal();
    },
    payload,
    latestResult: () => latestResult,
  };
}
