import {connectTournament} from './live.js';

const root = document.querySelector('#display');
const id = root.dataset.tournamentId;
let state;
let audioContext;
let audioEnabled = true;
let warnedMinute = false;
let cursorTimer;
let upcomingScrollLevel;
let upcomingStructureSignature = '';
let tickerSignature = '';
let tickerResizeTimer;
let upcomingResizeTimer;
let eventPopupTimer;
let eventPopupTransitionTimer;
let eventPopupAnimationFrame;
let eventPopupVisible = false;
let finishCelebrationPending = false;
let wakeLock = null;
const eventPopupQueue = [];

const clock = seconds => String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
const number = value => value === null || value === undefined ? '—' : Math.round(value).toLocaleString('ru-RU');
const money = value => number(value) + ' ' + (state?.currency_label || '₽');
const plural = (value, one, few, many) => {
  const mod100 = value % 100; const mod10 = value % 10;
  return mod100 >= 11 && mod100 <= 14 ? many : mod10 === 1 ? one : mod10 >= 2 && mod10 <= 4 ? few : many;
};

function tone(frequency, duration = 0.18, delay = 0, volume = 0.045, wave = 'sine') {
  if (!audioEnabled || !audioContext) return;
  const startsAt = audioContext.currentTime + delay;
  const oscillator = audioContext.createOscillator();
  const gain = audioContext.createGain();
  oscillator.type = wave;
  oscillator.frequency.setValueAtTime(frequency, startsAt);
  gain.gain.setValueAtTime(0.0001, startsAt);
  gain.gain.exponentialRampToValueAtTime(volume, startsAt + Math.min(0.035, duration / 4));
  gain.gain.exponentialRampToValueAtTime(0.0001, startsAt + duration);
  oscillator.connect(gain).connect(audioContext.destination);
  oscillator.start(startsAt);
  oscillator.stop(startsAt + duration + 0.03);
}

function playCue(name) {
  const cues = {
    enabled: [[660, .12, 0, .035]],
    minute: [[659, .16, 0, .045], [784, .22, .2, .05]],
    level: [[523, .16, 0, .04], [659, .18, .18, .045], [784, .26, .38, .05]],
    breakStart: [[587, .2, 0, .04], [494, .24, .22, .045], [392, .32, .46, .05]],
    breakEnd: [[392, .18, 0, .04], [523, .2, .2, .045], [659, .28, .42, .05]],
    pause: [[523, .18, 0, .04], [392, .3, .22, .045]],
    resume: [[392, .18, 0, .04], [523, .28, .22, .05]],
    playerRegistered: [[440, .13, 0, .035], [554, .2, .15, .04]],
    playerEliminated: [[440, .15, 0, .038], [330, .24, .17, .043]],
    reentry: [[392, .13, 0, .035], [523, .15, .15, .04], [659, .22, .32, .045]],
    bubble: [[392, .18, 0, .04], [494, .2, .2, .045], [587, .3, .42, .05]],
    itm: [[523, .17, 0, .04], [659, .2, .18, .048], [880, .34, .4, .055]],
    finished: [[523, .22, 0, .045], [659, .24, .2, .05], [784, .28, .42, .055], [1047, .55, .68, .06]],
  };
  (cues[name] || []).forEach(([frequency, duration, delay, volume]) => {
    tone(frequency, duration, delay, volume, name === 'pause' || name === 'breakStart' ? 'triangle' : 'sine');
  });
}

async function enableAudio(playConfirmation = true) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return false;
  if (!audioContext) audioContext = new AudioContextClass();
  await audioContext.resume();
  audioEnabled = true;
  updateAudioButton();
  if (playConfirmation) playCue('enabled');
  return true;
}

function updateAudioButton() {
  const button = root.querySelector('#display-sound');
  if (!button) return;
  button.classList.toggle('is-active', audioEnabled);
  button.setAttribute('aria-pressed', String(audioEnabled));
  button.title = audioEnabled ? 'Выключить звуки табло' : 'Включить звуки табло';
  button.setAttribute('aria-label', button.title);
}

