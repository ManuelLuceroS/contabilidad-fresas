/* Procesa la cola persistida, un destinatario por solicitud y sin reenvíos ciegos. */
(async () => {
  const queue = document.querySelector('[data-wa-queue]');
  if (!queue || queue.dataset.enabled !== '1') return;
  const csrf = document.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
  if (!csrf) return;
  for (const row of queue.querySelectorAll('[data-wa-id]')) {
    if (!['pending', 'blocked'].includes(row.dataset.state)) continue;
    const label = row.querySelector('[data-wa-label]');
    const detail = row.querySelector('[data-wa-detail]');
    label.textContent = 'Procesando…';
    try {
      const response = await fetch(`/whatsapp/envios/${row.dataset.waId}/procesar/`, {
        method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf}
      });
      if (!response.ok) throw new Error();
      const result = await response.json();
      row.dataset.state = result.status;
      label.textContent = result.label;
      detail.textContent = result.detail;
    } catch {
      label.textContent = 'Estado por consultar';
      detail.textContent = 'Recarga para consultar el resultado. No se reenvía automáticamente un intento sin confirmar.';
    }
  }
})();
