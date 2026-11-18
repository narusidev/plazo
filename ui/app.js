'use strict';
const KEY = new URLSearchParams(location.search).get('k') || '';
const DIA = 86400;
let S = null;
let vista = 'pendientes';
let temporizador = null;
let avisoAjustes = '';

// ---------- API ----------
async function api(ruta, datos) {
  const opciones = { headers: { 'X-Plazo-Key': KEY } };
  if (datos !== undefined) {
    opciones.method = 'POST';
    opciones.headers['Content-Type'] = 'application/json';
    opciones.body = JSON.stringify(datos);
  }
  const r = await fetch(ruta, opciones);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || 'Error ' + r.status);
  return j;
}

async function refrescar() {
  try {
    S = await api('/api/state');
    pintar();
  } catch (e) {
    document.getElementById('app').innerHTML =
      '<p class="caido">Plazo se ha cerrado. Ábrelo otra vez desde el menú Inicio.</p>';
    S = null;
  }
  clearTimeout(temporizador);
  const rapido = S && (S.sincronizando || S.esperando_login);
  temporizador = setTimeout(refrescar, rapido ? 2000 : 30000);
}

async function accion(ruta, datos = {}) {
  try { await api(ruta, datos); } catch (e) { alertaError(e.message); }
  refrescar();
}

function alertaError(msg) {
  avisoAjustes = msg;
}

// ---------- fechas ----------
const ahora = () => Date.now() / 1000;
const fmt = (o) => new Intl.DateTimeFormat('es-ES', o);
const fSem = fmt({ weekday: 'short' });
const fMes = fmt({ month: 'short' });
const fDiaLargo = fmt({ weekday: 'long' });
const fMesLargo = fmt({ month: 'long' });
const fHora = fmt({ hour: '2-digit', minute: '2-digit' });
const d = (ts) => new Date(ts * 1000);
const sinPunto = (s) => s.replace('.', '');

function inicioDia(ts) { const x = d(ts); x.setHours(0, 0, 0, 0); return x.getTime() / 1000; }
function diasEntre(a, b) { return Math.round((inicioDia(b) - inicioDia(a)) / DIA); }
function lunesDe(ts) { const x = d(ts); x.setHours(0, 0, 0, 0); x.setDate(x.getDate() - (x.getDay() + 6) % 7); return x.getTime() / 1000; }
function corta(ts) {
  if (!ts) return 'sin fecha';
  const x = d(ts);
  return `${sinPunto(fSem.format(x))} ${x.getDate()} ${sinPunto(fMes.format(x))}`;
}
function larga(ts) { const x = d(ts); return `${fDiaLargo.format(x)} ${x.getDate()} de ${fMesLargo.format(x)}`; }
function cortaConHora(ts) { return ts ? `${corta(ts)}, ${fHora.format(d(ts))}` : 'sin fecha'; }

function quedan(ts) {
  const s = ts - ahora();
  if (s <= 0) return 'vencida';
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 48 * 3600) return `${Math.floor(s / 3600)} h`;
  return `${diasEntre(ahora(), ts)} días`;
}
const urgente = (ts) => ts && ts > ahora() && ts - ahora() < 48 * 3600;

function hace(ts) {
  if (!ts) return 'nunca';
  const s = ahora() - ts;
  if (s < 60) return 'ahora mismo';
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < DIA) return `hace ${Math.round(s / 3600)} h`;
  return `el ${corta(ts)}`;
}

// ---------- utilidades ----------
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nombreModulo = (n) => String(n || '').replace(/\s*-\s*AND\s*$/i, '').replace(/\s*\(gs\)\s*/i, ' ').trim();
const cambiosSinLeer = () => S.cambios.filter((c) => !c.leido);

function cambioDeFecha(t) {
  return S.cambios.find((c) => !c.leido && c.entidad === 'tarea' && c.tipo === 'fecha' && c.id_entidad === t.id_cm);
}