function renderFinishConfetti() {
  const confetti = root.querySelector('#finish-celebration-confetti');
  confetti.replaceChildren();
  for (let index = 0; index < 56; index += 1) {
    const piece = document.createElement('i');
    const duration = 5.2 + (index % 8) * 0.34;
    piece.style.setProperty('--x', ((index * 37 + 11) % 101) + '%');
    piece.style.setProperty('--drift', (((index * 29) % 90) - 45) + 'px');
    piece.style.setProperty('--delay', (-((index * 0.43) % duration)) + 's');
    piece.style.setProperty('--duration', duration + 's');
    piece.style.setProperty('--rotation', (260 + (index % 7) * 55) + 'deg');
    piece.dataset.tone = String(index % 4);
    piece.dataset.shape = String(index % 3);
    confetti.append(piece);
  }
}

function stopFinishCelebration() {
  clearPublicEventPopups();
  const overlay = root.querySelector('#finish-celebration');
  overlay.classList.remove('is-visible');
  overlay.setAttribute('aria-hidden', 'true');
  root.classList.remove('celebrating');
  root.querySelector('#finish-celebration-confetti').replaceChildren();
}

function launchFinishCelebration() {
  const overlay = root.querySelector('#finish-celebration');
  overlay.classList.add('is-visible');
  overlay.setAttribute('aria-hidden', 'false');
  root.classList.add('celebrating');
  renderFinishConfetti();
}

function levelText(level) {
  if (!level) return '—';
  if (level.kind === 'break') return 'Перерыв';
  return [level.small_blind, level.big_blind, state?.ante_enabled ? level.ante : null]
    .filter(value => value !== null && value !== undefined)
    .map(number)
    .join(' / ');
}

function drawBlinds(level) {
  const blinds = root.querySelector('#blinds');
  blinds.replaceChildren();
  if (!level) { blinds.textContent = '—'; return; }
  if (level.kind === 'break') {
    const next = state.levels.find(item => item.order_index > level.order_index && item.kind === 'play');
    root.querySelector('#blinds-label').textContent = 'После перерыва';
    level = next;
    if (!level) { blinds.textContent = '—'; return; }
  } else {
    root.querySelector('#blinds-label').textContent = 'Блайнды';
  }
  const main = document.createElement('span');
  main.className = 'blinds-main';
  main.textContent = number(level.small_blind) + ' / ' + number(level.big_blind);
  blinds.append(main);
  if (state.ante_enabled && level.ante) {
    const ante = document.createElement('span');
    ante.className = 'blinds-ante';
    ante.textContent = 'анте ' + number(level.ante);
    blinds.append(ante);
  }
}

function updateTimerVisual() {
  if (!state) return;
  const current = state.current_level;
  const remaining = Math.max(0, state.remaining_seconds || 0);
  const duration = Math.max(0, current?.duration_seconds || 0);
  const progress = duration ? Math.min(100, Math.max(0, (remaining / duration) * 100)) : 0;
  const paused = state.timer_status !== 'running';
  root.querySelector('#timer-label').textContent = state.status === 'draft'
    ? 'турнир ещё не начат'
    : paused ? 'пауза'
    : current?.kind === 'break' ? 'до конца перерыва' : 'до конца уровня';
  root.querySelector('#time').textContent = clock(remaining);
  root.querySelector('#timer-progress-bar').style.width = progress + '%';
  root.classList.toggle('is-last-minute', !paused && state.status !== 'finished' && current?.kind === 'play' && remaining <= 60);
}

function statusText() {
  if (state.status === 'finished') return 'Турнир окончен';
  if (state.current_level?.kind === 'break') return 'Перерыв';
  return null;
}

function registrationText() {
  if (state.status === 'finished') return null;
  if (state.late_registration_phase === 'closed') return 'Регистрация закрыта, игра на вылет';
  if (state.late_registration_phase === 'closing') return 'Поздняя регистрация заканчивается после этого уровня';
  if (state.late_registration_phase === 'next_level') return 'Поздняя регистрация заканчивается после следующего уровня';
  return 'Поздняя регистрация открыта';
}

