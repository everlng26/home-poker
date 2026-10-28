const formatNumber = value => new Intl.NumberFormat('ru-RU').format(Number(value || 0));

const candidateLabels = {Comfortable: 'Комфортный', Balanced: 'Сбалансированный', Compact: 'Компактный'};
const make = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

async function request(url, options = {}) {
  const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options});
  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const body = isJson ? await response.json() : null;
  if (!response.ok) {
    const fallback = response.status === 404
      ? 'Конструктор стеков ещё не загружен сервером. Перезапустите Home Poker и повторите расчёт.'
      : 'Не удалось выполнить расчёт.';
    throw new Error(body?.detail?.message || fallback);
  }
  if (!isJson) throw new Error('Сервер вернул неожиданный ответ. Перезапустите Home Poker и повторите расчёт.');
  return body;
}

export function initStackOptimizer(root, options = {}) {
  const setList = root.querySelector('[data-role="chip-sets"]');
  const combinedBox = root.querySelector('[data-role="combined-summary"]');
  const combinedTotals = root.querySelector('[data-role="combined-totals"]');
  const denominationList = root.querySelector('[data-role="denominations"]');
  const error = root.querySelector('[data-role="error"]');
  const diagnostics = root.querySelector('[data-role="diagnostics"]');
  const candidates = root.querySelector('[data-role="candidates"]');
  const solveButton = root.querySelector('[data-action="solve"]');
  const fields = Object.fromEntries([...root.querySelectorAll('[data-field]')].map(input => [input.dataset.field, input]));
  let chipSets = [];
  let excluded = new Set();
  let loaded;

  const selectedIds = () => [...setList.querySelectorAll('input:checked')].map(input => Number(input.value));

  function aggregate() {
    const selected = new Set(selectedIds());
    const quantities = new Map();
    chipSets.filter(chipSet => selected.has(chipSet.id)).forEach(chipSet => {
      chipSet.denominations.forEach(item => quantities.set(item.value, (quantities.get(item.value) || 0) + item.quantity));
    });
    return [...quantities.entries()].sort((left, right) => left[0] - right[0]).map(([value, quantity]) => ({value, quantity}));
  }

  function renderCombined() {
    const denominations = aggregate();
    combinedBox.hidden = !selectedIds().length;
    if (combinedBox.hidden) return;
    const totalChips = denominations.reduce((sum, item) => sum + item.quantity, 0);
    const totalValue = denominations.reduce((sum, item) => sum + item.value * item.quantity, 0);
    combinedTotals.textContent = formatNumber(totalChips) + ' фишек на ' + formatNumber(totalValue);
    denominationList.replaceChildren();
    denominations.forEach(item => {
      const label = make('label', 'stack-denomination-option');
      const input = document.createElement('input');
      input.type = 'checkbox'; input.checked = !excluded.has(item.value); input.value = String(item.value);
      input.addEventListener('change', () => {
        if (input.checked) excluded.delete(item.value); else excluded.add(item.value);
        candidates.replaceChildren(); diagnostics.hidden = true;
      });
      label.append(input, make('span', '', formatNumber(item.value) + ' × ' + formatNumber(item.quantity)));
      denominationList.append(label);
    });
  }

  function renderSets() {
    setList.replaceChildren();
    if (!chipSets.length) {
      const empty = make('p', 'create-empty', 'Сначала создайте хотя бы один набор в разделе «Фишки».');
      const link = make('a', 'secondary', 'Открыть раздел «Фишки»'); link.href = '/chips';
      setList.append(empty, link); solveButton.disabled = true; return;
    }
    chipSets.forEach(chipSet => {
      const label = make('label', 'stack-chip-set-option');
      const input = document.createElement('input');
      input.type = 'checkbox'; input.value = String(chipSet.id); input.checked = chipSet.is_default;
      input.addEventListener('change', () => { renderCombined(); candidates.replaceChildren(); diagnostics.hidden = true; });
      const copy = make('span', 'stack-chip-set-copy');
      copy.append(make('strong', '', chipSet.name), make('small', '', formatNumber(chipSet.total_chips) + ' фишек на ' + formatNumber(chipSet.total_value)));
      label.append(input, copy); setList.append(label);
    });
    if (!selectedIds().length) setList.querySelector('input').checked = true;
    renderCombined();
  }

  function distributionBlock(title, rows) {
    const block = make('div', 'stack-distribution');
    if (title) block.append(make('strong', '', title));
    const list = make('div', 'stack-distribution-list');
    if (!rows.length) list.append(make('span', '', 'Не требуется'));
    rows.forEach(item => list.append(make('span', '', formatNumber(item.value) + ' × ' + formatNumber(item.quantity))));
    block.append(list); return block;
  }

  function renderDiagnostics(result) {
    diagnostics.replaceChildren(); diagnostics.hidden = false;
    diagnostics.classList.toggle('is-problem', !result.feasible);
    const data = result.diagnostics;
    const grid = make('div', 'stack-diagnostic-grid');
    const diagnostic = (label, value) => { const row = make('div'); row.append(make('span', '', label), make('strong', '', value)); grid.append(row); };
    diagnostic('Нужно для стартовой посадки', formatNumber(data.required_initial_value));
    diagnostic('Доступно', formatNumber(data.available_value));
    diagnostic('С запасом на все re-entry', formatNumber(data.required_full_coverage_value));
    if (data.initial_value_shortage) diagnostic('Не хватает', formatNumber(data.initial_value_shortage));
    diagnostics.append(make('strong', '', data.message), grid);
  }

  function renderCandidates(result, solvePayload) {
    candidates.replaceChildren();
    if (!result.feasible) return;
    result.candidates.forEach(candidate => {
      const card = make('article', 'stack-candidate');
      if (candidate.recommended) card.classList.add('is-recommended');
      const heading = make('header', 'stack-candidate-heading');
      const title = make('div', 'stack-candidate-title');
      if (candidate.recommended) title.append(make('span', 'stack-recommended-label', 'Рекомендуем'));
      title.append(make('h3', '', candidateLabels[candidate.label] || candidate.label));
      const badgeText = candidate.coverage_status === 'full' ? 'Полное покрытие' : 'Частичное покрытие';
      heading.append(title, make('span', 'stack-coverage-badge ' + candidate.coverage_status, badgeText));
      const stats = make('div', 'stack-candidate-stats');
      const addStat = (label, value) => { const row = make('div'); row.append(make('span', '', label), make('strong', '', value)); stats.append(row); };
      addStat('Стартовый стек', formatNumber(candidate.value));
      addStat('Фишек на игрока', formatNumber(candidate.chips_per_player));
      addStat('Допустимо re-entry', formatNumber(candidate.max_allowed_reentries));
      addStat('Запас на re-entry', formatNumber(candidate.covered_reentries) + ' / ' + formatNumber(candidate.max_allowed_reentries));
      card.append(heading, stats);
      if (candidate.recommended && candidate.quality_highlights.length) {
        const highlights = make('div', 'stack-quality-highlights');
        candidate.quality_highlights.forEach(message => highlights.append(make('span', '', message)));
        card.append(highlights);
      }
      card.append(distributionBlock('Стек игрока', candidate.initial_distribution), distributionBlock('Набор для re-entry', candidate.reentry_pack));
      const coverage = make('div', 'stack-coverage-note ' + candidate.coverage_status);
      coverage.append(make('strong', '', 'Запас на re-entry'), make('p', '', candidate.coverage_message));
      const coverageMeta = make('div', 'stack-coverage-meta');
      if (candidate.uniform_message) coverageMeta.append(make('span', '', candidate.uniform_message));
      if (candidate.coverage_suggestion) coverageMeta.append(make('span', '', candidate.coverage_suggestion));
      if (coverageMeta.childElementCount) coverage.append(coverageMeta);
      card.append(coverage);
      candidate.warnings.forEach(message => card.append(make('p', 'stack-candidate-note', message)));
      const remaining = make('details', 'stack-remaining');
      const remainingSummary = document.createElement('summary');
      const remainingCopy = make('span', 'stack-remaining-copy');
      remainingCopy.append(make('strong', '', 'Остаток после резерва'), make('small', '', 'Посмотреть номиналы и количество'));
      remainingSummary.append(make('span', 'stack-remaining-chevron'), remainingCopy);
      const remainingBody = make('div', 'stack-remaining-body');
      remainingBody.append(distributionBlock('', candidate.remaining_inventory));
      remaining.append(remainingSummary, remainingBody);
      card.append(remaining);
      if (options.onApply) {
        const apply = make('button', 'stack-apply', 'Использовать этот вариант'); apply.type = 'button';
        apply.addEventListener('click', () => options.onApply({
          chip_set_ids: solvePayload.chip_set_ids,
          excluded_denominations: solvePayload.excluded_denominations,
          initial_distribution: candidate.initial_distribution,
          candidate,
          result,
        }));
        card.append(apply);
      }
      candidates.append(card);
    });
  }

  function fillInputs(values) {
    if (!values) return;
    Object.entries(values).forEach(([name, value]) => {
      if (fields[name]) fields[name].value = value ?? '';
    });
  }

  function payload() {
    for (const input of Object.values(fields)) {
      if (!input.checkValidity()) { input.reportValidity(); return null; }
    }
    const optional = name => fields[name].value === '' ? null : Number(fields[name].value);
    return {
      chip_set_ids: selectedIds(),
      excluded_denominations: [...excluded].sort((left, right) => left - right),
      players: Number(fields.players.value),
      starting_stack: Number(fields.starting_stack.value),
      max_reentries_per_player: Number(fields.max_reentries_per_player.value),
      first_small_blind: optional('first_small_blind'),
      first_big_blind: optional('first_big_blind'),
      first_ante: optional('first_ante'),
    };
  }

  async function solve() {
    error.textContent = '';
    const data = payload();
    if (!data) return;
    if (!data.chip_set_ids.length) { error.textContent = 'Выберите хотя бы один набор фишек.'; return; }
    solveButton.disabled = true; solveButton.textContent = 'Считаю…'; candidates.replaceChildren(); diagnostics.hidden = true;
    try {
      const result = await request('/api/v1/stack-optimizer', {method: 'POST', body: JSON.stringify(data)});
      renderDiagnostics(result); renderCandidates(result, data);
    } catch (requestError) {
      error.textContent = requestError.message;
    } finally {
      solveButton.disabled = false; solveButton.textContent = 'Рассчитать';
    }
  }

  solveButton.addEventListener('click', solve);
  const close = root.querySelector('[data-action="close"]');
  if (close) close.addEventListener('click', () => root.closest('dialog')?.close());
  loaded = request('/api/v1/chip-sets').then(data => { chipSets = data; renderSets(); }).catch(loadError => { error.textContent = loadError.message; });

  return {
    async open() {
      await loaded;
      fillInputs(options.inputProvider?.());
      if (options.lockInputs) Object.values(fields).forEach(input => { input.readOnly = true; });
      root.closest('dialog')?.showModal();
    },
    payload,
  };
}

document.querySelectorAll('[data-stack-optimizer-auto]').forEach(root => initStackOptimizer(root));
