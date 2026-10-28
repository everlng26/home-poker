import {openDialog, showNotice} from './dialog.js?v=20260811-2';

const app = document.querySelector('#app');
const request = async (url, options = {}) => {
  const response = await fetch(url, { headers: {'Content-Type': 'application/json'}, ...options });
  if (!response.ok) { const body = await response.json(); throw new Error(body.detail?.message || 'Не удалось выполнить действие.'); }
  return response.json();
};
function show(tournaments) {
  app.innerHTML = '<section class="card home-page"><header class="home-header"><h1>Home Poker</h1></header><section class="home-tournaments"><header class="home-tournaments-header"><h2>Турниры</h2><div class="home-primary-actions"><a class="chip-inventory-link" href="/chips">Фишки</a><a class="chip-inventory-link" href="/structure-generator">Генератор структуры</a><a class="create-tournament-link" href="/tournaments/new">Создать турнир</a></div></header><p class="error" id="error"></p><div id="list"></div></section></section>';
  const list = document.querySelector('#list');
  if (!tournaments.length) { const empty = document.createElement('p'); empty.className = 'empty-tournaments'; empty.textContent = 'Турниров пока нет.'; list.append(empty); }
  const statuses = {draft: 'Подготовка', paused: 'Пауза', running: 'Идёт', finished: 'Завершён'};
  tournaments.forEach(item => { const line = document.createElement('article'); line.className = 'tournament-card'; const title = document.createElement('h3'); title.textContent = item.name; const meta = document.createElement('div'); meta.className = 'tournament-card-meta'; const status = document.createElement('span'); status.className = 'tournament-status'; status.textContent = statuses[item.status] || item.status; meta.append(status); const actions = document.createElement('div'); actions.className = 'tournament-actions'; const display = document.createElement('a'); display.href = '/display/' + item.id; display.textContent = 'Открыть экран турнира'; const admin = document.createElement('a'); admin.className = 'secondary'; admin.href = '/login/' + item.id; admin.textContent = 'Открыть админку'; const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'danger'; remove.textContent = 'Удалить турнир'; remove.onclick = async () => { const pin = await openDialog({tone: 'danger', eyebrow: 'Опасное действие', title: 'Удалить турнир?', message: 'Будут удалены турнир «' + item.name + '», игроки и весь журнал действий. Восстановить их будет нельзя.', confirmLabel: 'Удалить турнир', pin: true}); if (pin === null) return; try { await request('/api/v1/tournaments/' + item.id + '/delete', {method: 'POST', body: JSON.stringify({pin})}); location.reload(); } catch (error) { document.querySelector('#error').textContent = error.message; await showNotice({tone: 'danger', eyebrow: 'Удаление не выполнено', title: 'Не удалось удалить турнир', message: error.message}); } }; actions.append(display, admin, remove); const adminQr = document.createElement('img'); adminQr.className = 'qr'; adminQr.alt = 'QR-код админки'; adminQr.src = '/api/v1/tournaments/' + item.id + '/qr/admin'; const qrBox = document.createElement('div'); qrBox.className = 'qr-box'; const adminLabel = document.createElement('span'); adminLabel.textContent = 'Админка для телефона'; qrBox.append(adminLabel, adminQr); line.append(title, meta, actions, qrBox); list.append(line); });
}
function polishHomeShell() {
  const homeHeader = app.querySelector('.home-header');
  homeHeader.innerHTML = '<div class="home-brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></svg></div><div class="home-header-copy"><p class="home-brand-name">Home Poker</p><p>Создавайте турниры, настраивайте структуру и управляйте игрой в одном месте.</p></div>';
  const tournamentHeader = app.querySelector('.home-tournaments-header');
  const title = tournamentHeader.querySelector('h2');
  const intro = document.createElement('div');
  intro.className = 'home-tournaments-copy';
  const eyebrow = document.createElement('p');
  eyebrow.className = 'eyebrow';
  eyebrow.textContent = 'Игровая зона';
  const description = document.createElement('p');
  description.className = 'home-section-copy';
  description.textContent = 'Выберите турнир или создайте новый.';
  intro.append(eyebrow, title, description);
  tournamentHeader.prepend(intro);
  const empty = app.querySelector('.empty-tournaments');
  if (empty) {
    empty.className = 'home-empty';
    empty.innerHTML = '<strong>Турниров пока нет</strong><span>Создайте первый турнир, чтобы начать игру.</span>';
  }
}

request('/api/v1/tournaments').then(tournaments => { show(tournaments); polishHomeShell(); }).catch(error => { app.textContent = error.message; });