function publicEventText() {
  const event = state.public_latest_event;
  if (!event?.player_name) return null;
  const playerName = event.player_name;
  if (event.type === 'player_registered') return playerName + ' входит в игру';
  if (event.type === 'player_eliminated' && event.killer_name) {
    return {kind: 'ko', killer: event.killer_name, eliminated: playerName};
  }
  if (event.type === 'player_eliminated') return playerName + ' вылетает';
  if (event.type === 'reentry_added') return playerName + ' делает ре-энтри';
  return null;
}

function publicStageText() {
  const stage = state.public_stage;
  if (!stage) return null;
  if (stage.type === 'three_players_left') return 'Осталось 3 игрока';
  if (stage.type === 'heads_up') return 'Хедз-ап';
  if (stage.type === 'winner' && stage.player_name) return 'Победитель: ' + stage.player_name;
  return null;
}

function payoutStageText() {
  if (!state.payouts?.configured || state.status === 'finished') return null;
  if (state.payouts.stage === 'bubble') return 'Баббл: следующий вылет без приза';
  if (state.payouts.stage === 'itm') return 'Все оставшиеся игроки в призах';
  return null;
}

function winnerText() {
  const winner = state.standings?.find(player => player.place === 1);
  const winnerName = winner?.name || (state.public_stage?.type === 'winner' ? state.public_stage.player_name : null);
  return winnerName ? 'Победитель: ' + winnerName : 'Турнир окончен';
}

function appendTickerSequence(group, tickerItems) {
  tickerItems.forEach(value => {
    const item = document.createElement('span');
    item.className = 'ticker-item';
    if (typeof value === 'object' && value.kind === 'ko') {
      item.classList.add('ticker-ko-event');
      // Имена не склоняются, поэтому фраза построена так, чтобы оба имени стояли в именительном падеже.
      item.setAttribute('aria-label', value.eliminated + ' вылетает, баунти забирает ' + value.killer);
      const badge = document.createElement('span');
      badge.className = 'ticker-ko-badge';
      badge.textContent = 'K.O.';
      const eliminated = document.createElement('strong');
      eliminated.textContent = value.eliminated;
      const verb = document.createElement('span');
      verb.className = 'ticker-ko-verb';
      verb.textContent = 'вылетает, баунти забирает';
      const killer = document.createElement('strong');
      killer.textContent = value.killer;
      item.append(badge, eliminated, verb, killer);
    } else {
      item.textContent = value;
    }
    group.append(item);
    const separator = document.createElement('span');
    separator.className = 'ticker-separator';
    separator.textContent = '•';
    separator.setAttribute('aria-hidden', 'true');
    group.append(separator);
  });
}

function drawTicker(force = false) {
  const track = root.querySelector('#display-ticker-track');
  const tickerItems = state.status === 'finished'
    ? [winnerText()]
    : state.timer_status === 'paused' && state.status !== 'draft'
    ? ['Турнир на паузе']
    : [statusText(), registrationText(), payoutStageText(), publicStageText(), publicEventText()].filter(Boolean);
  const signature = tickerItems.map(item => typeof item === 'string' ? item : JSON.stringify(item)).join('\u0000');
  if (!force && tickerSignature === signature && track.childElementCount === 2) return;
  tickerSignature = signature;

  const viewport = track.closest('.ticker-viewport');
  const group = document.createElement('div');
  group.className = 'ticker-group';
  appendTickerSequence(group, tickerItems);
  track.replaceChildren(group);

  const minimumGroupWidth = (viewport?.clientWidth || 0) + 32;
  while (group.scrollWidth < minimumGroupWidth) appendTickerSequence(group, tickerItems);
  track.append(group.cloneNode(true));
}

function secondsUntilBreak() {
  const current = state.levels.findIndex(level => level.order_index === state.current_level_index);
  if (current < 0) return null;
  const breakIndex = state.levels.findIndex((level, index) => index > current && level.kind === 'break');
  if (breakIndex < 0) return null;
  return state.remaining_seconds + state.levels.slice(current + 1, breakIndex).reduce((sum, level) => sum + (level.duration_seconds || 0), 0);
}

