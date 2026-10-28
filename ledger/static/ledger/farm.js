(() => {
  const rules = JSON.parse(document.getElementById('spray-product-rules').textContent);
  const rows = document.getElementById('spray-rows');
  const total = document.getElementById('id_form-TOTAL_FORMS');
  document.getElementById('add-spray-product').addEventListener('click', () => {
    if (Number(total.value) >= 100) return;
    rows.insertAdjacentHTML('beforeend', document.getElementById('spray-empty').innerHTML.replaceAll('__prefix__', total.value));
    total.value = Number(total.value) + 1;
  });
  function suggest() {
    const box = document.getElementById('interval-suggestions');
    box.replaceChildren(document.createTextNode('Fechas orientativas según configuración. Revisa las condiciones técnicas antes de elegir una próxima fecha. '));
    const input = document.getElementById('id_scheduled_at').value;
    if (!input) return;
    rows.querySelectorAll('select').forEach(select => {
      const rule = rules.find(r => String(r.id) === select.value);
      const deleted = select.closest('.spray-row').querySelector('input[name$="-DELETE"]');
      if (!rule || !rule.interval_days || deleted?.checked) return;
      const date = new Date(input);
      date.setDate(date.getDate() + rule.interval_days);
      const pad = n => String(n).padStart(2, '0');
      const value = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'btn btn-ghost';
      button.textContent = `${rule.name}: ${date.toLocaleDateString('es-CO')} (${rule.interval_source})`;
      button.addEventListener('click', () => { document.getElementById('id_next_at').value = value; });
      box.append(button);
    });
  }
  rows.addEventListener('change', e => {
    if (e.target.matches('select')) {
      const rule = rules.find(r => String(r.id) === e.target.value);
      const unit = e.target.closest('.spray-row').querySelector('input[name$="-unit"]');
      if (rule && !unit.value) unit.value = rule.unit;
    }
    suggest();
  });
  document.getElementById('id_scheduled_at').addEventListener('change', suggest);
  suggest();
})();