function textoCambio(c) {
  const quien = c.sigla ? `<b>${esc(c.sigla)}</b> ` : '';
  const que = `${quien}${esc(c.titulo)}`;
  switch (c.tipo) {
    case 'fecha': return `${que}: <s>${esc(cortaConHora(+c.antes))}</s> ahora es <b>${esc(cortaConHora(+c.despues))}</b>`;
    case 'nueva': return `${que} es nueva${c.despues ? `, para el ${esc(cortaConHora(+c.despues))}` : ''}`;
    case 'nota': return `${que}: nota <b>${esc(c.despues)}</b>${c.antes ? ` (antes ${esc(c.antes)})` : ''}`;
    case 'eliminada': return `${que} ya no aparece en el campus`;
  }
  return que;
}

// ---------- pintado ----------
function pintar() {
  const app = document.getElementById('app');
  if (!S.conectado) { app.innerHTML = pantallaConexion(); return; }
  const n = cambiosSinLeer().length;
  const pestañas = [['pendientes', 'Pendientes'], ['entregadas', 'Entregadas'], ['notas', 'Notas'], ['agenda', 'Agenda'], ['cambios', 'Cambios'], ['ajustes', 'Ajustes']];
  const estado = S.sincronizando ? 'Leyendo el campus…' : `Actualizado ${hace(S.ultima_sync)}`;
  app.innerHTML = `
    <header class="cabecera">
      <div class="marca">Plazo</div>
      <nav class="nav" aria-label="Secciones">
        ${pestañas.map(([id, txt]) => `<button data-vista="${id}" ${vista === id ? 'aria-current="page"' : ''}>${txt}${id === 'cambios' && n ? `<span class="cuenta-cambios">${n}</span>` : ''}</button>`).join('')}
      </nav>
      <div class="estado"><span>${esc(estado)}</span>
        <button class="boton suave" data-accion="sync" ${S.sincronizando ? 'disabled' : ''}>Sincronizar</button></div>
    </header>
    ${S.error ? `<p class="error">${esc(S.error)}</p>` : ''}
    <main>${({ pendientes, entregadas, notas, agenda, cambios, ajustes })[vista]()}</main>`;
  colocarPines();
}

function pantallaConexion() {
  if (S.esperando_login) {
    return `<div class="conexion"><div class="marca">Plazo</div>
      <p>Entra con tu cuenta de Office 365 en la ventana que se ha abierto. Cuando el campus te deje dentro, se cerrará sola.</p>
      <p class="ayuda">Esta pantalla cambia sola en cuanto llegue la conexión.</p></div>`;
  }
  return `<div class="conexion"><div class="marca">Plazo</div>
    <p>Lee tus entregas, fechas y notas del campus de CESUR y te avisa cuando un profesor cambia una fecha.</p>
    <button class="boton" data-accion="login">Entrar en el campus</button>
    <p class="ayuda">Se abre una ventana del campus para que entres con Office 365, como siempre. Plazo no ve tu contraseña: se queda con la sesión, cifrada en este ordenador, y solo la usa para leer.</p>
    ${S.error ? `<p class="ayuda">${esc(S.error)}</p>` : ''}
    <p class="ayuda">Campus: ${esc(S.sitio)}</p></div>`;
}

function avisoSesion() {
  if (S.sesion === 'activa') return '';
  if (S.esperando_login) {
    return `<section class="sesion"><p>Entra en el campus en la ventana que se ha abierto. Cuando termines, esto se actualiza solo.</p></section>`;
  }
  const desde = S.ultima_sync_completa ? ` desde el ${esc(corta(S.ultima_sync_completa))}` : '';
  const fechas = S.ical ? 'Las fechas se siguen actualizando, ' : '';
  return `<section class="sesion"><p><b>Tu sesión del campus ha caducado.</b> ${fechas}pero entregas y notas no cambian${desde}.</p>
    <button class="boton" data-accion="login">Volver a entrar</button></section>`;
}