function upcomingSignature() {
  return [state.ante_enabled, ...state.levels.map(level => [
    level.order_index,
    level.kind,
    level.level_number,
    level.small_blind,
    level.big_blind,
    level.ante,
    level.duration_seconds,
  ].join(':'))].join('|');
}

function fitUpcomingViewport(container) {
  const items = [...container.children];
  if (!items.length) return;
  container.style.removeProperty('height');
  container.style.removeProperty('flex');
  const availableHeight = container.clientHeight;
  const rowHeight = items[0].offsetHeight;
  const rowStep = items[1]
    ? items[1].offsetTop - items[0].offsetTop
    : rowHeight + (Number.parseFloat(getComputedStyle(container).rowGap) || 0);
  const gap = Math.max(0, rowStep - rowHeight);
  const visibleRows = Math.max(1, Math.min(items.length, Math.floor((availableHeight + gap) / rowStep)));
  const viewportHeight = (visibleRows - 1) * rowStep + rowHeight;
  container.style.height = viewportHeight + 'px';
  container.style.flex = '0 0 ' + viewportHeight + 'px';
}

function scrollUpcomingToCurrent(container) {
  const activeItem = container.querySelector('.upcoming-item.current');
  const firstItem = container.firstElementChild;
  if (!activeItem || !firstItem) return;
  const target = Math.max(0, activeItem.offsetTop - firstItem.offsetTop);
  const maximum = Math.max(0, container.scrollHeight - container.clientHeight);
  const nextTop = Math.min(target, maximum);
  if (Math.abs(container.scrollTop - nextTop) < 1) return;
  container.scrollTo({top: nextTop, behavior: 'auto'});
}

function scheduleUpcomingAlignment(delay = 0) {
  clearTimeout(upcomingResizeTimer);
  upcomingResizeTimer = setTimeout(() => {
    if (!state) return;
    const container = root.querySelector('#upcoming-levels');
    fitUpcomingViewport(container);
    scrollUpcomingToCurrent(container);
  }, delay);
}

function drawUpcoming() {
  const container = root.querySelector('#upcoming-levels');
  const levelChanged = upcomingScrollLevel !== state.current_level_index;
  const structureSignature = upcomingSignature();
  const structureChanged = structureSignature !== upcomingStructureSignature;

  if (structureChanged) {
    const fragment = document.createDocumentFragment();
    state.levels.forEach(level => {
      const item = document.createElement('div');
      item.dataset.levelIndex = String(level.order_index);
      item.className = 'upcoming-item' + (level.kind === 'break' ? ' break' : '');
      const marker = document.createElement('span');
      marker.className = 'upcoming-marker';
      const label = document.createElement('span');
      label.textContent = level.kind === 'break' ? 'Перерыв' : String(level.level_number);
      const value = document.createElement('strong');
      value.textContent = level.kind === 'break' ? '' : levelText(level);
      const duration = document.createElement('small');
      duration.textContent = Math.round((level.duration_seconds || 0) / 60) + ' мин';
      item.append(marker, label, value, duration);
      fragment.append(item);
    });
    container.replaceChildren(fragment);
    upcomingStructureSignature = structureSignature;
  }

  if (structureChanged || levelChanged) {
    [...container.children].forEach(item => {
      const active = Number(item.dataset.levelIndex) === state.current_level_index;
      item.classList.toggle('current', active);
      if (active) item.setAttribute('aria-current', 'step');
      else item.removeAttribute('aria-current');
    });
    if (structureChanged) fitUpcomingViewport(container);
    scrollUpcomingToCurrent(container);
    upcomingScrollLevel = state.current_level_index;
  }
}

function nextItems() {
  const current = state.levels.findIndex(level => level.order_index === state.current_level_index);
  const onBreak = state.current_level?.kind === 'break';
  // На перерыве крупно показан уровень после него, поэтому строкой ниже идёт следующий за ним.
  const next = onBreak
    ? state.levels.slice(current + 1).filter(level => level.kind === 'play')[1]
    : state.levels[current + 1];
  root.querySelector('#next-level-label').textContent = onBreak ? 'Затем' : 'Дальше';
  root.querySelector('#next-level').textContent = !next ? 'конец структуры'
    : next.kind === 'break' ? 'перерыв ' + Math.round((next.duration_seconds || 0) / 60) + ' мин'
    : levelText(next);
  const breakSeconds = secondsUntilBreak();
  root.querySelector('#break-time').textContent = breakSeconds === null ? '—' : clock(breakSeconds);
  drawUpcoming();
}

