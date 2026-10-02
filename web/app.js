/* Nexus · panel de certificados de Bomberos.
 * Seguridad: todo el contenido se inserta con textContent / createElement (nunca innerHTML),
 * así ningún dato de la página oficial puede ejecutar código en el panel. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const meta = (name) => (document.querySelector(`meta[name="${name}"]`) || {}).content || '';
  const PORTABLE = meta('nexus-modo') === 'portable';
  const TOKEN = meta('nexus-token');
  if (PORTABLE) document.body.classList.add('modo-portable');

  /* ---------- iconos ---------- */
  const NS = 'http://www.w3.org/2000/svg';
  const ICONS = {
    shield: ['M12 3 4.5 6.2v5.3c0 4.6 3.1 7.9 7.5 9.5 4.4-1.6 7.5-4.9 7.5-9.5V6.2L12 3Z', 'M8.4 12.2 10.8 14.6 15.8 9.6'],
    refresh: ['M20 11a8 8 0 0 0-14.8-4L4 9', 'M4 4v5h5', 'M4 13a8 8 0 0 0 14.8 4L20 15', 'M20 20v-5h-5'],
    stop: ['M7 7h10v10H7z'],
    search: ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Z', 'm20 20-3.5-3.5'],
    download: ['M12 3v12', 'm8 11 4 4 4-4', 'M5 20h14'],
    sheet: ['M4 4h16v16H4z', 'M4 10h16', 'M4 15h16', 'M10 4v16'],
    share: ['M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7', 'M12 3v12', 'm8 7 4-4 4 4'],
    external: ['M14 4h6v6', 'M20 4 11 13', 'M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5'],
    bolt: ['M13 2 4 14h7l-1 8 9-12h-7l1-8Z'],
    copy: ['M9 9h11v11H9z', 'M5 15H4V4h11v1'],
    close: ['M6 6l12 12', 'M18 6 6 18'],
  };
  function icon(name) {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('class', 'i');
    svg.setAttribute('aria-hidden', 'true');
    for (const d of ICONS[name] || []) {
      const p = document.createElementNS(NS, 'path');
      p.setAttribute('d', d);
      svg.appendChild(p);
    }
    return svg;
  }
  document.querySelectorAll('[data-icon]').forEach((el) => el.appendChild(icon(el.dataset.icon)));

  /* ---------- utilidades ---------- */
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v == null || v === false) continue;
        if (k === 'class') el.className = v;
        else if (k === 'text') el.textContent = v;
        else if (k === 'dataset') Object.assign(el.dataset, v);
        else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v === true ? '' : String(v));
      }
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const nf = new Intl.NumberFormat('es-CO');
  const num = (x) => nf.format(x || 0);
  const collator = new Intl.Collator('es', { sensitivity: 'base', numeric: true });
  const norm = (s) => (s == null ? '' : String(s)).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const isIso = (s) => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s);
  const fdate = (s) => (isIso(s) ? `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : s || '');
  const pad = (n) => String(n).padStart(2, '0');
  const now = new Date();
  const TODAY = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const dayNum = (iso) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86400000;
  function fdatetime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function relTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const s = (Date.now() - d.getTime()) / 1000;
    if (isNaN(s)) return '';
    if (s < 45) return 'hace un momento';
    if (s < 3600) return `hace ${Math.round(s / 60)} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
    return `el ${fdatetime(iso)}`;
  }
  const store = {
    get(k, d) { try { const v = localStorage.getItem('nexus.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('nexus.' + k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } },
  };

  function toast(msg, kind) {
    const t = h('div', { class: 'toast' + (kind ? ' ' + kind : ''), role: 'status' }, msg);
    $('toasts').appendChild(t);
    setTimeout(() => t.remove(), kind === 'bad' ? 5200 : 2600);
  }
  async function copy(text, label) {
    try { await navigator.clipboard.writeText(text); }
    catch {
      const ta = h('textarea', { 'aria-hidden': 'true' }); ta.value = text;
      document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
    }
    toast(label || 'Copiado');
  }
  function download(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = h('a', { href: url, download: name });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  /* ---------- estado ---------- */
  const STATUS = {
    vigente: 'Vigente', porvencer: 'Por vencer', vencido: 'Vencido', sinfecha: 'Validado',
    invalido: 'No válido', vacio: 'Sin certificado', error: 'Error',
  };
  const STATUS_RANK = { vigente: 0, porvencer: 1, sinfecha: 2, vencido: 3, invalido: 4, vacio: 5, error: 6 };
  const ORIGEN = { importado: 'Importado del sistema anterior', consulta: 'Consulta automática' };

  const S = {
    items: [], byId: new Map(), filtered: [], meta: {}, terms: [],
    q: '', estado: store.get('estado', 'ok'), vig: store.get('vig', 'all'), soloNuevos: false,
    sortKey: store.get('sortKey', 'consecutivo'), sortDir: store.get('sortDir', -1),
    page: 1, size: store.get('size', '100'),
    desde: null, running: false, lastDelta: 0, sel: null, lastSync: null, progressHideTimer: 0,
  };

  function enrich(it) {
    it._key = (it.anio || 0) * 1e12 + (it.numero || 0);
    let vig = '';
    it._dias = null;
    if (it.estado === 'ok') {
      if (isIso(it.fecha_expiracion)) {
        const d = dayNum(it.fecha_expiracion) - dayNum(TODAY);
        it._dias = d;
        vig = d < 0 ? 'vencido' : d <= (S.meta.dias_por_vencer || 30) ? 'porvencer' : 'vigente';
      } else vig = 'sinfecha';
    }
    it._vig = vig;
    it._estado = it.estado === 'ok' ? vig : it.estado;
    it._nuevo = it.origen !== 'importado' && !!it.primera_vez && it.primera_vez.slice(0, 10) === TODAY;
    it._s = norm([
      it.consecutivo, it.numero, it.contribuyente, it.identificacion, it.direccion, it.ref_catastral,
      fdate(it.fecha_acta), fdate(it.fecha_expedicion), fdate(it.fecha_expiracion), it.actividad,
      STATUS[it._estado], it.detalle,
    ].filter(Boolean).join(' '));
    return it;
  }

  function setItems(items) {
    S.items = items.map(enrich);
    S.byId = new Map(S.items.map((it) => [it.consecutivo, it]));
  }
  function merge(items) {
    for (const raw of items) {
      const it = enrich(raw);
      const prev = S.byId.get(it.consecutivo);
      if (prev) {
        if (prev.campos && !it.campos) it.campos = prev.campos;
        S.items[S.items.indexOf(prev)] = it;
      } else S.items.push(it);
      S.byId.set(it.consecutivo, it);
    }
  }

  /* ---------- API ---------- */
  async function api(path, opts = {}) {
    const init = { method: opts.method || 'GET', headers: { 'X-Nexus-Token': TOKEN }, cache: 'no-store', credentials: 'same-origin' };
    if (opts.body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.body);
    }
    const r = await fetch(path, init);
    if (opts.raw) {
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
      return r;
    }
    const data = await r.json().catch(() => ({}));
    if (!r.ok && !(opts.ok || []).includes(r.status)) throw new Error(data.error || `HTTP ${r.status}`);
    data._status = r.status;
    return data;
  }
  function certUrl(consec) {
    const base = S.meta.url_base || '';
    if (!/^https?:\/\//i.test(base)) return '#';
    return `${base}?${encodeURIComponent(S.meta.parametro || 'csctvo')}=${encodeURIComponent(consec)}`;
  }

  /* ---------- filtros y orden ---------- */
  function sortValue(it, key) {
    if (key === 'consecutivo') return it._key;
    if (key === '_estado') return (STATUS_RANK[it._estado] ?? 9) * 1e5 + (it._dias ?? 0);
    return it[key] || '';
  }
  function compare(a, b) {
    const k = S.sortKey;
    const x = sortValue(a, k), y = sortValue(b, k);
    if (typeof x === 'number') return (x - y) * S.sortDir;
    if (!x && y) return 1;
    if (x && !y) return -1;
    const c = k.startsWith('fecha') ? (x < y ? -1 : x > y ? 1 : 0) : collator.compare(x, y);
    return (c || a._key - b._key) * S.sortDir;
  }
  function applyFilters(resetPage = true) {
    if (resetPage) S.page = 1;
    S.terms = norm(S.q).split(/\s+/).filter(Boolean);
    S.filtered = S.items.filter((it) =>
      (S.estado === 'all' || it.estado === S.estado) &&
      (S.vig === 'all' || it._vig === S.vig) &&
      (!S.soloNuevos || it._nuevo) &&
      S.terms.every((t) => it._s.includes(t)));
    S.filtered.sort(compare);
    renderTable();
  }

  /* resaltado de coincidencias sin importar tildes ni mayúsculas */
  function hl(text) {
    text = text == null ? '' : String(text);
    if (!S.terms.length || !text) return document.createTextNode(text);
    let ns = '';
    const map = [];
    for (let i = 0; i < text.length; i++) {
      const c = norm(text[i]);
      for (let k = 0; k < c.length; k++) { ns += c[k]; map.push(i); }
    }
    const ranges = [];
    for (const t of S.terms) {
      let from = 0, idx;
      while ((idx = ns.indexOf(t, from)) !== -1) {
        ranges.push([map[idx], map[idx + t.length - 1] + 1]);
        from = idx + t.length;
      }
    }
    if (!ranges.length) return document.createTextNode(text);
    ranges.sort((a, b) => a[0] - b[0]);
    const merged = [ranges[0]];
    for (const r of ranges.slice(1)) {
      const last = merged[merged.length - 1];
      if (r[0] <= last[1]) last[1] = Math.max(last[1], r[1]); else merged.push(r);
    }
    const frag = document.createDocumentFragment();
    let pos = 0;
    for (const [a, b] of merged) {
      if (a > pos) frag.appendChild(document.createTextNode(text.slice(pos, a)));
      frag.appendChild(h('mark', null, text.slice(a, b)));
      pos = b;
    }
    if (pos < text.length) frag.appendChild(document.createTextNode(text.slice(pos)));
    return frag;
  }

  function statusChip(it) {
    const k = it._estado || 'vacio';
    let label = STATUS[k] || k;
    if (k === 'porvencer' && it._dias != null) label += ` · ${it._dias} d`;
    const title = it.estado === 'ok' && it._dias != null
      ? (it._dias < 0 ? `Venció hace ${-it._dias} días` : `Vence en ${it._dias} días`)
      : it.detalle || label;
    return h('span', { class: `status st-${k}`, title }, label);
  }

  /* ---------- tabla ---------- */
  function rowFor(it, n) {
    const ok = it.estado === 'ok' || it.estado === 'invalido';
    return h('tr', { dataset: { c: it.consecutivo }, class: it.consecutivo === S.sel ? 'selected' : null },
      h('td', { class: 'num' }, String(n)),
      h('td', null, h('button', { class: 'copy-code', type: 'button', title: 'Copiar consecutivo', dataset: { copy: it.consecutivo } }, hl(it.consecutivo))),
      ok
        ? h('td', { class: 'contrib' }, hl(it.contribuyente || '—'), it._nuevo && h('span', { class: 'badge-new' }, 'NUEVO'))
        : h('td', { class: 'contrib muted' }, it.detalle || STATUS[it.estado] || ''),
      h('td', { class: 'mono' }, hl(it.identificacion || '')),
      h('td', { class: 'address' }, hl(it.direccion || '')),
      h('td', { class: 'mono cadastral' }, hl(it.ref_catastral || '')),
      h('td', { class: 'date' }, hl(fdate(it.fecha_acta))),
      h('td', { class: 'date' }, hl(fdate(it.fecha_expedicion))),
      h('td', { class: 'date' }, hl(fdate(it.fecha_expiracion))),
      h('td', null, statusChip(it)),
      h('td', { class: 'open-cell' },
        h('a', { class: 'open-cert', href: certUrl(it.consecutivo), target: '_blank', rel: 'noopener noreferrer', 'aria-label': `Abrir certificado ${it.consecutivo}` },
          icon('external'), 'Abrir')));
  }

  function renderTable() {
    const total = S.filtered.length;
    const size = S.size === 'all' ? Math.max(total, 1) : Number(S.size);
    const pages = Math.max(1, Math.ceil(total / size));
    S.page = Math.min(Math.max(1, S.page), pages);
    const start = (S.page - 1) * size;
    const end = Math.min(start + size, total);
    const frag = document.createDocumentFragment();
    for (let i = start; i < end; i++) frag.appendChild(rowFor(S.filtered[i], i + 1));
    const tbody = $('tbody');
    tbody.replaceChildren(frag);
    $('empty').hidden = total > 0;
    $('table').hidden = total === 0;

    const counter = $('counter');
    counter.replaceChildren(h('strong', null, num(total)), ` de ${num(S.items.length)} registros`);
    if (S.soloNuevos) {
      counter.append(' · ', h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => { S.soloNuevos = false; syncKpiActive(); applyFilters(); } }, 'Solo nuevos de hoy ✕'));
    }
    $('pageInfo').textContent = total ? `Mostrando ${num(start + 1)}–${num(end)} de ${num(total)}` : '0 registros';
    $('pageNumber').textContent = `Página ${num(S.page)} de ${num(pages)}`;
    $('prev').disabled = S.page <= 1;
    $('next').disabled = S.page >= pages;
    if (!S.items.length) {
      $('empty').replaceChildren(h('strong', null, 'Aún no hay datos'),
        PORTABLE ? 'Esta copia no contiene registros.' : 'Pulsa «Actualizar» para traer los certificados.');
    } else if (!total) {
      $('empty').replaceChildren(h('strong', null, 'Sin resultados'), 'No hay registros que coincidan con esta búsqueda o filtro.');
    }
    document.querySelectorAll('th.sortable').forEach((th) => {
      th.classList.toggle('sorted-asc', th.dataset.key === S.sortKey && S.sortDir === 1);
      th.classList.toggle('sorted-desc', th.dataset.key === S.sortKey && S.sortDir === -1);
      th.setAttribute('aria-sort', th.dataset.key === S.sortKey ? (S.sortDir === 1 ? 'ascending' : 'descending') : 'none');
    });
  }

  /* ---------- KPIs ---------- */
  function renderKpis() {
    let ok = 0, vig = 0, pv = 0, ven = 0, nuevos = 0, consultados = 0;
    for (const it of S.items) {
      consultados++;
      if (it.estado === 'ok') {
        ok++;
        if (it._vig === 'vigente') vig++;
        else if (it._vig === 'porvencer') pv++;
        else if (it._vig === 'vencido') ven++;
      }
      if (it._nuevo) nuevos++;
    }
    const pct = (x) => (ok ? `${Math.round((x / ok) * 100)}% del total` : '');
    $('kOk').textContent = num(ok);
    $('kOkSub').textContent = `${num(consultados)} consecutivos consultados`;
    $('kVig').textContent = num(vig); $('kVigSub').textContent = pct(vig);
    $('kPv').textContent = num(pv); $('kPvSub').textContent = `próximos ${S.meta.dias_por_vencer || 30} días`;
    $('kVen').textContent = num(ven); $('kVenSub').textContent = pct(ven);
    const last = S.meta.ultimo;
    $('kLast').textContent = last ? last.consecutivo : '—';
    $('kLastSub').textContent = last ? (last.contribuyente || '') : '';
    $('kNew').textContent = num(nuevos);
    $('kNewSub').textContent = S.meta.ultimo_escaneo ? `última búsqueda: +${num(S.meta.ultimo_escaneo.nuevos)}` : '';
    syncKpiActive();
  }
  function syncKpiActive() {
    document.querySelectorAll('.kpi').forEach((k) => {
      const v = k.dataset.kpi;
      const active = (v === 'nuevos' && S.soloNuevos) ||
        (!S.soloNuevos && S.estado === 'ok' && ((v === 'ok' && S.vig === 'all') || v === S.vig));
      k.classList.toggle('active', active);
    });
    document.querySelectorAll('#segEstado button').forEach((b) => b.classList.toggle('active', b.dataset.v === S.estado));
    document.querySelectorAll('#segVig button').forEach((b) => b.classList.toggle('active', b.dataset.v === S.vig));
  }

  function renderAll(resetPage = false) {
    renderKpis();
    applyFilters(resetPage);
    renderSync();
    $('footText').textContent = `Nexus ${S.meta.version || ''} · ${num(S.items.length)} registros · fuente: Alcaldía de Barranquilla`;
    if (PORTABLE) {
      $('portableNote').textContent = `Copia portable de solo lectura · generada el ${fdatetime(S.meta.generado)} · ${num(S.items.length)} registros. Para traer datos nuevos usa Nexus en el computador.`;
    }
    if (S.sel && $('drawer').classList.contains('open')) fillDrawer(S.byId.get(S.sel));
  }

  /* ---------- estado de sincronización ---------- */
  function renderSync() {
    const el = $('sync');
    el.classList.remove('ok', 'run', 'bad');
    if (PORTABLE) { el.classList.add('ok'); $('syncText').textContent = `Copia del ${fdatetime(S.meta.generado)}`; return; }
    const esc = S.meta.ultimo_escaneo;
    if (S.running) { el.classList.add('run'); $('syncText').textContent = S.syncRunText || 'Actualizando…'; }
    else if (esc && esc.error_fatal) { el.classList.add('bad'); $('syncText').textContent = 'Sin conexión con la Alcaldía'; el.title = esc.error_fatal; }
    else if (S.meta.ultima_actualizacion) {
      el.classList.add('ok');
      const auto = S.meta.auto_minutos ? ` · auto cada ${S.meta.auto_minutos} min` : '';
      $('syncText').textContent = `Actualizado ${relTime(S.meta.ultima_actualizacion)}${auto}`;
      el.title = `Última actualización completa: ${fdatetime(S.meta.ultima_actualizacion)}`;
    } else $('syncText').textContent = 'Sin actualizar todavía';
    $('btnUpdate').disabled = S.running;
    $('btnUpdate').classList.toggle('spinning', S.running);
  }

  function renderProgress(p) {
    const box = $('progress');
    box.classList.toggle('running', !!p.corriendo);
    box.classList.toggle('failed', !p.corriendo && !!p.error_fatal);
    if (p.corriendo) {
      clearTimeout(S.progressHideTimer);
      S.progressHideTimer = 0;
      box.hidden = false;
    }
    const pct = p.total ? Math.min(1, p.hechos / p.total) : 0;
    $('pBar').style.width = `${p.corriendo ? Math.max(2, pct * 100) : 100}%`;
    $('pPhase').textContent = p.fase || (p.corriendo ? 'Actualizando…' : 'Listo');
    $('pSub').textContent = p.error_fatal ? p.error_fatal : p.ultimo ? `Último encontrado: ${p.ultimo}` : '';
    $('pDone').textContent = `${num(p.hechos)}${p.total ? ' / ' + num(p.total) : ''}`;
    $('pRate').textContent = `${num(Math.round(p.velocidad))}/s`;
    $('pNew').textContent = num(p.nuevos);
    $('pEmpty').textContent = num(p.vacios);
    $('pErr').textContent = num(p.errores);
    $('pConn').textContent = num(p.limite);
    $('pEta').textContent = p.corriendo ? (p.eta != null ? `${Math.max(1, Math.round(p.eta))} s` : '—') : `${p.segundos} s total`;
    $('btnStop').hidden = !p.corriendo;
    S.syncRunText = `Actualizando… ${Math.round(pct * 100)}%`;
  }

  /* ---------- carga y sondeo ---------- */
  async function loadAll() {
    const d = await api('/api/certificados');
    S.meta = d.meta;
    setItems(d.items);
    S.desde = d.meta.ahora;
    renderAll(false);
  }
  async function loadDelta() {
    const d = await api('/api/certificados?desde=' + encodeURIComponent(S.desde || ''));
    S.meta = d.meta;
    S.desde = d.meta.ahora;
    if (d.items.length) { merge(d.items); renderAll(false); } else renderSync();
  }

  let pollTimer = 0, pollBusy = false, pollSoon = false;
  function schedulePoll(ms) {
    if (pollBusy) { pollSoon = true; return; }
    clearTimeout(pollTimer);
    pollTimer = setTimeout(poll, ms);
  }
  async function poll() {
    let delay = 4000;
    pollBusy = true;
    try {
      const d = await api('/api/estado');
      const prevMeta = S.meta;
      S.meta = Object.assign({}, S.meta, d.meta);
      const p = d.progreso;
      renderProgress(p);
      if (p.corriendo) {
        delay = 600;
        if (!S.running) { S.running = true; renderSync(); }
        if (Date.now() - S.lastDelta > 1500) { S.lastDelta = Date.now(); await loadDelta(); }
        renderSync();
      } else if (S.running) {
        S.running = false;
        await loadAll();
        if (p.error_fatal) toast(p.error_fatal, 'bad');
        else if (p.cancelado) toast('Actualización detenida');
        else toast(`Listo · ${num(p.nuevos)} nuevos · ${num(p.hechos)} consultas en ${p.segundos} s`, 'good');
        S.progressHideTimer = setTimeout(() => { $('progress').hidden = true; }, 7000);
      } else if (prevMeta.total !== d.meta.total || prevMeta.ultima_actualizacion !== d.meta.ultima_actualizacion) {
        await loadAll();
      } else renderSync();
    } catch (e) {
      const el = $('sync');
      el.classList.remove('ok', 'run');
      el.classList.add('bad');
      $('syncText').textContent = 'Nexus está cerrado';
      delay = 5000;
    }
    pollBusy = false;
    schedulePoll(pollSoon ? 200 : delay);
    pollSoon = false;
  }

  async function startUpdate() {
    if (PORTABLE || S.running) return;
    try {
      const d = await api('/api/actualizar', { method: 'POST', body: {}, ok: [409] });
      if (d._status === 409) toast('Ya hay una actualización en curso');
      S.running = true;
      renderProgress(d.progreso);
      renderSync();
      schedulePoll(200);
    } catch (e) { toast('No se pudo iniciar: ' + e.message, 'bad'); }
  }

  /* ---------- ficha (drawer) ---------- */
  function dl(target, pairs) {
    const box = $(target);
    const kids = [];
    for (const [k, v] of pairs) {
      if (v == null || v === '') continue;
      kids.push(h('dt', null, k), h('dd', null, v instanceof Node ? v : String(v)));
    }
    if (!kids.length) kids.push(h('div', { class: 'empty-row' }, 'Sin datos.'));
    box.replaceChildren(...kids);
  }
  function fillDrawer(it) {
    if (!it) return;
    $('dConsec').textContent = it.consecutivo;
    $('dConsec').dataset.copy = it.consecutivo;
    $('dTitle').textContent = it.contribuyente || STATUS[it.estado] || 'Certificado';
    const chips = [statusChip(it)];
    if (it._nuevo) chips.push(h('span', { class: 'badge-new' }, 'NUEVO'));
    $('dChips').replaceChildren(...chips);
    $('dOpen').setAttribute('href', certUrl(it.consecutivo));
    let venc = fdate(it.fecha_expiracion);
    if (it._dias != null) venc += it._dias < 0 ? `  ·  venció hace ${num(-it._dias)} días` : `  ·  vence en ${num(it._dias)} días`;
    dl('dMain', [
      ['Consecutivo', it.consecutivo], ['Contribuyente', it.contribuyente], ['Identificación', it.identificacion],
      ['Dirección', it.direccion], ['Ref. catastral', it.ref_catastral], ['Actividad', it.actividad],
      ['Fecha acta', fdate(it.fecha_acta)], ['Expedición', fdate(it.fecha_expedicion)], ['Expiración', venc],
      ['Estado en la página', it.estado_pagina],
    ]);
    if (it.campos) dl('dAll', it.campos.map(([k, v]) => [k, v || '—']));
    else $('dAll').replaceChildren(h('div', { class: 'empty-row' }, PORTABLE ? 'No disponible.' : 'Cargando…'));
    dl('dLog', [
      ['Estado en Nexus', STATUS[it._estado] || it.estado], ['Origen', ORIGEN[it.origen] || it.origen],
      ['Primera vez', it.primera_vez ? fdatetime(it.primera_vez) : ''], ['Última consulta', fdatetime(it.actualizado)],
      ['Detalle', it.detalle],
    ]);
  }
  async function openDrawer(consec) {
    const it = S.byId.get(consec);
    if (!it) return;
    S.sel = consec;
    document.querySelectorAll('#tbody tr.selected').forEach((tr) => tr.classList.remove('selected'));
    const tr = document.querySelector(`#tbody tr[data-c="${CSS.escape(consec)}"]`);
    if (tr) tr.classList.add('selected');
    fillDrawer(it);
    $('drawer').classList.add('open');
    $('drawer').setAttribute('aria-hidden', 'false');
    $('scrim').hidden = false;
    $('dClose').focus({ preventScroll: true });
    if (!it.campos && !PORTABLE) {
      try {
        const full = await api('/api/certificado?c=' + encodeURIComponent(consec));
        it.campos = full.campos || [];
        if (S.sel === consec) fillDrawer(it);
      } catch { $('dAll').replaceChildren(h('div', { class: 'empty-row' }, 'No disponible.')); }
    }
  }
  function closeDrawer() {
    $('drawer').classList.remove('open');
    $('drawer').setAttribute('aria-hidden', 'true');
    $('scrim').hidden = true;
  }
  function fichaTexto(it) {
    const lines = [`${it.contribuyente || ''}`, `Consecutivo: ${it.consecutivo}`];
    const pares = [['Identificación', it.identificacion], ['Dirección', it.direccion], ['Ref. catastral', it.ref_catastral],
      ['Fecha acta', fdate(it.fecha_acta)], ['Expedición', fdate(it.fecha_expedicion)], ['Expiración', fdate(it.fecha_expiracion)],
      ['Estado', STATUS[it._estado] || it.estado]];
    for (const [k, v] of pares) if (v) lines.push(`${k}: ${v}`);
    lines.push(certUrl(it.consecutivo));
    return lines.join('\n');
  }

  async function consultarVivo(texto, { abrir = true } = {}) {
    const res = await api('/api/consultar', { method: 'POST', body: { consecutivo: texto } });
    const campos = res.campos;
    merge([res]);
    const it = S.byId.get(res.consecutivo);
    it.campos = campos;
    renderAll(false);
    const c = res.consulta || {};
    if (c.estado === 'ok') toast(`${res.consecutivo} · ${res.contribuyente || 'validado'}`, 'good');
    else if (c.estado === 'vacio') toast(`${res.consecutivo} no tiene certificado registrado`);
    else if (c.estado === 'error') toast(`No se pudo consultar ${res.consecutivo}: ${c.detalle || 'error'}`, 'bad');
    else toast(`${res.consecutivo}: ${STATUS[c.estado] || c.estado}`);
    if (abrir && (res.estado === 'ok' || res.estado === 'invalido')) openDrawer(res.consecutivo);
    return it;
  }

  function showLive(it) {
    const box = $('liveResult');
    if (!it) { box.hidden = true; return; }
    const ok = it.estado === 'ok' || it.estado === 'invalido';
    box.replaceChildren(
      statusChip(it),
      h('span', { class: 'mono' }, it.consecutivo),
      ok ? h('span', { class: 'lr-name' }, it.contribuyente || '') : h('span', { class: 'lr-meta' }, it.detalle || ''),
      ok && h('span', { class: 'lr-meta' }, [it.identificacion && `NIT/CC ${it.identificacion}`, it.fecha_expiracion && `vence ${fdate(it.fecha_expiracion)}`].filter(Boolean).join(' · ')),
      ok && h('button', { class: 'btn btn-secondary btn-sm', type: 'button', onclick: () => openDrawer(it.consecutivo) }, 'Ver ficha'));
    box.hidden = false;
  }

  /* ---------- exportar ---------- */
  function exportCsv() {
    const cols = [['Consecutivo', (i) => i.consecutivo], ['Contribuyente', (i) => i.contribuyente], ['Identificación', (i) => i.identificacion],
      ['Dirección', (i) => i.direccion], ['Ref. catastral', (i) => i.ref_catastral], ['Fecha acta', (i) => fdate(i.fecha_acta)],
      ['Fecha expedición', (i) => fdate(i.fecha_expedicion)], ['Fecha expiración', (i) => fdate(i.fecha_expiracion)],
      ['Estado', (i) => STATUS[i._estado] || i.estado], ['Enlace', (i) => certUrl(i.consecutivo)]];
    const q = (v) => {
      let s = v == null ? '' : String(v);
      if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; // evita fórmulas al abrir en Excel
      return '"' + s.replace(/"/g, '""') + '"';
    };
    const lines = [cols.map(([t]) => q(t)).join(';')];
    for (const it of S.filtered) lines.push(cols.map(([, f]) => q(f(it))).join(';'));
    download(new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }), `certificados_bomberos_${TODAY}.csv`);
    toast(`${num(S.filtered.length)} registros exportados a CSV`);
  }
  async function exportServer(formato, btn) {
    btn.disabled = true;
    try {
      const r = await api('/api/exportar', { method: 'POST', body: { formato, consecutivos: S.filtered.map((i) => i.consecutivo) }, raw: true });
      const cd = r.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename="([^"]+)"/);
      download(await r.blob(), m ? m[1] : `certificados.${formato}`);
      toast(`${num(S.filtered.length)} registros exportados`, 'good');
    } catch (e) { toast('No se pudo exportar: ' + e.message, 'bad'); }
    finally { btn.disabled = false; }
  }

  /* ---------- eventos ---------- */
  let qTimer = 0;
  $('q').addEventListener('input', () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { S.q = $('q').value; applyFilters(); }, 70);
  });
  function bindSegment(id, key) {
    $(id).addEventListener('click', (e) => {
      const b = e.target.closest('button[data-v]');
      if (!b) return;
      S[key] = b.dataset.v;
      if (key === 'vig' && S.vig !== 'all') S.estado = 'ok';
      store.set(key, S[key]);
      syncKpiActive();
      applyFilters();
    });
  }
  bindSegment('segEstado', 'estado');
  bindSegment('segVig', 'vig');

  $('kpis').addEventListener('click', (e) => {
    const k = e.target.closest('.kpi');
    if (!k) return;
    const v = k.dataset.kpi;
    if (v === 'ultimo') { if (S.meta.ultimo) openDrawer(S.meta.ultimo.consecutivo); return; }
    if (v === 'nuevos') { S.soloNuevos = !S.soloNuevos; S.estado = 'ok'; S.vig = 'all'; }
    else { S.soloNuevos = false; S.estado = 'ok'; S.vig = v === 'ok' ? 'all' : v; }
    store.set('estado', S.estado); store.set('vig', S.vig);
    syncKpiActive();
    applyFilters();
  });

  document.querySelectorAll('th.sortable').forEach((th) => th.addEventListener('click', () => {
    const k = th.dataset.key;
    S.sortDir = S.sortKey === k ? -S.sortDir : (k === 'consecutivo' || k.startsWith('fecha') ? -1 : 1);
    S.sortKey = k;
    store.set('sortKey', S.sortKey); store.set('sortDir', S.sortDir);
    applyFilters(false);
  }));

  $('pageSize').value = S.size;
  $('pageSize').addEventListener('change', () => { S.size = $('pageSize').value; store.set('size', S.size); applyFilters(); });
  const toTop = () => $('tablewrap').scrollTo({ top: 0, behavior: 'smooth' });
  $('prev').addEventListener('click', () => { S.page--; renderTable(); toTop(); });
  $('next').addEventListener('click', () => { S.page++; renderTable(); toTop(); });

  $('tbody').addEventListener('click', (e) => {
    const cp = e.target.closest('.copy-code');
    if (cp) { copy(cp.dataset.copy, 'Consecutivo copiado'); return; }
    if (e.target.closest('a')) return;
    const tr = e.target.closest('tr[data-c]');
    if (tr) openDrawer(tr.dataset.c);
  });

  $('dClose').addEventListener('click', closeDrawer);
  $('scrim').addEventListener('click', closeDrawer);
  $('dConsec').addEventListener('click', () => copy($('dConsec').dataset.copy, 'Consecutivo copiado'));
  $('dCopy').addEventListener('click', () => { const it = S.byId.get(S.sel); if (it) copy(fichaTexto(it), 'Ficha copiada'); });
  $('dRefresh').addEventListener('click', async () => {
    const btn = $('dRefresh');
    btn.disabled = true; btn.classList.add('spinning');
    try { await consultarVivo(S.sel, { abrir: false }); fillDrawer(S.byId.get(S.sel)); }
    catch (e) { toast('No se pudo consultar: ' + e.message, 'bad'); }
    finally { btn.disabled = false; btn.classList.remove('spinning'); }
  });

  $('liveForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const v = $('liveInput').value.trim();
    if (!/^0*\d{1,15}\s*(?:[-/ ]\s*\d{4})?$/.test(v)) { toast('Escribe un consecutivo, por ejemplo 62667 o 00000062667-2026', 'bad'); return; }
    const btn = $('liveBtn');
    btn.disabled = true;
    try { showLive(await consultarVivo(v)); }
    catch (err) { toast(err.message, 'bad'); }
    finally { btn.disabled = false; }
  });

  $('btnUpdate').addEventListener('click', startUpdate);
  $('btnStop').addEventListener('click', async () => {
    try { await api('/api/detener', { method: 'POST', body: {} }); toast('Deteniendo…'); } catch (e) { toast(e.message, 'bad'); }
  });
  $('expCsv').addEventListener('click', exportCsv);
  $('expXlsx').addEventListener('click', (e) => exportServer('xlsx', e.currentTarget));
  $('expHtml').addEventListener('click', (e) => exportServer('html', e.currentTarget));

  document.addEventListener('keydown', (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement && document.activeElement.tagName);
    if (e.key === 'Escape') {
      if ($('drawer').classList.contains('open')) closeDrawer();
      else if (document.activeElement === $('q') && $('q').value) { $('q').value = ''; S.q = ''; applyFilters(); }
      return;
    }
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === '/') { e.preventDefault(); $('q').focus(); $('q').select(); }
    else if ((e.key === 'u' || e.key === 'U') && !PORTABLE) startUpdate();
  });

  /* ---------- arranque ---------- */
  async function init() {
    syncKpiActive();
    if (PORTABLE) {
      const raw = $('nexus-data');
      const d = raw ? JSON.parse(raw.textContent) : { items: [], meta: {} };
      S.meta = d.meta || {};
      setItems(d.items || []);
      renderAll(true);
      return;
    }
    try { await loadAll(); }
    catch (e) { toast('No se pudo cargar: ' + e.message, 'bad'); }
    poll();
    setInterval(() => { if (!S.running) renderSync(); }, 30000);
  }
  init();
})();
