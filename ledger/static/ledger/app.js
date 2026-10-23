'use strict';
const currency=new Intl.NumberFormat('es-CO',{style:'currency',currency:'COP',minimumFractionDigits:2});
const SVG=(paths,size=18)=>`<svg class="ic" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
const ICON={plus:'<path d="M12 5v14M5 12h14"/>',minus:'<path d="M5 12h14"/>',x:'<path d="M6 6l12 12M18 6 6 18"/>',cart:'<circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/><path d="M2.5 3.5h3l2.5 12h11l2-8.5H6.5"/>',search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'};
const BERRY='<svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true"><path d="M16 29.2c-6.4-2.3-10.6-8.4-10.6-13.4 0-4 3.3-6.2 6.3-5.6 1.5.3 2.8.8 4.3.8s2.8-.5 4.3-.8c3-.6 6.3 1.6 6.3 5.6 0 5-4.2 11.1-10.6 13.4z" fill="#E23D55"/><g fill="#FFE9C7"><ellipse cx="11.5" cy="15.5" rx=".7" ry="1"/><ellipse cx="16" cy="14.2" rx=".7" ry="1"/><ellipse cx="20.5" cy="15.5" rx=".7" ry="1"/><ellipse cx="13.6" cy="19.6" rx=".7" ry="1"/><ellipse cx="18.4" cy="19.6" rx=".7" ry="1"/></g><path d="M16 10.6c-2.3-2.6-5.3-3.2-8-2.4 1.6 2.4 4.6 3.4 8 2.4zM16 10.6c2.3-2.6 5.3-3.2 8-2.4-1.6 2.4-4.6 3.4-8 2.4z" fill="#3E9B5F"/></svg>';
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};

/* ---------- Impresión ---------- */
document.querySelectorAll('[data-print]').forEach(b=>b.addEventListener('click',()=>window.print()));

/* ---------- Menú lateral móvil ---------- */
const openNav=()=>document.body.classList.add('nav-open'),closeNav=()=>document.body.classList.remove('nav-open');
document.querySelectorAll('[data-nav-open]').forEach(b=>b.addEventListener('click',openNav));
document.querySelectorAll('[data-nav-close]').forEach(b=>b.addEventListener('click',closeNav));
document.addEventListener('keydown',e=>{
 if(e.key==='Escape')closeNav();
 const typing=/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName)||document.activeElement?.isContentEditable;
 if(!typing&&!e.metaKey&&!e.ctrlKey&&!e.altKey&&(e.key==='n'||e.key==='N')&&document.querySelector('.sb-cta')&&location.pathname!=='/ventas/nueva/'){location.href='/ventas/nueva/';}
});

/* ---------- Avisos (toasts) ---------- */
document.querySelectorAll('[data-toast]').forEach((t,i)=>{
 const close=()=>{t.classList.add('is-leaving');setTimeout(()=>t.remove(),300);};
 t.querySelector('.toast-close')?.addEventListener('click',close);
 if(!t.classList.contains('error'))setTimeout(close,6000+i*400);
});

/* ---------- Saludo según la hora ---------- */
const greet=document.querySelector('[data-greeting]');
if(greet){const h=new Date().getHours(),name=greet.textContent.replace(/^Hola,\s*/,'');greet.textContent=(h<12?'Buenos días':h<19?'Buenas tardes':'Buenas noches')+', '+name;}

/* ---------- Mostrar contraseña ---------- */
document.querySelectorAll('[data-reveal]').forEach(b=>b.addEventListener('click',()=>{const i=document.getElementById(b.dataset.reveal);const show=i.type==='password';i.type=show?'text':'password';b.setAttribute('aria-label',show?'Ocultar contraseña':'Mostrar contraseña');}));

/* ---------- Envío automático al elegir cliente ---------- */
document.querySelectorAll('select[data-autosubmit]').forEach(s=>s.addEventListener('change',()=>{if(s.value)s.form.requestSubmit?s.form.requestSubmit():s.form.submit();}));

/* ---------- Periodos rápidos ---------- */
const iso=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const presetRange=p=>{const now=new Date(),from=new Date(now);if(p==='week')from.setDate(now.getDate()-(now.getDay()+6)%7);if(p==='month')from.setDate(1);if(p==='year')from.setMonth(0,1);return[iso(from),iso(now)];};
document.querySelectorAll('[data-period]').forEach(b=>{
 const f=b.closest('form');if(!f||!f.elements.start)return;
 const [s,e]=presetRange(b.dataset.period);
 if(f.elements.start.value===s&&f.elements.end.value===e&&!f.querySelector('.chip.is-active'))b.classList.add('is-active');
 b.addEventListener('click',()=>{const [a,z]=presetRange(b.dataset.period);f.elements.start.value=a;f.elements.end.value=z;f.submit();});
});

/* ---------- Tablas ordenables ---------- */
document.querySelectorAll('table[data-sortable]').forEach(table=>{
 table.querySelectorAll('thead th').forEach((th,index)=>{
  if(th.classList.contains('no-sort'))return;
  th.tabIndex=0;th.setAttribute('role','button');th.title='Ordenar por esta columna';
  const sort=()=>{const tbody=table.tBodies[0],rows=Array.from(tbody.rows);if(rows.length<2)return;const ascending=th.dataset.direction!=='asc';table.querySelectorAll('thead th').forEach(o=>{if(o!==th){o.removeAttribute('aria-sort');delete o.dataset.direction;}});th.dataset.direction=ascending?'asc':'desc';rows.sort((a,b)=>{const av=a.cells[index]?.innerText.trim()||'',bv=b.cells[index]?.innerText.trim()||'';const numeric=s=>Number(s.replace(/[^\d,.-]/g,'').replace(/\./g,'').replace(',','.'));const d=/^\d{2}\/\d{2}\/\d{4}/;let diff;if(d.test(av)&&d.test(bv)){const n=s=>s.slice(0,10).split('/').reverse().join('');diff=n(av).localeCompare(n(bv));}else if(/^\$/.test(av)&&/^\$/.test(bv))diff=numeric(av)-numeric(bv);else diff=av.localeCompare(bv,'es',{numeric:true});return ascending?diff:-diff;});rows.forEach(r=>tbody.appendChild(r));th.setAttribute('aria-sort',ascending?'ascending':'descending');};
  th.addEventListener('click',sort);th.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();sort();}});
 });
});

/* ---------- Gráfico de columnas: escala limpia y detalle al pasar ---------- */
const chart=document.querySelector('[data-colchart]');
if(chart){
 const groups=[...chart.querySelectorAll('.col-group')];
 const peak=Math.max(1,...groups.flatMap(g=>[Number(g.dataset.sales),Number(g.dataset.expenses)]));
 const step=(()=>{const raw=peak/4,mag=10**Math.floor(Math.log10(raw)),n=raw/mag;return(n<=1?1:n<=2?2:n<=2.5?2.5:n<=5?5:10)*mag;})();
 const top=step*4;
 const compact=new Intl.NumberFormat('es-CO',{notation:'compact',maximumFractionDigits:1});
 chart.querySelectorAll('[data-tick]').forEach(t=>t.textContent='$'+compact.format(step*Number(t.dataset.tick)));
 groups.forEach(g=>{
  g.querySelector('.col-sales').style.setProperty('--h',(Number(g.dataset.sales)/top*100).toFixed(2)+'%');
  g.querySelector('.col-exp').style.setProperty('--h',(Number(g.dataset.expenses)/top*100).toFixed(2)+'%');
 });
 const tip=document.getElementById('chart-tip');
 const show=g=>{const r=g.getBoundingClientRect();tip.replaceChildren();tip.append(el('b','',g.dataset.label));[['Ventas','sw-sales',g.dataset.salesText],['Gastos','sw-exp',g.dataset.expensesText]].forEach(([l,c,v])=>{const row=el('div'),lab=el('span');lab.append(el('i','sw '+c),document.createTextNode(l));row.append(lab,el('strong','',v));tip.append(row);});tip.hidden=false;tip.style.left=Math.min(Math.max(r.left+r.width/2,100),innerWidth-100)+'px';tip.style.top=Math.max(r.top+20,90)+'px';};
 const hide=()=>{tip.hidden=true;};
 groups.forEach(g=>{g.querySelectorAll('[title]').forEach(n=>n.removeAttribute('title'));g.addEventListener('mouseenter',()=>show(g));g.addEventListener('focus',()=>show(g));g.addEventListener('mouseleave',hide);g.addEventListener('blur',hide);});
 chart.querySelector('.colchart-scroll').addEventListener('scroll',hide);
 const sc=chart.querySelector('.colchart-scroll');sc.scrollLeft=sc.scrollWidth;
}

/* ---------- Nueva venta ---------- */
const saleForm=document.getElementById('sale-form');
if(saleForm){
 const products=JSON.parse(document.getElementById('products-data').textContent),submitted=JSON.parse(document.getElementById('submitted-data').textContent),lines=document.getElementById('sale-lines');let items=[];
 const money=n=>currency.format(n),round=n=>Math.round((n+Number.EPSILON)*100)/100;
 const total=()=>items.reduce((sum,item)=>{const p=products.find(p=>p.id===item.product);return sum+round(Number(p.price)*item.quantity*(p.by_weight?item.weight:1));},0);
 const grand=document.getElementById('grand-total');let lastTotal=null;
 const steps=()=>{const set=(k,ok)=>document.querySelector(`.stepper [data-step="${k}"]`)?.classList.toggle('is-done',ok);set('customer',!!saleForm.elements.customer.value);set('products',items.length>0);set('payment',!!saleForm.elements.method.value);};
 const update=()=>{const value=round(total()),initial=Number(saleForm.elements.initial.value||0);grand.textContent=money(value);if(lastTotal!==null&&lastTotal!==value){grand.classList.remove('bump');void grand.offsetWidth;grand.classList.add('bump');}lastTotal=value;document.getElementById('draft-total').textContent=money(value);document.getElementById('draft-quantity').textContent=items.reduce((n,i)=>n+i.quantity,0).toLocaleString('es-CO');document.getElementById('draft-weight').textContent=items.reduce((n,i)=>n+(products.find(p=>p.id===i.product).by_weight?i.quantity*i.weight:0),0).toLocaleString('es-CO',{maximumFractionDigits:6});document.getElementById('sale-balance').textContent=money(value-initial);saleForm.elements.initial.max=value;document.getElementById('sale-rows').value=JSON.stringify(items);const credit=saleForm.elements.method.selectedOptions[0]?.dataset.credit==='true';document.getElementById('cash-method-label').hidden=!credit;saleForm.elements.cash_method.required=credit&&initial>0;steps();};
 function draw(){
  lines.replaceChildren();
  if(!items.length){const empty=el('div','empty-state compact'),art=el('div','empty-art');art.innerHTML=SVG(ICON.cart,26);empty.append(art,el('h3','','Tu venta empieza aquí'),el('p','','Agrega un producto para comenzar.'));lines.append(empty);}
  items.forEach((item,index)=>{
   const p=products.find(p=>p.id===item.product),row=el('div','sale-line');
   const header=el('div','line-heading'),badge=el('span','line-badge');badge.innerHTML=BERRY;
   const title=el('div');title.append(el('strong','',p.name),el('small','',`${money(Number(p.price))} por ${p.by_weight?'libra':p.unit}`));
   const remove=el('button','remove-line');remove.type='button';remove.innerHTML=SVG(ICON.x,16);remove.setAttribute('aria-label',`Quitar ${p.name}`);remove.onclick=()=>{items.splice(index,1);draw();};
   header.append(badge,title,remove);row.append(header);
   const fields=el('div','line-fields');
   function input(label,key,disabled=false){
    const l=el('label');l.append(document.createTextNode(label));
    const v=document.createElement('input');v.type='number';v.min=key==='quantity'?'1':'0.001';v.step=key==='quantity'?'1':'0.001';v.inputMode=key==='quantity'?'numeric':'decimal';v.max='999999999';v.value=item[key];v.required=true;v.disabled=disabled;v.setAttribute('aria-label',label);
    v.oninput=()=>{item[key]=Number(v.value);if(key==='quantity')v.setCustomValidity(Number.isInteger(item[key])&&item[key]>0?'':'Ingrese una cantidad entera mayor que cero.');calculate();update();};
    if(key==='quantity'){
     v.addEventListener('keydown',e=>{if(['.',',','e','E','+','-'].includes(e.key))e.preventDefault();});
     v.addEventListener('paste',e=>{if(!/^\d+$/.test(e.clipboardData.getData('text').trim()))e.preventDefault();});
     const wrap=el('div','qty'),dec=el('button'),inc=el('button');dec.type=inc.type='button';dec.innerHTML=SVG(ICON.minus,16);inc.innerHTML=SVG(ICON.plus,16);dec.setAttribute('aria-label','Restar uno');inc.setAttribute('aria-label','Sumar uno');dec.tabIndex=inc.tabIndex=-1;
     const bump=d=>{const n=Math.max(1,(Math.floor(Number(v.value))||0)+d);v.value=n;v.dispatchEvent(new Event('input'));};
     dec.onclick=()=>bump(-1);inc.onclick=()=>bump(1);wrap.append(dec,v,inc);l.append(wrap);
    }else l.append(v);
    fields.append(l);
   }
   input(`Cantidad (${p.unit})`,'quantity');if(p.by_weight)input('lb por presentación','weight',!p.variable_weight);
   const subtotal=el('strong','line-total');fields.append(subtotal);row.append(fields);
   const calculation=el('div','line-calculation');row.append(calculation);
   function calculate(){const weight=Math.round(item.quantity*item.weight*1e6)/1e6,amount=round(Number(p.price)*item.quantity*(p.by_weight?item.weight:1));subtotal.textContent=money(amount);calculation.textContent=p.by_weight?`${item.quantity} ${p.unit} × ${item.weight} lb = ${weight} lb en total × ${money(Number(p.price))}/lb`:`${item.quantity} ${p.unit} × ${money(Number(p.price))}`;}
   calculate();lines.append(row);
  });
  update();
 }
 const search=document.getElementById('product-search'),results=document.getElementById('product-results');
 const normalize=value=>String(value||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLocaleLowerCase('es');
 const addProduct=p=>{const existing=items.find(i=>i.product===p.id&&!p.variable_weight);if(existing)existing.quantity+=1;else items.push({product:p.id,quantity:1,weight:p.by_weight?Number(p.weight)||1:0});draw();search.value='';searchProducts();search.focus();};
 function searchProducts(){
  results.replaceChildren();const query=normalize(search.value.trim());
  if(!products.length){results.append(el('p','muted','No hay productos activos. Crea uno en Productos.'));return;}
  if(!query){results.append(el('p','muted','Escribe para encontrar un producto y agregarlo a la venta. Accesos rápidos:'));}
  const matches=query?products.filter(p=>normalize(p.name+' '+(p.code||'')).includes(query)):products.slice(0,6);
  if(!matches.length){results.append(el('p','muted','No se encontraron productos.'));return;}
  matches.forEach(p=>{
   const row=el('div',query?'product-result':'product-result product-quick'),icon=el('span','pr-icon');icon.innerHTML=BERRY;
   const info=el('div');info.append(el('strong','',p.name),el('small','',`${money(Number(p.price))} por ${p.by_weight?'libra':p.unit}`));
   const add=el('button','btn btn-soft btn-sm');add.type='button';add.innerHTML=SVG(ICON.plus,15);add.append(document.createTextNode(' Agregar'));add.setAttribute('aria-label',`Agregar ${p.name}`);add.onclick=()=>addProduct(p);
   row.append(icon,info,add);results.append(row);
  });
 }
 search.addEventListener('input',searchProducts);search.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();results.querySelector('.product-result:not(.product-quick) button')?.click();}});
 saleForm.elements.initial.addEventListener('input',update);saleForm.elements.method.addEventListener('change',update);saleForm.elements.customer.addEventListener('change',steps);
 saleForm.querySelector('[data-fill-total]')?.addEventListener('click',()=>{saleForm.elements.initial.value=round(total()).toFixed(2);update();saleForm.elements.initial.focus();});
 for(const key of ['customer','method','initial','cash_method'])if(submitted[key])saleForm.elements[key].value=submitted[key];
 try{items=JSON.parse(submitted.rows||'[]').filter(i=>products.some(p=>p.id===i.product));}catch{}draw();searchProducts();
 saleForm.addEventListener('submit',e=>{update();if(!items.length||items.some(i=>i.quantity<=0||!Number.isInteger(i.quantity))){e.preventDefault();document.getElementById('sale-error').textContent='Agrega al menos un producto. Las cantidades deben ser números enteros mayores que cero.';}});
}

/* ---------- Producto: solo muestra los campos de peso que corresponden ---------- */
const byWeight=document.getElementById('id_by_weight');
if(byWeight){
 const variable=document.getElementById('id_variable_weight'),weight=document.getElementById('id_weight');
 const updateWeightFields=()=>{const active=byWeight.checked;if(!active)variable.checked=false;variable.closest('[data-field]').hidden=!active;variable.disabled=!active;const fixed=active&&!variable.checked;weight.closest('[data-field]').hidden=!fixed;weight.disabled=!fixed;weight.required=fixed;};
 byWeight.addEventListener('change',updateWeightFields);variable.addEventListener('change',updateWeightFields);updateWeightFields();
}

/* ---------- Abonos: vista previa de la aplicación (más antigua primero) ---------- */
const paymentForm=document.getElementById('payment-form');
if(paymentForm){
 const amount=paymentForm.elements.amount,date=paymentForm.elements.date;
 const preview=()=>{let remaining=Math.max(0,Number(amount.value)||0),eligible=0;const balance=Number(paymentForm.dataset.balance);paymentForm.querySelectorAll('[data-debt]').forEach(row=>{const debt=Number(row.dataset.debt),available=row.dataset.date<=date.value;if(available)eligible+=debt;const applied=available?Math.min(remaining,debt):0;remaining-=applied;row.querySelector('[data-applied]').textContent=currency.format(applied);row.querySelector('[data-after]').textContent=currency.format(debt-applied);const cover=row.querySelector('[data-cover]');if(cover)cover.style.width=(debt?applied/debt*100:0)+'%';row.classList.toggle('is-muted',!available);});const appliedTotal=Math.min(Math.max(0,Number(amount.value)||0),eligible);document.getElementById('payment-remaining').textContent=currency.format(balance-appliedTotal);document.getElementById('payment-total-applied').textContent=currency.format(appliedTotal);document.getElementById('payment-total-after').textContent=currency.format(balance-appliedTotal);amount.max=eligible;document.getElementById('payment-preview-error').textContent=remaining>0?'El abono supera la deuda disponible para la fecha seleccionada.':'';};
 amount.addEventListener('input',preview);date.addEventListener('change',preview);preview();
}

/* ---------- Confirmación con modal y estado de carga ----------
   Se registra al final para ejecutarse después de las validaciones propias de cada formulario. */
const modal=document.getElementById('confirm-modal');
const markLoading=(form,submitter)=>{const b=submitter||form.querySelector('button:not([type=button]):not([value=cancel])');if(b&&b.classList.contains('btn')){b.classList.add('is-loading');b.setAttribute('aria-busy','true');}};
document.querySelectorAll('form').forEach(f=>{
 if(f.method==='dialog')return;
 f.addEventListener('submit',e=>{
  if(e.defaultPrevented)return;
  if(f.dataset.confirm&&f.dataset.confirmed!=='1'){
   e.preventDefault();
   const submitter=e.submitter;
   if(!modal||typeof modal.showModal!=='function'){if(confirm(f.dataset.confirm)){f.dataset.confirmed='1';f.requestSubmit?f.requestSubmit(submitter):f.submit();}return;}
   document.getElementById('confirm-title').textContent=f.dataset.confirmTitle||'Confirmar acción';
   document.getElementById('confirm-text').textContent=f.dataset.confirm;
   modal.returnValue='';modal.showModal();document.getElementById('confirm-ok').focus();
   modal.addEventListener('close',()=>{if(modal.returnValue==='ok'){f.dataset.confirmed='1';if(f.requestSubmit)f.requestSubmit(submitter&&submitter.form===f?submitter:undefined);else{markLoading(f,submitter);f.submit();}}},{once:true});
   return;
  }
  delete f.dataset.confirmed;
  if(f.method==='post')markLoading(f,e.submitter);
 });
});
window.addEventListener('pageshow',()=>document.querySelectorAll('.is-loading').forEach(b=>{b.classList.remove('is-loading');b.removeAttribute('aria-busy');}));
