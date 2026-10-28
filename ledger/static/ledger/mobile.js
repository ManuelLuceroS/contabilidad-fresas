/* La cola se confirma en IndexedDB antes de mostrar «guardado». No usa el token del servidor. */
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const MAX = 99999999999999n;
  let db, catalog, queue = [], mode = 'sale', syncing = false, identityMismatch = false, cloudReachable;
  const owner = crypto.randomUUID();
  const label = {sale: 'Venta', payment: 'Abono', expense: 'Gasto'};
  function note(message) { $('notice').textContent = message; }
  function units(value, places = 2) {
    const text = String(value).trim();
    if (!(places === 0 ? /^\d+$/ : new RegExp(`^\\d+(?:\\.\\d{1,${places}})?$`)).test(text))
      throw Error('Revisa el valor y la cantidad de decimales.');
    const [whole, fraction = ''] = text.split('.');
    const result = BigInt(whole) * 10n ** BigInt(places) + BigInt(fraction.padEnd(places, '0') || '0');
    if (result > (places === 2 ? MAX : 999999999999n)) throw Error('El valor supera el límite permitido.');
    return result;
  }
  function decimal(value, places = 2) {
    const sign = value < 0n ? '-' : '';
    const str = (value < 0n ? -value : value).toString().padStart(places + 1, '0');
    return sign + (places ? str.slice(0, -places) + '.' + str.slice(-places) : str);
  }
  function money(value) {
    return '$ ' + decimal(value).replace(/\B(?=(\d{3})+(?!\d))/g, '.').replace(/\.(\d{2})$/, ',$1');
  }
  function localDate(value) {
    return new Intl.DateTimeFormat('sv-SE', {timeZone: 'America/Bogota'}).format(new Date(value));
  }
  function today() { return localDate(Date.now()); }
  function requestResult(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  function transactionDone(tx) {
    return new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onerror = tx.onabort = () => reject(tx.error || Error('No se pudo guardar en este dispositivo.'));
    });
  }
  async function openDB() {
    const request = indexedDB.open('fresas-mobile-v1', 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore('meta');
      request.result.createObjectStore('queue', {keyPath: 'token'});
    };
    return requestResult(request);
  }
  async function read() {
    const tx = db.transaction(['meta', 'queue'], 'readonly');
    const done = transactionDone(tx);
    [catalog, queue] = await Promise.all([
      requestResult(tx.objectStore('meta').get('catalog')),
      requestResult(tx.objectStore('queue').getAll())
    ]);
    await done;
    queue.sort((a, b) => a.created.localeCompare(b.created) || a.token.localeCompare(b.token));
  }
  async function writeOperation(entry) {
    const tx = db.transaction('queue', 'readwrite');
    const done = transactionDone(tx);
    tx.objectStore('queue').add(entry);
    await done;
  }
  async function lease(release = false) {
    const tx = db.transaction('meta', 'readwrite');
    const done = transactionDone(tx), store = tx.objectStore('meta');
    const current = await requestResult(store.get('sync-lock'));
    if (release) {
      if (current?.owner === owner) store.delete('sync-lock');
    } else {
      if (current && current.owner !== owner && current.expires > Date.now()) {
        await done; throw Error('Otra ventana está sincronizando. Espera un momento.');
      }
      store.put({owner, expires: Date.now() + 60000}, 'sync-lock');
    }
    await done;
  }
  async function api(path, body) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store',
        signal: controller.signal, method: body ? 'POST' : 'GET',
        headers: body ? {'Content-Type': 'application/json', 'X-CSRFToken': catalog.csrf} : {},
        ...(body ? {body: JSON.stringify(body)} : {})});
      cloudReachable = true;
      let data;
      try { data = await response.json(); } catch {
        throw Error('La sesión pudo vencer. Inicia sesión con internet y vuelve a sincronizar.');
      }
      if (!response.ok) throw Error(data.error || 'No se pudo sincronizar. Los pendientes siguen guardados.');
      return data;
    } catch (error) {
      if (error.name === 'AbortError' || error instanceof TypeError) {
        cloudReachable = false;
        throw Error('No hay conexión con la nube. Los pendientes siguen guardados en este dispositivo.');
      }
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function sameIdentity(a, b) {
    return a && b && a.user === b.user && a.business === b.business && a.username === b.username;
  }
  async function synchronize() {
    if (syncing) return;
    syncing = true; $('sync').disabled = true;
    let locked = false;
    try {
      await lease(); locked = true;
      const fresh = await api('/api/mobile/bootstrap/');
      await read();
      if (catalog && !sameIdentity(catalog.identity, fresh.identity)) {
        identityMismatch = true;
        throw Error('Esta copia pertenece a otra cuenta. Cierra la sesión desde el menú principal e ingresa con la cuenta original para enviar sus pendientes.');
      }
      identityMismatch = false;
      // Renueva CSRF sin reemplazar el catálogo usado por los pendientes.
      if (catalog) catalog.csrf = fresh.csrf;
      for (const item of queue) {
        await lease();
        try {
          await api('/api/mobile/push/', {identity: catalog.identity, operation: item.operation});
        } catch (error) {
          throw Error(`${label[item.operation.kind]} ${item.token.slice(0, 8)}: ${error.message}`);
        }
        const tx = db.transaction('queue', 'readwrite'), done = transactionDone(tx);
        const store = tx.objectStore('queue');
        const stored = await requestResult(store.get(item.token));
        if (stored) store.put({...stored, status: 'sent'});
        await done;
      }
      await lease();
      const updated = queue.length ? await api('/api/mobile/bootstrap/') : fresh;
      if (!sameIdentity(updated.identity, fresh.identity)) {
        identityMismatch = true; throw Error('La cuenta cambió durante la sincronización. Vuelve a la cuenta original.');
      }
      const tx = db.transaction(['meta', 'queue'], 'readwrite'), done = transactionDone(tx);
      const store = tx.objectStore('queue');
      const entries = await requestResult(store.getAll());
      for (const item of entries) if (item.status === 'sent') store.delete(item.token);
      tx.objectStore('meta').put(updated, 'catalog');
      await done;
      note('Sincronización completa. Tu copia y el catálogo están actualizados.');
      if (navigator.storage?.persist) await navigator.storage.persist().catch(() => false);
    } catch (error) {
      note(error.message);
    } finally {
      if (locked) await lease(true).catch(() => {});
      syncing = false; $('sync').disabled = false;
      await read(); render();
    }
  }
  function fill(select, items, selected) {
    const old = selected ?? select.value;
    select.replaceChildren(new Option('Seleccionar…', ''));
    for (const item of items.filter(o => o.active)) select.add(new Option(item.name, item.id));
    if ([...select.options].some(o => o.value === old)) select.value = old;
  }
  function productFor(select) {
    const p = catalog.products.find(o => o.id === Number(select.value) && o.active);
    if (!p) throw Error('Selecciona un producto activo.');
    return p;
  }
  function rows() {
    return [...$('lines').children].map(line => {
      const p = productFor(line.querySelector('select'));
      const quantity = units(line.querySelector('.quantity').value, 0);
      if (!quantity || quantity > 999999999n) throw Error('La cantidad debe ser un entero positivo dentro del límite.');
      const weight = p.by_weight ? units(p.variable_weight ? line.querySelector('.weight').value : p.weight, 3) : 0n;
      if (p.by_weight && !weight) throw Error('Ingresa un peso mayor que cero.');
      const totalWeight = quantity * weight;
      if (totalWeight > 999999999999n) throw Error('El peso total supera el límite permitido.');
      const subtotal = p.by_weight ? (totalWeight * units(p.price) + 500n) / 1000n : quantity * units(p.price);
      if (subtotal > MAX) throw Error('El subtotal supera el límite permitido.');
      return {product: p.id, quantity: quantity.toString(), weight: decimal(weight, 3),
        price: p.price, unit: p.unit, by_weight: p.by_weight, subtotal};
    });
  }
  function debt(customer, through = today()) {
    let value = catalog.debts.filter(d => d.customer === customer && d.date <= through)
      .reduce((sum, d) => sum + units(d.balance), 0n);
    for (const item of queue) {
      const o = item.operation;
      if (o.customer_id !== customer) continue;
      if (o.kind === 'sale' && localDate(o.occurred_at) <= through)
        value += units(item.total) - units(o.initial);
      if (o.kind === 'payment' && o.date <= through) value -= units(o.amount);
    }
    return value;
  }
  function totals() {
    if (!catalog) return;
    try {
      const total = rows().reduce((sum, row) => sum + row.subtotal, 0n);
      if (total > MAX) throw Error('El total supera el límite permitido.');
      $('sale-total').textContent = 'Total: ' + money(total);
    } catch (error) { $('sale-total').textContent = error.message; }
    $('balance').textContent = $('customer').value ? 'Saldo local: ' + money(debt(Number($('customer').value), mode === 'payment' ? $('date').value || today() : today())) : '';
  }
  function addLine() {
    if ($('lines').children.length >= 100) { note('Máximo 100 productos por venta.'); return; }
    const line = document.createElement('div'); line.className = 'line';
    line.innerHTML = '<label>Producto<select></select></label><div class="pair"><label>Cantidad<input class="quantity" type="number" min="1" step="1" inputmode="numeric" value="1"></label><label class="weight-label">Libras por presentación<input class="weight" type="number" min="0.001" step="0.001" inputmode="decimal"></label></div><small class="product-info"></small><button type="button" class="secondary">Quitar producto</button>';
    const select = line.querySelector('select'); fill(select, catalog.products);
    select.addEventListener('change', () => {
      const p = catalog.products.find(o => o.id === Number(select.value));
      line.querySelector('.weight-label').hidden = !p?.variable_weight;
      line.querySelector('.product-info').textContent = p ? `${p.unit} · ${money(units(p.price))} por ${p.by_weight ? 'libra' : 'unidad'}${p.by_weight && !p.variable_weight ? ' · ' + p.weight + ' lb por presentación' : ''}` : '';
      totals();
    });
    line.querySelector('.weight-label').hidden = true;
    line.querySelector('button').onclick = () => { line.remove(); totals(); };
    line.addEventListener('input', totals); $('lines').append(line); totals();
  }
  function render() {
    $('connection').textContent = !navigator.onLine || cloudReachable === false ? 'Sin conexión con la nube' : (cloudReachable ? 'Conectado a la nube' : 'Comprobando conexión…');
    $('workspace').hidden = !catalog || identityMismatch;
    $('pending-count').textContent = queue.length + ' movimientos por confirmar';
    if (!catalog) { $('account').textContent = 'Inicia sesión y sincroniza una vez con internet.'; return; }
    $('account').textContent = `${catalog.identity.username} · ${catalog.identity.business}`;
    $('last-sync').textContent = 'Última copia: ' + new Date(catalog.updated).toLocaleString('es-CO');
    fill($('customer'), catalog.customers); fill($('category'), catalog.categories);
    const cash = catalog.methods.filter(o => !o.is_credit);
    fill($('method'), cash); fill($('cash-method'), cash); fill($('sale-method'), catalog.methods);
    // Conserva los formularios en curso mientras la copia se actualiza.
    for (const line of $('lines').children) {
      const select = line.querySelector('select');
      fill(select, catalog.products);
      select.dispatchEvent(new Event('change'));
    }
    if (!$('lines').children.length) addLine();
    $('save').disabled = !catalog.permissions[mode] || identityMismatch;
    $('queue').replaceChildren();
    for (const item of queue) {
      const li = document.createElement('li'); li.className = 'queue-item';
      li.textContent = `${label[item.operation.kind]} · ${money(units(item.total || item.operation.amount))} · ${item.status === 'sent' ? 'Recibido en nube; falta actualizar copia' : 'Guardado en este dispositivo'} · ${item.token.slice(0, 8)}`;
      $('queue').append(li);
    }
    totals();
  }
  function chooseMode(next) {
    mode = next;
    for (const button of document.querySelectorAll('[data-tab]')) button.setAttribute('aria-pressed', String(button.dataset.tab === mode));
    $('form-title').textContent = 'Nuevo registro · ' + label[mode];
    $('sale-fields').hidden = mode !== 'sale'; $('other-fields').hidden = mode === 'sale';
    $('customer-field').hidden = mode === 'expense'; $('category-field').hidden = mode !== 'expense';
    if (catalog) $('save').disabled = !catalog.permissions[mode];
    totals();
  }
  async function save(event) {
    event.preventDefault(); $('save').disabled = true;
    try {
      await read();
      if (!catalog || identityMismatch || !catalog.permissions[mode]) throw Error('Primero prepara la app con tu cuenta autorizada.');
      const token = crypto.randomUUID(), created = new Date().toISOString();
      const o = {kind: mode, token, method_id: Number($(mode === 'sale' ? 'sale-method' : 'method').value)};
      const method = catalog.methods.find(m => m.id === o.method_id && m.active);
      if (!method || (mode !== 'sale' && method.is_credit)) throw Error('Selecciona un medio de pago válido.');
      if (mode !== 'expense') {
        o.customer_id = Number($('customer').value);
        if (!catalog.customers.some(c => c.id === o.customer_id && c.active)) throw Error('Selecciona un cliente activo.');
      }
      let total;
      if (mode === 'sale') {
        const detail = rows();
        if (!detail.length) throw Error('Agrega al menos un producto.');
        total = detail.reduce((sum, row) => sum + row.subtotal, 0n);
        if (total > MAX) throw Error('El total supera el límite permitido.');
        const initial = units($('initial').value);
        if (initial > total) throw Error('El pago inicial supera la venta.');
        o.initial = decimal(initial);
        o.cash_method_id = Number($('cash-method').value) || null;
        if (initial && !catalog.methods.some(m => m.id === o.cash_method_id && m.active && !m.is_credit)) throw Error('Selecciona el medio del pago inicial.');
        o.occurred_at = created;
        o.rows = detail.map(({subtotal, ...row}) => row);
      } else {
        total = units($('amount').value);
        if (!total) throw Error('El valor debe ser mayor que cero.');
        o.amount = decimal(total); o.date = $('date').value;
        if (!o.date || o.date > today()) throw Error('Selecciona una fecha válida hasta hoy.');
        if (mode === 'payment') {
          const customer = catalog.customers.find(c => c.id === o.customer_id);
          if (o.date < localDate(customer.created_at)) throw Error('El abono es anterior al cliente.');
          if (total > debt(o.customer_id, o.date)) throw Error('El abono supera la deuda local disponible en esa fecha.');
          o.notes = $('notes').value;
        } else {
          o.category_id = Number($('category').value);
          if (!catalog.categories.some(c => c.id === o.category_id && c.active)) throw Error('Selecciona una categoría activa.');
          o.description = $('notes').value; o.reference = '';
        }
      }
      await writeOperation({token, created, operation: o, total: decimal(total), status: 'pending'});
      note('Guardado en este dispositivo. Se enviará cuando haya conexión y una sesión activa.');
      $('movement').reset(); $('date').value = today(); $('lines').replaceChildren();
      await read(); render();
      if (navigator.onLine) synchronize();
    } catch (error) { note('No se confirmó el guardado: ' + error.message); }
    finally { $('save').disabled = !catalog?.permissions[mode] || identityMismatch; }
  }
  async function start() {
    try {
      db = await openDB(); await read(); render(); chooseMode('sale');
      $('date').value = today();
      $('sync').onclick = synchronize; $('add-line').onclick = addLine;
      $('movement').onsubmit = save;
      $('customer').onchange = totals; $('date').onchange = totals;
      for (const button of document.querySelectorAll('[data-tab]')) button.onclick = () => chooseMode(button.dataset.tab);
      $('export').onclick = async () => {
        await read();
        const blob = new Blob([JSON.stringify({version: 1, identity: catalog.identity, queue}, null, 2)], {type: 'application/json'});
        const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
        a.download = 'fresas-pendientes-' + today() + '.json'; a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      };
      window.addEventListener('online', () => { render(); synchronize(); });
      window.addEventListener('offline', render);
      document.addEventListener('visibilitychange', () => { if (!document.hidden && navigator.onLine) synchronize(); });
      setInterval(() => { if (!document.hidden && navigator.onLine) synchronize(); }, 120000);
      if ('serviceWorker' in navigator && window.isSecureContext) {
        try {
          await navigator.serviceWorker.register('/movil/sw.js', {scope: '/movil/'});
          await Promise.race([navigator.serviceWorker.ready, new Promise((_, reject) => setTimeout(() => reject(Error('offline-cache-timeout')), 20000))]);
          $('install-status').textContent = 'App preparada para abrir sin internet. Agrégala a inicio desde el menú del navegador; en iPhone: Compartir → Agregar a inicio. Sincroniza de nuevo al abrirla desde ese acceso.';
        } catch { note('No se pudo preparar la apertura sin internet. Mantén esta ventana y vuelve a intentarlo con conexión.'); }
      } else { note('Este navegador necesita HTTPS y almacenamiento local para preparar la app sin internet.'); }
      if (navigator.onLine) synchronize();
    } catch (error) { note('No se pudo abrir el almacenamiento local: ' + error.message); $('workspace').hidden = true; }
  }
  start();
})();
