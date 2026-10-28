export function connectTournament(id, onState, onConnection) {
  let socket; let retry = 1000; let stopped = false; let heartbeat; let reconnectTimer;
  const open = () => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socketUrl = protocol + '//' + location.host + '/ws/tournaments/' + encodeURIComponent(String(id));
    socket = new WebSocket(socketUrl);
    socket.onopen = () => { retry = 1000; onConnection('Онлайн'); };
    socket.onmessage = event => { const message = JSON.parse(event.data); if (message.protocol_version === 1 && (message.type === 'state_snapshot' || message.type === 'tournament_updated') && message.payload?.id) onState(message.payload); };
    socket.onclose = () => { clearInterval(heartbeat); if (!stopped) { onConnection('Переподключение…'); reconnectTimer = setTimeout(open, retry); retry = Math.min(15000, retry * 2); } };
    socket.onerror = () => socket.close();
    clearInterval(heartbeat);
    heartbeat = setInterval(() => { if (socket?.readyState === WebSocket.OPEN) socket.send('sync'); }, 15000);
  };
  open();
  return () => { stopped = true; clearInterval(heartbeat); clearTimeout(reconnectTimer); socket?.close(); };
}
export function csrfToken() { return decodeURIComponent((document.cookie.split('; ').find(value => value.startsWith('poker_csrf=')) || '').split('=')[1] || ''); }
export function requestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  if (globalThis.crypto?.getRandomValues) {
    const bytes = new Uint8Array(16); globalThis.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    return [...bytes].map((value, index) => (index === 4 || index === 6 || index === 8 || index === 10 ? '-' : '') + value.toString(16).padStart(2, '0')).join('');
  }
  return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
}
export async function command(url, body) {
  const response = await fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken()}, body: JSON.stringify({...body, request_id: requestId()}) });
  if (!response.ok) { const data = await response.json(); const error = new Error(data.detail?.message || 'Команда не выполнена.'); error.code = data.detail?.code; throw error; }
  return response.json();
}