function correcciones() {
  const nuevos = cambiosSinLeer();
  if (!nuevos.length) return '';
  const visibles = nuevos.slice(0, 4);
  return `<section class="correcciones" aria-label="Cambios sin leer">
    <h2>${nuevos.length === 1 ? 'Ha cambiado algo en el campus' : `Han cambiado ${nuevos.length} cosas en el campus`}</h2>
    <ul>${visibles.map((c) => `<li>${textoCambio(c)}</li>`).join('')}</ul>
    <div class="acciones"><button class="boton" data-accion="leidos">Entendido</button>
    ${nuevos.length > visibles.length ? '<button class="enlace" data-vista="cambios">Ver todos</button>' : ''}</div>
  </section>`;
}

function filaTarea(t, opciones = {}) {
  const ts = t.fecha_limite;
  const cambio = cambioDeFecha(t);
  const clases = ['fila'];
  if (opciones.pasada) clases.push('pasada');
  if (opciones.hecha) clases.push('hecha');
  const titulo = t.url
    ? `<a href="#" class="titulo" data-abrir="${esc(t.url)}">${esc(t.titulo)}</a>`
    : `<span class="titulo">${esc(t.titulo)}</span>`;
  let derecha;
  if (opciones.hecha) {
    derecha = t.nota_texto ? `<span class="resta">${esc(t.nota_texto)}</span>` : '<span class="hora">sin nota todavía</span>';
  } else if (!t.fecha_limite) {
    derecha = '<span class="hora">sin fecha</span>';
  } else {
    derecha = `<span class="resta ${urgente(t.fecha_limite) ? 'urgente' : ''}">${quedan(t.fecha_limite)}</span>
               <span class="hora">${fHora.format(d(t.fecha_limite))}</span>`;
  }
  let extra = '';
  if (cambio && !opciones.hecha) extra = `<span class="corregido">Antes era el <s>${esc(cortaConHora(+cambio.antes))}</s></span>`;
  return `<li class="${clases.join(' ')}" id="t-${t.id_cm}">
    <div class="fecha">${ts ? `<span class="num">${d(ts).getDate()}</span><span class="sem">${sinPunto(fSem.format(d(ts)))} ${sinPunto(fMes.format(d(ts)))}</span>` : '<span class="sem">—</span>'}</div>
    <div class="que">${titulo}<span class="mod">${esc(nombreModulo(t.modulo))}</span>${extra}</div>
    <div class="cuando"><span class="sigla">${esc(t.sigla)}</span>${derecha}</div>
  </li>`;
}

function grupo(titulo, filas, nota = '') {
  if (!filas.length) return '';
  return `<section class="grupo"><h2>${titulo}</h2>${nota ? `<p class="nota-grupo">${nota}</p>` : ''}<ul class="filas">${filas.join('')}</ul></section>`;
}

