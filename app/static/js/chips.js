import {openDialog, showNotice} from './dialog.js?v=20261028-1';

const list = document.querySelector('#chip-set-list');
const errorLine = document.querySelector('#chip-list-error');
const number = value => new Intl.NumberFormat('ru-RU').format(value);

async function request(url, options = {}) {
  const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options});
  if (!response.ok) {
    const body = await response.json();
    throw new Error(body.detail?.message || 'Не удалось выполнить действие.');
  }
  return response.json();
}

function metric(label, value) {
  const item = document.createElement('div');
  const caption = document.createElement('span');
  caption.textContent = label;
  const amount = document.createElement('strong');
  amount.textContent = number(value);
  item.append(caption, amount);
  return item;
}

function renderEmpty() {
  list.replaceChildren();
  const empty = document.createElement('section');
  empty.className = 'chip-empty-state';
  const title = document.createElement('h2');
  title.textContent = 'Наборов фишек пока нет';
  const copy = document.createElement('p');
  copy.textContent = 'Добавьте набор, который лежит у вас дома, и укажите, сколько в нём фишек каждого номинала.';
  const action = document.createElement('a');
  action.href = '/chips/new';
  action.textContent = 'Создать первый набор';
  empty.append(title, copy, action);
  list.append(empty);
}

function render(chipSets) {
  list.replaceChildren();
  if (!chipSets.length) {
    renderEmpty();
    return;
  }
  for (const chipSet of chipSets) {
    const card = document.createElement('article');
    card.className = 'chip-set-card';
    const header = document.createElement('header');
    const title = document.createElement('h2');
    title.textContent = chipSet.name;
    header.append(title);
    if (chipSet.is_default) {
      const badge = document.createElement('span');
      badge.className = 'chip-default-badge';
      badge.textContent = 'По умолчанию';
      header.append(badge);
    }

    const metrics = document.createElement('div');
    metrics.className = 'chip-set-metrics';
    metrics.append(metric('Фишек', chipSet.total_chips), metric('Общая стоимость', chipSet.total_value));

    const denominations = document.createElement('div');
    denominations.className = 'chip-set-denominations';
    if (!chipSet.denominations.length) {
      const empty = document.createElement('p');
      empty.className = 'chip-set-no-denominations';
      empty.textContent = 'Номиналы пока не добавлены.';
      denominations.append(empty);
    }
    for (const denomination of chipSet.denominations) {
      const line = document.createElement('div');
      const value = document.createElement('strong');
      value.textContent = number(denomination.value);
      const multiply = document.createElement('span');
      multiply.textContent = '×';
      const quantity = document.createElement('span');
      quantity.textContent = number(denomination.quantity);
      line.append(value, multiply, quantity);
      denominations.append(line);
    }

    const actions = document.createElement('div');
    actions.className = 'chip-set-actions';
    const edit = document.createElement('a');
    edit.href = `/chips/${chipSet.id}/edit`;
    edit.textContent = 'Редактировать';
    actions.append(edit);
    if (!chipSet.is_default) {
      const makeDefault = document.createElement('button');
      makeDefault.type = 'button';
      makeDefault.className = 'secondary-action';
      makeDefault.textContent = 'По умолчанию';
      makeDefault.addEventListener('click', async () => {
        errorLine.textContent = '';
        try {
          await request(`/api/v1/chip-sets/${chipSet.id}/default`, {method: 'POST'});
          await load();
        } catch (error) {
          errorLine.textContent = error.message;
          await showNotice({tone: 'danger', title: 'Не удалось выбрать набор', message: error.message});
        }
      });
      actions.append(makeDefault);
    }
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'danger';
    remove.textContent = 'Удалить';
    remove.addEventListener('click', async () => {
      const confirmed = await openDialog({
        tone: 'danger',
        eyebrow: 'Опасное действие',
        title: 'Удалить набор фишек?',
        message: `Набор «${chipSet.name}» и все его номиналы будут удалены. Восстановить их будет нельзя.`,
        confirmLabel: 'Удалить набор',
      });
      if (confirmed === null) return;
      try {
        await request(`/api/v1/chip-sets/${chipSet.id}`, {method: 'DELETE'});
        await load();
      } catch (error) {
        errorLine.textContent = error.message;
        await showNotice({tone: 'danger', title: 'Не удалось удалить набор', message: error.message});
      }
    });
    actions.append(remove);
    card.append(header, metrics, denominations, actions);
    list.append(card);
  }
}

async function load() {
  errorLine.textContent = '';
  try {
    render(await request('/api/v1/chip-sets'));
  } catch (error) {
    list.replaceChildren();
    errorLine.textContent = error.message;
  }
}

load();
