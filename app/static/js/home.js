import {openDialog, showNotice} from './dialog.js?v=20261028-1';

const app = document.querySelector('#app');
const request = async (url, options = {}) => {
  const response = await fetch(url, { headers: {'Content-Type': 'application/json'}, ...options });
  if (!response.ok) { const body = await response.json(); throw new Error(body.detail?.message || 'Не удалось выполнить действие.'); }
  return response.json();
};

const statuses = {draft: 'Не начат', paused: 'Пауза', running: 'Идёт', finished: 'Завершён'};
// Идущие турниры сверху, затем подготовленные, завершённые в конце.
const statusOrder = {running: 0, paused: 0, draft: 1, finished: 2};
const money = (value, currency) => Math.round(value).toLocaleString('ru-RU') + ' ' + currency;
const plural = (value, one, few, many) => {
  const mod100 = value % 100; const mod10 = value % 10;
  return mod100 >= 11 && mod100 <= 14 ? many : mod10 === 1 ? one : mod10 >= 2 && mod10 <= 4 ? few : many;
};
const icon = name => '<svg class="icon" aria-hidden="true"><use href="#i-' + name + '"/></svg>';

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function statusText(item) {
  if (item.status === 'running' && item.timer_status !== 'running') return 'Пауза';
  if (item.status === 'running' && item.current_level_kind === 'break') return 'Перерыв';
  return statuses[item.status] || item.status;
}

function metaParts(item) {
  const parts = [];
  if (item.status !== 'draft' && item.status !== 'finished' && item.current_level_number) parts.push('уровень ' + item.current_level_number);
  if (item.status === 'draft' || item.status === 'finished') {
    parts.push(item.registered_players + ' ' + plural(item.registered_players, 'игрок', 'игрока', 'игроков'));
  } else {
    parts.push(item.active_players + ' из ' + item.registered_players + ' в игре');
  }
  if (item.is_freeroll) parts.push('фриролл');
  else parts.push('бай-ин ' + money(item.buy_in_amount, item.currency_label));
  if (item.bounty_mode === 'fixed') parts.push('баунти ' + money(item.bounty_amount, item.currency_label));
  return parts;
}

async function removeTournament(item) {
  const pin = await openDialog({
    tone: 'danger',
    eyebrow: 'Опасное действие',
    title: 'Удалить турнир?',
    message: 'Будут удалены турнир «' + item.name + '», игроки и весь журнал действий. Восстановить их будет нельзя.',
    confirmLabel: 'Удалить турнир',
    pin: true,
  });
  if (pin === null) return;
  try {
    await request('/api/v1/tournaments/' + item.id + '/delete', {method: 'POST', body: JSON.stringify({pin})});
    load();
  } catch (error) {
    document.querySelector('#error').textContent = error.message;
    await showNotice({tone: 'danger', eyebrow: 'Удаление не выполнено', title: 'Не удалось удалить турнир', message: error.message});
  }
}

function tournamentRow(item) {
  const row = element('article', 'tournament-row');
  row.dataset.status = item.status;
  const main = element('div', 'tournament-row-main');
  const title = element('h3');
  const link = element('a', '', item.name); link.href = '/display/' + item.id;
  title.append(link);
  const meta = element('p', 'tournament-row-meta');
  meta.append(element('span', 'tournament-status', statusText(item)));
  metaParts(item).forEach(part => meta.append(element('span', '', part)));
  main.append(title, meta);

  const actions = element('div', 'tournament-row-actions');
  const display = element('a', 'button', 'Табло'); display.href = '/display/' + item.id;
  const admin = element('a', 'button secondary', 'Админка'); admin.href = '/login/' + item.id;
  const qr = element('details', 'tournament-qr');
  const qrSummary = element('summary');
  qrSummary.innerHTML = icon('qr') + '<span class="sr-only">QR-код админки</span>';
  qrSummary.title = 'QR-код админки для телефона';
  const qrPop = element('div', 'tournament-qr-pop');
  const qrImage = element('img'); qrImage.alt = 'QR-код админки турнира «' + item.name + '»'; qrImage.loading = 'lazy'; qrImage.src = '/api/v1/tournaments/' + item.id + '/qr/admin';
  qrPop.append(qrImage, element('span', '', 'Наведите камеру телефона, чтобы открыть админку.'));
  qr.append(qrSummary, qrPop);
  const remove = element('button', 'icon-button danger-quiet');
  remove.type = 'button';
  remove.title = 'Удалить турнир';
  remove.setAttribute('aria-label', 'Удалить турнир «' + item.name + '»');
  remove.innerHTML = icon('trash');
  remove.onclick = () => removeTournament(item);
  actions.append(display, admin, qr, remove);
  row.append(main, actions);
  return row;
}

function show(tournaments) {
  app.innerHTML = `
    <section class="home-page">
      <header class="home-header">
        <div class="home-brand"><img class="home-brand-mark" src="/static/img/icon.svg" alt=""><h1>Домашний покер</h1></div>
        <nav class="home-tools" aria-label="Инструменты">
          <a class="button secondary" href="/chips">Фишки</a>
          <a class="button secondary" href="/structure-generator">Генератор структуры</a>
        </nav>
      </header>
      <section class="home-tournaments">
        <header class="home-tournaments-header">
          <h2>Турниры</h2>
          <a class="button" href="/tournaments/new">${icon('plus')}Новый турнир</a>
        </header>
        <p class="error" id="error"></p>
        <div id="list" class="tournament-list"></div>
      </section>
    </section>`;
  const list = document.querySelector('#list');
  if (!tournaments.length) {
    const empty = element('div', 'home-empty');
    empty.append(element('strong', '', 'Турниров пока нет'), element('span', '', 'Соберите первый турнир: параметры, структура и игроки займут пару минут.'));
    const create = element('a', 'button', 'Собрать турнир'); create.href = '/tournaments/new';
    empty.append(create);
    list.append(empty);
    return;
  }
  [...tournaments]
    .sort((left, right) => (statusOrder[left.status] ?? 3) - (statusOrder[right.status] ?? 3))
    .forEach(item => list.append(tournamentRow(item)));
}

// Открытый QR-код закрывается кликом мимо него.
document.addEventListener('click', event => {
  document.querySelectorAll('.tournament-qr[open]').forEach(details => {
    if (!details.contains(event.target)) details.open = false;
  });
});

function load() {
  request('/api/v1/tournaments').then(show).catch(error => { app.textContent = error.message; });
}

load();