function pendientes() {
  const t0 = ahora();
  const pend = S.tareas.filter((t) => t.estado !== 'entregada');
  const futuras = pend.filter((t) => t.fecha_limite && t.fecha_limite >= t0);
  const pasadas = pend.filter((t) => t.fecha_limite && t.fecha_limite < t0 && t0 - t.fecha_limite < 60 * DIA);
  const sinFecha = pend.filter((t) => !t.fecha_limite);
  const lunes = lunesDe(t0);

  let proximo;
  if (futuras.length) {
    const p = futuras[0];
    const cuando = `${larga(p.fecha_limite)} a las ${fHora.format(d(p.fecha_limite))}`;
    proximo = `<p class="proximo">Lo próximo es <b>${esc(p.titulo)}</b> de ${esc(p.sigla)}, el ${esc(cuando)}. Quedan <span class="quedan ${urgente(p.fecha_limite) ? 'urgente' : ''}">${quedan(p.fecha_limite)}</span>.</p>`;
  } else {
    proximo = `<p class="proximo"><span class="nada">No tienes ninguna entrega pendiente con fecha.</span></p>`;
  }

  return `${avisoSesion()}${correcciones()}${proximo}${regla(futuras)}
    ${grupo('Se ha pasado la fecha', pasadas.map((t) => filaTarea(t, { pasada: true })), 'No constan como entregadas en el campus.')}
    ${grupo('Esta semana', futuras.filter((t) => t.fecha_limite < lunes + 7 * DIA).map((t) => filaTarea(t)))}
    ${grupo('La semana que viene', futuras.filter((t) => t.fecha_limite >= lunes + 7 * DIA && t.fecha_limite < lunes + 14 * DIA).map((t) => filaTarea(t)))}
    ${grupo('Más adelante', futuras.filter((t) => t.fecha_limite >= lunes + 14 * DIA).map((t) => filaTarea(t)))}
    ${grupo('Sin fecha', sinFecha.map((t) => filaTarea(t)))}
    ${!pend.length && S.ultima_sync ? '<p class="vacio">Todo entregado. Si te parece raro, pulsa Sincronizar.</p>' : ''}`;
}

function regla(futuras) {
  const hoy = inicioDia(ahora());
  const pines = [];
  for (const t of futuras) {
    const col = diasEntre(hoy, t.fecha_limite);
    if (col < 28) pines.push({ col, t, fantasma: false });
    const c = cambioDeFecha(t);
    if (c && c.antes) {
      const colAntes = diasEntre(hoy, +c.antes);
      if (colAntes >= 0 && colAntes < 28 && colAntes !== col) pines.push({ col: colAntes, t, fantasma: true });
    }
  }
  const porColumna = {};
  for (const p of pines) (porColumna[p.col] ||= []).push(p);
  const pinesHtml = Object.entries(porColumna).map(([col, lista]) => {
    const fantasma = lista.every((p) => p.fantasma);
    return `<div class="pin ${fantasma ? 'fantasma' : ''}" data-col="${+col + 1}">${lista.map((p) =>
      `<button data-ir="${p.t.id_cm}" class="${p.fantasma ? 'fantasma' : urgente(p.t.fecha_limite) ? 'urgente' : ''}"
        title="${esc(p.t.titulo)}${p.fantasma ? ' (fecha anterior)' : ''}">${esc(p.t.sigla)}</button>`).join('')}</div>`;
  }).join('');
  let dias = '';
  for (let i = 0; i < 28; i++) {
    const x = d(hoy); x.setDate(x.getDate() + i);
    const finde = x.getDay() === 0 || x.getDay() === 6;
    const mes = i === 0 || x.getDate() === 1 ? `<span class="mes">${sinPunto(fMes.format(x))}</span>` : '';
    dias += `<div class="dia ${finde ? 'finde' : ''} ${i === 0 ? 'hoy' : ''}">${i === 0 ? 'hoy' : x.getDate()}${mes}</div>`;
  }
  const hayFantasmas = pines.some((p) => p.fantasma);
  return `<div class="regla" aria-label="Entregas de los próximos 28 días">
    <div class="regla-pines">${pinesHtml}</div><div class="regla-dias">${dias}</div>
    ${hayFantasmas ? '<p class="leyenda">Tachado en rojo: dónde estaba la entrega antes de que cambiaran la fecha.</p>' : ''}</div>`;
}

function colocarPines() {
  document.querySelectorAll('.pin[data-col]').forEach((el) => { el.style.gridColumn = el.dataset.col; });
}

function entregadas() {
  const hechas = S.tareas.filter((t) => t.estado === 'entregada')
    .sort((a, b) => (b.fecha_limite || 0) - (a.fecha_limite || 0));
  if (!hechas.length) return '<p class="vacio">Todavía no hay entregas enviadas.</p>';
  return avisoSesion() + grupo('Enviadas', hechas.map((t) => filaTarea(t, { hecha: true })), 'La fecha es la fecha límite que tenía.');
}