function publicEventSignature(event) {
  if (!event) return '';
  return [event.type, event.player_name, event.created_at].join('|');
}

function newPublicEvent(old) {
  const event = state.public_latest_event;
  const previousEvent = old.public_latest_event;
  if (!event || publicEventSignature(event) === publicEventSignature(previousEvent)) return null;
  if (previousEvent && new Date(event.created_at) <= new Date(previousEvent.created_at)) return null;
  return event;
}

function newPayoutEvent(old) {
  const event = state.public_payout_event;
  const previous = old.public_payout_event;
  if (!event || event.id === previous?.id) return null;
  if (previous && event.id < previous.id) return null;
  if (event.type === 'bubble_reached') {
    return {
      ...event,
      player_name: event.active_players + ' ' + plural(event.active_players, 'игрок', 'игрока', 'игроков')
        + ', ' + event.paid_places + ' ' + plural(event.paid_places, 'призовое место', 'призовых места', 'призовых мест'),
    };
  }
  if (event.type === 'itm_reached') {
    return {...event, player_name: 'Все оставшиеся игроки получают выплаты'};
  }
  return null;
}

function publicEventPresentation(event) {
  if (event?.type === 'player_eliminated' && event.killer_name) {
    return {label: 'K.O.', icon: 'K.O.', tone: 'ko'};
  }
  const presentations = {
    player_registered: {label: 'Входит в игру', icon: '#i-plus', tone: 'entry'},
    player_eliminated: {label: 'Вылетает', icon: '#i-close', tone: 'eliminated'},
    reentry_added: {label: 'Делает ре-энтри', icon: '#i-reentry', tone: 'reentry'},
    late_registration_closing: {label: 'Поздняя регистрация', icon: '#i-timer', tone: 'registration'},
    bubble_reached: {label: 'Баббл', icon: '♠', tone: 'bubble'},
    itm_reached: {label: 'В призах', icon: '₽', tone: 'itm'},
  };
  return presentations[event?.type] || null;
}

function showNextPublicEventPopup() {
  if (eventPopupVisible) return;
  if (!eventPopupQueue.length) {
    if (finishCelebrationPending) completePendingFinishCelebration();
    return;
  }
  const event = eventPopupQueue.shift();
  const presentation = publicEventPresentation(event);
  if (!presentation || !event?.player_name) {
    showNextPublicEventPopup();
    return;
  }

  const popup = root.querySelector('#display-event-popup');
  eventPopupVisible = true;
  popup.dataset.tone = presentation.tone;
  const icon = popup.querySelector('#display-event-popup-icon');
  if (presentation.icon.startsWith('#')) {
    icon.innerHTML = '<svg aria-hidden="true"><use href="' + presentation.icon + '"/></svg>';
  } else {
    icon.textContent = presentation.icon;
  }
  const label = popup.querySelector('#display-event-popup-label');
  const player = popup.querySelector('#display-event-popup-player');
  label.replaceChildren();
  player.replaceChildren();
  if (presentation.tone === 'ko') {
    label.textContent = event.player_name + ' вылетает, баунти забирает';
    const killer = document.createElement('span');
    killer.className = 'display-event-popup-ko-name';
    killer.textContent = event.killer_name;
    const bounty = document.createElement('b');
    bounty.className = 'display-event-popup-bounty';
    bounty.textContent = '+' + money(event.bounty_amount_awarded);
    player.append(killer, bounty);
    player.setAttribute('aria-label', event.player_name + ' вылетает, баунти забирает ' + event.killer_name);
  } else {
    label.textContent = presentation.label;
    player.textContent = event.player_name;
    player.removeAttribute('aria-label');
  }
  popup.setAttribute('aria-hidden', 'false');
  eventPopupAnimationFrame = requestAnimationFrame(() => {
    popup.classList.add('is-visible');
    playPublicEventCue(event);
  });

  clearTimeout(eventPopupTimer);
  eventPopupTimer = setTimeout(() => {
    popup.classList.remove('is-visible');
    popup.setAttribute('aria-hidden', 'true');
    clearTimeout(eventPopupTransitionTimer);
    eventPopupTransitionTimer = setTimeout(() => {
      eventPopupVisible = false;
      showNextPublicEventPopup();
    }, 320);
  }, 3600);
}

