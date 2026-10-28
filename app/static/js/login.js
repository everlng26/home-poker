const root = document.querySelector('#login-page');
const tournamentId = root.dataset.tournamentId;
const form = root.querySelector('#login');
const pin = root.querySelector('#pin');
const error = root.querySelector('#login-error');
const submit = root.querySelector('.login-submit');

// Если этот браузер уже вошёл в админку турнира (например, по QR с табло), PIN не спрашиваем.
fetch('/api/v1/tournaments/' + tournamentId + '/session')
  .then(response => response.ok ? response.json() : null)
  .then(session => { if (session?.authenticated) location.replace('/admin/' + tournamentId); })
  .catch(() => {});

pin.focus();
pin.addEventListener('input', () => { error.textContent = ''; });

form.addEventListener('submit', async event => {
  event.preventDefault();
  error.textContent = '';
  submit.disabled = true;
  submit.textContent = 'Проверяем PIN…';
  try {
    const response = await fetch('/api/v1/tournaments/' + tournamentId + '/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pin: pin.value}),
    });
    if (!response.ok) {
      error.textContent = 'Неверный PIN. Проверьте код и попробуйте снова.';
      pin.select();
      return;
    }
    location.href = '/admin/' + tournamentId;
  } catch {
    error.textContent = 'Не удалось подключиться к серверу. Проверьте, что он запущен.';
  } finally {
    submit.disabled = false;
    submit.textContent = 'Войти';
  }
});