function notas() {
  if (!S.modulos.length) return '<p class="vacio">Aún no hay módulos. Pulsa Sincronizar.</p>';
  return avisoSesion() + S.modulos.map((m) => {
    const ts = S.tareas.filter((t) => t.id_curso === m.id_curso && (t.nota_texto || t.estado === 'entregada'));
    const filas = ts.map((t) => `<div class="calif"><span>${esc(t.titulo)}</span>
      <span class="valor">${t.nota_texto ? esc(t.nota_texto) : '<span class="pendiente">sin corregir</span>'}</span></div>`).join('');
    return `<section class="modulo"><div class="modulo-cab"><span class="sigla">${esc(m.sigla)}</span>
      <span class="nombre">${esc(nombreModulo(m.nombre))}</span>
      ${m.nota_curso && m.nota_curso !== '-' ? `<span class="global">${esc(m.nota_curso)}</span>` : ''}</div>
      ${filas || '<div class="calif"><span class="pendiente">Nada entregado ni corregido todavía.</span><span></span></div>'}</section>`;
  }).join('');
}

function agenda() {
  if (!S.eventos.length) return '<p class="vacio">No hay tutorías ni otras actividades en los próximos días.</p>';
  const filas = S.eventos.map((e) => {
    const fin = e.duracion ? `–${fHora.format(d(e.inicio + e.duracion))}` : '';
    const titulo = e.url && e.url.startsWith(S.sitio + '/')
      ? `<a href="#" class="titulo" data-abrir="${esc(e.url)}">${esc(e.titulo)}</a>` : `<span class="titulo">${esc(e.titulo)}</span>`;
    return `<li class="fila"><div class="fecha"><span class="num">${d(e.inicio).getDate()}</span>
      <span class="sem">${sinPunto(fSem.format(d(e.inicio)))} ${sinPunto(fMes.format(d(e.inicio)))}</span></div>
      <div class="que">${titulo}<span class="mod">${fHora.format(d(e.inicio))}${fin}</span></div>
      <div class="cuando"><span class="sigla">${esc(e.sigla || '')}</span><span class="hora">${diasEntre(ahora(), e.inicio) === 0 ? 'hoy' : diasEntre(ahora(), e.inicio) === 1 ? 'mañana' : `en ${diasEntre(ahora(), e.inicio)} días`}</span></div></li>`;
  });
  return grupo('Próximas tutorías y actividades', filas, 'El campus solo enseña las próximas semanas.');
}

function cambios() {
  if (!S.cambios.length) return '<p class="vacio">Sin cambios desde la primera sincronización. Aquí quedará apuntado cada vez que muevan una fecha, publiquen una nota o aparezca algo nuevo.</p>';
  const filas = S.cambios.map((c) => `<li class="fila"><div class="fecha"><span class="num">${d(c.detectado).getDate()}</span>
    <span class="sem">${sinPunto(fMes.format(d(c.detectado)))}</span></div>
    <div class="que">${textoCambio(c)}</div><div class="cuando"><span class="hora">${fHora.format(d(c.detectado))}</span></div></li>`);
  return `${grupo('Historial de cambios', filas, 'La fecha de la izquierda es cuándo lo detectó Plazo.')}`;
}