function clearPublicEventPopups() {
  clearTimeout(eventPopupTimer);
  clearTimeout(eventPopupTransitionTimer);
  cancelAnimationFrame(eventPopupAnimationFrame);
  eventPopupQueue.length = 0;
  eventPopupVisible = false;
  finishCelebrationPending = false;
  const popup = root.querySelector('#display-event-popup');
  popup.classList.remove('is-visible');
  popup.setAttribute('aria-hidden', 'true');
}

function queuePublicEventPopup(event) {
  if (!publicEventPresentation(event) || !event?.player_name) return;
  eventPopupQueue.push(event);
  showNextPublicEventPopup();
}

function playPublicEventCue(event) {
  if (event.type === 'player_registered') playCue('playerRegistered');
  else if (event.type === 'player_eliminated') playCue('playerEliminated');
  else if (event.type === 'reentry_added') playCue('reentry');
  else if (event.type === 'bubble_reached') playCue('bubble');
  else if (event.type === 'itm_reached') playCue('itm');
}

function completePendingFinishCelebration() {
  finishCelebrationPending = false;
  launchFinishCelebration();
  playCue('finished');
}

function handleStateTransition(old, current) {
  if (!old) {
    if (state.status === 'finished') launchFinishCelebration();
    return;
  }
  const levelChanged = old.current_level_index !== state.current_level_index;
  const finishedNow = old.status !== 'finished' && state.status === 'finished';
  const statusChanged = old.timer_status !== state.timer_status;
  const publicEvent = newPublicEvent(old);
  const payoutEvent = newPayoutEvent(old);

  if (old.status === 'finished' && state.status !== 'finished') stopFinishCelebration();
  if (levelChanged || state.remaining_seconds > 60) warnedMinute = false;
  if (finishedNow) {
    if (publicEvent) queuePublicEventPopup(publicEvent);
    if (payoutEvent) queuePublicEventPopup(payoutEvent);
    finishCelebrationPending = true;
    if (!eventPopupVisible && !eventPopupQueue.length) completePendingFinishCelebration();
    return;
  }
  if (publicEvent) {
    queuePublicEventPopup(publicEvent);
  }
  if (payoutEvent) {
    queuePublicEventPopup(payoutEvent);
  }
  if (
    levelChanged
    && current?.kind === 'play'
    && current.order_index === state.late_registration_end_level_index
  ) {
    queuePublicEventPopup({
      type: 'late_registration_closing',
      player_name: 'Заканчивается после этого уровня',
    });
  }
  if (levelChanged) {
    if (current?.kind === 'break') playCue('breakStart');
    else if (old.current_level?.kind === 'break') playCue('breakEnd');
    else playCue('level');
    return;
  }
  if (statusChanged) {
    if (state.timer_status === 'paused') playCue('pause');
    else if (old.timer_status === 'paused' && state.timer_status === 'running') playCue('resume');
    return;
  }
  if (
    state.timer_status === 'running'
    && old.remaining_seconds > 60
    && state.remaining_seconds <= 60
    && !warnedMinute
  ) {
    playCue('minute');
    warnedMinute = true;
  }
}

