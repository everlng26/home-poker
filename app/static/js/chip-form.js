const page = document.querySelector('#chip-form-page');
const form = document.querySelector('#chip-set-form');
const nameInput = document.querySelector('#chip-set-name');
const defaultInput = document.querySelector('#chip-set-default');
const list = document.querySelector('#chip-denomination-list');
const addButton = document.querySelector('#add-denomination');
const errorLine = document.querySelector('#chip-form-error');
const saveButton = document.querySelector('#save-chip-set');
const totalCount = document.querySelector('#chip-total-count');
const totalValue = document.querySelector('#chip-total-value');
const chipSetId = page.dataset.chipSetId ? Number(page.dataset.chipSetId) : null;
const number = value => new Intl.NumberFormat('ru-RU').format(value);

async function request(url, options = {}) {
  const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options});
  if (!response.ok) {
    const body = await response.json();
    throw new Error(body.detail?.message || 'Не удалось сохранить набор.');
  }
  return response.json();
}

function values() {
  return [...list.querySelectorAll('.chip-denomination-row')].map(row => ({
    value: Number(row.querySelector('[data-field="value"]').value),
    quantity: Number(row.querySelector('[data-field="quantity"]').value),
  }));
}

function updateSummary() {
  let chips = 0;
  let value = 0;
  for (const item of values()) {
    if (!Number.isSafeInteger(item.value) || !Number.isSafeInteger(item.quantity)) continue;
    if (item.value <= 0 || item.quantity < 0) continue;
    chips += item.quantity;
    value += item.value * item.quantity;
  }
  totalCount.textContent = number(chips);
  totalValue.textContent = number(value);
}

function sortRows() {
  const rows = [...list.querySelectorAll('.chip-denomination-row')];
  rows.sort((left, right) => {
    const leftValue = Number(left.querySelector('[data-field="value"]').value) || Number.MAX_SAFE_INTEGER;
    const rightValue = Number(right.querySelector('[data-field="value"]').value) || Number.MAX_SAFE_INTEGER;
    return leftValue - rightValue;
  });
  rows.forEach(row => list.append(row));
}

function addRow(item = {value: '', quantity: ''}, focus = false) {
  const row = document.createElement('div');
  row.className = 'chip-denomination-row';
  const valueLabel = document.createElement('label');
  valueLabel.innerHTML = '<span>Номинал</span>';
  const valueInput = document.createElement('input');
  valueInput.type = 'number';
  valueInput.min = '1';
  valueInput.step = '1';
  valueInput.inputMode = 'numeric';
  valueInput.required = true;
  valueInput.dataset.field = 'value';
  valueInput.value = item.value;
  const multiply = document.createElement('span');
  multiply.className = 'chip-multiply';
  multiply.textContent = '×';
  const quantityLabel = document.createElement('label');
  quantityLabel.innerHTML = '<span>Количество</span>';
  const quantityInput = document.createElement('input');
  quantityInput.type = 'number';
  quantityInput.min = '0';
  quantityInput.step = '1';
  quantityInput.inputMode = 'numeric';
  quantityInput.required = true;
  quantityInput.dataset.field = 'quantity';
  quantityInput.value = item.quantity;
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'chip-remove-denomination';
  remove.textContent = 'Удалить';
  remove.setAttribute('aria-label', 'Удалить строку номинала');
  remove.addEventListener('click', () => {
    row.remove();
    updateSummary();
  });
  for (const input of [valueInput, quantityInput]) {
    input.addEventListener('input', () => {
      input.setCustomValidity('');
      errorLine.textContent = '';
      updateSummary();
    });
  }
  valueInput.addEventListener('change', sortRows);
  valueLabel.append(valueInput);
  quantityLabel.append(quantityInput);
  row.append(valueLabel, multiply, quantityLabel, remove);
  list.append(row);
  updateSummary();
  if (focus) valueInput.focus();
}

function validateRows() {
  const seen = new Set();
  for (const row of list.querySelectorAll('.chip-denomination-row')) {
    const valueInput = row.querySelector('[data-field="value"]');
    const quantityInput = row.querySelector('[data-field="quantity"]');
    const value = Number(valueInput.value);
    const quantity = Number(quantityInput.value);
    valueInput.setCustomValidity('');
    quantityInput.setCustomValidity('');
    if (!valueInput.value || !Number.isSafeInteger(value) || value <= 0) {
      valueInput.setCustomValidity('Введите целый положительный номинал.');
      valueInput.reportValidity();
      return false;
    }
    if (!quantityInput.value || !Number.isSafeInteger(quantity) || quantity < 0) {
      quantityInput.setCustomValidity('Введите целое неотрицательное количество.');
      quantityInput.reportValidity();
      return false;
    }
    if (seen.has(value)) {
      valueInput.setCustomValidity('Такой номинал уже есть в наборе.');
      valueInput.reportValidity();
      errorLine.textContent = `Номинал ${number(value)} указан дважды.`;
      return false;
    }
    seen.add(value);
  }
  return true;
}

addButton.addEventListener('click', () => addRow(undefined, true));
form.addEventListener('submit', async event => {
  event.preventDefault();
  errorLine.textContent = '';
  if (!nameInput.checkValidity()) {
    nameInput.reportValidity();
    return;
  }
  if (!validateRows()) return;
  sortRows();
  saveButton.disabled = true;
  try {
    const payload = {
      name: nameInput.value,
      is_default: defaultInput.checked,
      denominations: values(),
    };
    await request(chipSetId ? `/api/v1/chip-sets/${chipSetId}` : '/api/v1/chip-sets', {
      method: chipSetId ? 'PUT' : 'POST',
      body: JSON.stringify(payload),
    });
    location.href = '/chips';
  } catch (error) {
    errorLine.textContent = error.message;
    errorLine.scrollIntoView({behavior: 'smooth', block: 'center'});
    saveButton.disabled = false;
  }
});

async function initialize() {
  if (!chipSetId) {
    addRow();
    return;
  }
  saveButton.disabled = true;
  try {
    const chipSet = await request(`/api/v1/chip-sets/${chipSetId}`);
    nameInput.value = chipSet.name;
    defaultInput.checked = chipSet.is_default;
    chipSet.denominations.forEach(item => addRow(item));
    updateSummary();
    saveButton.disabled = false;
  } catch (error) {
    errorLine.textContent = error.message;
    form.hidden = true;
  }
}

initialize();