function ajustes() {
  const msg = avisoAjustes ? `<p class="error">${esc(avisoAjustes)}</p>` : '';
  avisoAjustes = '';
  return `<div class="ajustes">${msg}
    <section><h2>Conexión</h2>
      <p>${S.sesion === 'activa' ? 'Sesión del campus activa: Plazo la mantiene abierta mientras el ordenador está encendido.' : 'Sin sesión del campus: entregas y notas no se actualizan.'}
      ${S.ical ? 'Las fechas también llegan por el calendario iCal, que no caduca.' : ''} Sincroniza cada 2 horas.</p>
      <div class="fila-botones">${S.sesion === 'activa' ? '' : '<button class="boton" data-accion="login">Entrar en el campus</button>'}
      <button class="boton peligro" data-accion="logout">Desconectar del campus</button></div></section>
    <section><h2>Versión</h2>
      <p>Plazo ${esc(S.version)}. Se actualiza solo: comprueba si hay versión nueva al arrancar y cada 6 horas.</p>
      ${S.actualizacion_error ? `<p>La última comprobación falló: ${esc(S.actualizacion_error)}</p>` : ''}
      <button class="boton suave" data-accion="actualizar">Buscar actualización ahora</button></section>
    <section><h2>Dirección del campus</h2>
      <p>Cuando empiece el curso que viene cambiará (por ejemplo, campusonline2027). Al cambiarla tendrás que volver a conectar.</p>
      <form class="campo" data-form="sitio"><input type="url" name="sitio" value="${esc(S.sitio)}" required aria-label="Dirección del campus">
      <button class="boton suave">Guardar</button></form></section>
    <section><h2>Arranque</h2>
      <label class="check"><input type="checkbox" data-accion="autostart" ${S.autostart ? 'checked' : ''}> Abrir Plazo en segundo plano al encender el ordenador</label>
      <p>Sin esto, solo avisa mientras tengas Plazo abierto.</p></section>
    <section><h2>Tu base de datos</h2>
      <p>Todo lo que lee Plazo queda en un archivo SQLite que puedes abrir con DB Browser for SQLite o consultar con SQL.</p>
      <code class="ruta">${esc(S.ruta_bd)}</code></section>
    <section><h2>Cerrar Plazo</h2>
      <p>Cerrar esta ventana no detiene los avisos. Este botón sí lo para todo hasta que vuelvas a abrirlo.</p>
      <button class="boton suave" data-accion="salir">Cerrar Plazo del todo</button></section></div>`;
}

// ---------- eventos ----------
document.addEventListener('click', (ev) => {
  const el = ev.target.closest('[data-vista],[data-accion],[data-abrir],[data-ir]');
  if (!el) return;
  if (el.dataset.vista) { vista = el.dataset.vista; pintar(); window.scrollTo(0, 0); return; }
  if (el.dataset.abrir) { ev.preventDefault(); accion('/api/abrir', { url: el.dataset.abrir }); return; }
  if (el.dataset.ir) {
    const fila = document.getElementById('t-' + el.dataset.ir);
    if (fila) {
      fila.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' });
      fila.classList.add('resaltada'); setTimeout(() => fila.classList.remove('resaltada'), 1600);
    }
    return;
  }
  switch (el.dataset.accion) {
    case 'sync': accion('/api/sync'); break;
    case 'login': accion('/api/login'); break;
        case 'leidos': accion('/api/cambios/leidos'); break;
    case 'logout': if (confirm('¿Desconectar Plazo del campus? Tus datos se quedan guardados.')) accion('/api/logout'); break;
    case 'actualizar': accion('/api/actualizar'); break;
    case 'salir': api('/api/salir', {}).finally(() => { document.getElementById('app').innerHTML = '<p class="caido">Plazo está cerrado. Ya puedes cerrar esta ventana.</p>'; clearTimeout(temporizador); }); break;
  }
});
document.addEventListener('change', (ev) => {
  if (ev.target.dataset.accion === 'autostart') accion('/api/ajustes', { autostart: ev.target.checked });
});
document.addEventListener('submit', (ev) => {
  if (ev.target.dataset.form === 'sitio') {
    ev.preventDefault();
    accion('/api/ajustes', { sitio: new FormData(ev.target).get('sitio') });
  }
});
setInterval(() => { if (S && S.conectado && vista !== 'ajustes') pintar(); }, 60000);
refrescar();