function draw(next) {
  if (!next?.id) return;
  const old = state;
  state = next;
  root.querySelector('#prize-pool-metric').hidden = Boolean(state.is_freeroll);
  root.classList.toggle('display-freeroll', Boolean(state.is_freeroll));
  root.classList.toggle('display-break', state.current_level?.kind === 'break');
  root.classList.toggle('display-paused', state.timer_status === 'paused' && state.status !== 'finished');
  root.classList.toggle('finished', state.status === 'finished');
  const showAdminQr = state.status === 'draft';
  root.classList.toggle('display-awaiting-start', showAdminQr);
  root.querySelector('#display-admin-qr').hidden = !showAdminQr;
  const current = state.current_level;
  const live = state.timer_status === 'running';
  root.querySelector('#name').textContent = state.name;
  root.querySelector('#status').textContent = state.status === 'finished' ? 'Завершён'
    : state.status === 'draft' ? 'Не начат'
    : !live ? 'Пауза'
    : current?.kind === 'break' ? 'Перерыв' : 'Идёт';
  root.querySelector('#level').textContent = current?.kind === 'break' ? 'Перерыв' : current ? 'Уровень ' + current.level_number : 'Нет уровней';
  updateTimerVisual();
  drawBlinds(current);
  root.querySelector('#active-players').textContent = state.status === 'draft'
    ? number(state.metrics.registered_players)
    : number(state.metrics.active_players) + ' из ' + number(state.metrics.registered_players);
  root.querySelector('#total-entries').textContent = number(state.metrics.total_entries);
  root.querySelector('#prize-pool').textContent = money(state.metrics.prize_pool);
  const averageStack = root.querySelector('#average-stack');
  averageStack.textContent = number(state.metrics.average_stack);
  if (state.metrics.average_stack_bb) {
    const depth = document.createElement('small');
    depth.textContent = Math.round(state.metrics.average_stack_bb) + ' BB';
    averageStack.append(depth);
  }
  const koLeader = root.querySelector('#display-ko-leader');
  const showKoLeader = state.bounty_mode === 'fixed' && Boolean(state.ko_leader) && state.status !== 'finished';
  koLeader.hidden = !showKoLeader;
  if (showKoLeader) {
    root.querySelector('#display-ko-leader-label').textContent = 'Больше всех K.O.';
    root.querySelector('#display-ko-leader-value').textContent = state.ko_leader.names[0] + ', ' + state.ko_leader.ko_count;
  }
  const payoutPanel = root.querySelector('#display-payouts');
  const showPayouts = !state.is_freeroll && state.payouts?.configured && state.payouts.status === 'final' && state.status !== 'finished';
  payoutPanel.hidden = !showPayouts;
  root.classList.toggle('display-has-payouts', showPayouts);
  if (showPayouts) {
    root.querySelector('#display-paid-places').textContent = state.payouts.paid_places + ' '
      + plural(state.payouts.paid_places, 'призовое место', 'призовых места', 'призовых мест');
    const lines = root.querySelector('#display-payout-lines'); lines.replaceChildren();
    state.payouts.lines.slice(0, 3).forEach(line => {
      const item = document.createElement('p');
      const place = document.createElement('span'); place.textContent = line.place + ' место';
      const amount = document.createElement('b'); amount.textContent = money(line.amount);
      item.append(place, amount); lines.append(item);
    });
  }
  const finalResults = root.querySelector('#final-results');
  finalResults.hidden = state.status !== 'finished';
  if (state.status === 'finished') {
    const standings = root.querySelector('#standings');
    const winner = state.standings.find(player => player.place === 1);
    root.querySelector('#display-winner-name').textContent = winner?.name || '—';
    const finalKoLeader = root.querySelector('#display-final-ko-leader');
    finalKoLeader.hidden = state.bounty_mode !== 'fixed' || !state.ko_leader;
    if (!finalKoLeader.hidden) finalKoLeader.textContent = 'Больше всех K.O.: ' + state.ko_leader.names[0] + ', ' + state.ko_leader.ko_count;
    standings.replaceChildren();
    state.standings.forEach(player => {
      const row = document.createElement('article');
      row.className = 'display-standing-row' + (player.place ? ' place-' + player.place : '');
      const place = document.createElement('span');
      place.className = 'standing-place' + (player.place ? ' place-' + player.place : '');
      place.textContent = player.place || '—';
      const identity = document.createElement('div');
      identity.className = 'standing-identity';
      const name = document.createElement('strong');
      name.textContent = player.name;
      identity.append(name);
      if (!state.is_freeroll) {
        const entries = document.createElement('small'); entries.textContent = 'Входов: ' + player.entries_count;
        identity.append(entries);
      }
      if (state.bounty_mode === 'fixed') {
        const bounty = document.createElement('small'); bounty.textContent = 'K.O.: ' + player.ko_count + ', баунти ' + money(player.bounty_winnings);
        identity.append(bounty);
      }
      row.append(place, identity);
      if (state.is_freeroll || player.winnings > 0) {
        const result = document.createElement('span');
        result.className = 'standing-reentries';
        result.textContent = state.is_freeroll ? 'Входов: ' + player.entries_count : money(player.winnings);
        row.append(result);
      } else {
        row.classList.add('without-payout');
      }
      standings.append(row);
    });
  }
  drawTicker(); nextItems();
  handleStateTransition(old, current);
}

