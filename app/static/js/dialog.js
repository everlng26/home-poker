const iconByTone = {
  neutral: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 17.5v.01M9.4 9.2a2.75 2.75 0 1 1 4.1 2.4c-.95.55-1.5 1.15-1.5 2.4"/><circle cx="12" cy="12" r="9"/></svg>',
  info: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 10v6M12 7.5v.01"/><circle cx="12" cy="12" r="9"/></svg>',
  warning: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5M12 16.5v.01M10.2 4.9 3.3 17a2 2 0 0 0 1.74 3h13.92a2 2 0 0 0 1.74-3L13.8 4.9a2.08 2.08 0 0 0-3.6 0Z"/></svg>',
  danger: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 9v7M15 9v7M5 6h14M10 6V4h4v2M7 6l1 14h8l1-14"/></svg>',
  finish: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7.5 12 3 3 6-7"/><circle cx="12" cy="12" r="9"/></svg>',
  undo: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 8-4 4 4 4M5 12h8a6 6 0 0 1 6 6"/></svg>',
  player: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3"/><path d="M6 19c.55-3.1 2.55-5 6-5s5.45 1.9 6 5"/></svg>',
  reentry: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.4 9A7 7 0 1 0 19 14M18 4v5h-5"/><circle cx="12" cy="10" r="2.2"/><path d="M8.5 17c.4-2 1.55-3.1 3.5-3.1 1.1 0 2 .35 2.65 1"/></svg>',
};

let activeDialog;

function ensureDialog() {
  let dialog = document.querySelector('#app-dialog');
  if (dialog) return dialog;

  dialog = document.createElement('dialog');
  dialog.id = 'app-dialog';
  dialog.className = 'app-dialog';
  dialog.setAttribute('aria-labelledby', 'app-dialog-title');
  dialog.setAttribute('aria-describedby', 'app-dialog-message');
  dialog.innerHTML = `
    <form class="app-dialog-card" novalidate>
      <div class="app-dialog-accent" aria-hidden="true"></div>
      <header class="app-dialog-header">
        <span class="app-dialog-icon" aria-hidden="true"></span>
        <div class="app-dialog-heading">
          <p class="app-dialog-eyebrow"></p>
          <h2 id="app-dialog-title" class="app-dialog-title"></h2>
        </div>
      </header>
      <p id="app-dialog-message" class="app-dialog-message"></p>
      <label class="app-dialog-field" hidden>
        <span class="app-dialog-field-label">PIN администратора</span>
        <input class="app-dialog-pin" type="password" inputmode="numeric" autocomplete="off" minlength="4" maxlength="12">
        <small class="app-dialog-hint">Введите PIN, заданный при создании турнира.</small>
      </label>
      <label class="app-dialog-select-field" hidden>
        <span class="app-dialog-field-label">Выбил</span>
        <select class="app-dialog-select"></select>
      </label>
      <div class="app-dialog-actions">
        <button class="app-dialog-cancel" type="button">Отмена</button>
        <button class="app-dialog-confirm" type="submit">Подтвердить</button>
      </div>
    </form>`;
  document.body.append(dialog);
  return dialog;
}

export function openDialog({
  tone = 'neutral',
  eyebrow = 'Подтверждение',
  title = 'Подтвердить действие?',
  message = '',
  confirmLabel = 'Подтвердить',
  cancelLabel = 'Отмена',
  showCancel = true,
  pin = false,
  icon = tone,
  pinLabel = 'PIN администратора',
  hint = 'Введите PIN, заданный при создании турнира.',
  select = null,
} = {}) {
  if (activeDialog) activeDialog(null);

  const dialog = ensureDialog();
  const form = dialog.querySelector('.app-dialog-card');
  const cancel = dialog.querySelector('.app-dialog-cancel');
  const confirm = dialog.querySelector('.app-dialog-confirm');
  const field = dialog.querySelector('.app-dialog-field');
  const input = dialog.querySelector('.app-dialog-pin');
  const selectField = dialog.querySelector('.app-dialog-select-field');
  const selectInput = dialog.querySelector('.app-dialog-select');
  const previousFocus = document.activeElement;
  const safeTone = iconByTone[tone] ? tone : 'neutral';
  const safeIcon = iconByTone[icon] ? icon : safeTone;

  dialog.dataset.tone = safeTone;
  dialog.classList.toggle('app-dialog-notice', !showCancel);
  dialog.querySelector('.app-dialog-icon').innerHTML = iconByTone[safeIcon];
  dialog.querySelector('.app-dialog-eyebrow').textContent = eyebrow;
  dialog.querySelector('.app-dialog-title').textContent = title;
  dialog.querySelector('.app-dialog-message').textContent = message;
  dialog.querySelector('.app-dialog-field-label').textContent = pinLabel;
  dialog.querySelector('.app-dialog-hint').textContent = hint;
  cancel.textContent = cancelLabel;
  cancel.hidden = !showCancel;
  confirm.textContent = confirmLabel;
  field.hidden = !pin;
  input.required = pin;
  input.value = '';
  selectField.hidden = !select;
  selectInput.required = Boolean(select);
  selectInput.replaceChildren();
  if (select) {
    dialog.querySelector('.app-dialog-select-field .app-dialog-field-label').textContent = select.label || 'Выберите';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = select.placeholder || 'Нажмите, чтобы выбрать игрока';
    placeholder.disabled = true;
    placeholder.selected = true;
    selectInput.append(placeholder);
    for (const optionData of select.options || []) {
      const option = document.createElement('option');
      option.value = optionData.value;
      option.textContent = optionData.label;
      selectInput.append(option);
    }
  }

  return new Promise(resolve => {
    let settled = false;

    const cleanup = () => {
      form.removeEventListener('submit', submit);
      cancel.removeEventListener('click', cancelDialog);
      dialog.removeEventListener('cancel', escapeDialog);
      dialog.removeEventListener('click', backdropDialog);
      activeDialog = undefined;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
    const settle = result => {
      if (settled) return;
      settled = true;
      if (dialog.open) dialog.close();
      cleanup();
      resolve(result);
    };
    const submit = event => {
      event.preventDefault();
      if (pin && !input.checkValidity()) {
        input.reportValidity();
        return;
      }
      if (select && !selectInput.checkValidity()) {
        selectInput.reportValidity();
        return;
      }
      settle(pin ? input.value : select ? selectInput.value : true);
    };
    const cancelDialog = () => settle(null);
    const escapeDialog = event => {
      event.preventDefault();
      settle(null);
    };
    const backdropDialog = event => {
      if (event.target === dialog) settle(null);
    };

    activeDialog = settle;
    form.addEventListener('submit', submit);
    cancel.addEventListener('click', cancelDialog);
    dialog.addEventListener('cancel', escapeDialog);
    dialog.addEventListener('click', backdropDialog);
    dialog.showModal();
    requestAnimationFrame(() => (pin ? input : confirm).focus());
  });
}

export function showNotice(options = {}) {
  return openDialog({
    tone: 'info',
    eyebrow: 'Информация',
    title: 'Готово',
    confirmLabel: 'Понятно',
    ...options,
    showCancel: false,
    pin: false,
  });
}