function tick() {
  if (!state || state.timer_status !== 'running') return;
  const before = state.remaining_seconds;
  state.remaining_seconds = Math.max(0, before - 1);
  updateTimerVisual();
  const breakSeconds = secondsUntilBreak();
  root.querySelector('#break-time').textContent = breakSeconds === null ? '—' : clock(breakSeconds);
  if (audioEnabled && before > 60 && state.remaining_seconds <= 60 && !warnedMinute) {
    playCue('minute');
    warnedMinute = true;
  }
}

root.querySelector('#display-activate').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen?.();
    else await root.requestFullscreen?.();
  } catch (error) {
    console.debug('Полноэкранный режим недоступен.', error);
  }
  if (audioEnabled && !audioContext) await enableAudio(false);
};

root.querySelector('#display-sound').onclick = async () => {
  if (audioEnabled) {
    audioEnabled = false;
    updateAudioButton();
    return;
  }
  try {
    await enableAudio();
  } catch (error) {
    console.debug('Звуки табло недоступны.', error);
  }
};

document.addEventListener('pointerdown', event => {
  if (!audioEnabled || audioContext || event.target.closest('#display-sound')) return;
  enableAudio(false).catch(error => console.debug('Звуки табло недоступны.', error));
}, {capture: true});

document.addEventListener('fullscreenchange', () => {
  const button = root.querySelector('#display-activate');
  const active = Boolean(document.fullscreenElement);
  button.title = active ? 'Выйти из полного экрана' : 'Открыть полный экран';
  button.setAttribute('aria-label', button.title);
  button.querySelector('use').setAttribute('href', active ? '#i-collapse' : '#i-expand');
  if (active) scheduleUpcomingAlignment(120);
});

const ticker = root.querySelector('.display-ticker');
ticker.addEventListener('pointerdown', () => ticker.classList.add('is-paused'));
ticker.addEventListener('pointerup', () => ticker.classList.remove('is-paused'));
ticker.addEventListener('pointercancel', () => ticker.classList.remove('is-paused'));

window.addEventListener('resize', () => {
  clearTimeout(tickerResizeTimer);
  tickerResizeTimer = setTimeout(() => {
    if (state) drawTicker(true);
  }, 120);
  scheduleUpcomingAlignment(120);
});

document.addEventListener('mousemove', () => { document.body.classList.remove('cursor-hidden'); clearTimeout(cursorTimer); cursorTimer = setTimeout(() => document.body.classList.add('cursor-hidden'), 3000); });

const updateDeviceTime = () => {
  const now = new Date();
  const deviceTime = root.querySelector('#device-time');
  deviceTime.dateTime = now.toISOString();
  deviceTime.textContent = now.toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  });
};

// Табло может работать на iPad или втором ноутбуке без caffeinate: не даём экрану погаснуть.
async function keepScreenAwake() {
  if (!('wakeLock' in navigator) || document.visibilityState !== 'visible' || wakeLock) return;
  try {
    wakeLock = await navigator.wakeLock.request('screen');
    wakeLock.addEventListener('release', () => { wakeLock = null; });
  } catch (error) {
    console.debug('Экран может погаснуть: блокировка сна недоступна.', error);
  }
}
document.addEventListener('visibilitychange', keepScreenAwake);
document.addEventListener('pointerdown', keepScreenAwake, {once: true});
keepScreenAwake();

updateDeviceTime();
updateAudioButton();
connectTournament(id, draw, () => {});
setInterval(tick, 1000);
setInterval(updateDeviceTime, 1000);
