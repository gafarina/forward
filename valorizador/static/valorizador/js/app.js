/* ==========================================================================
   app.js — utilidades comunes del Valorizador de Forwards v2
   Sin dependencias salvo Chart.js (opcional). No usa localStorage.
   ========================================================================== */
(function (global) {
    'use strict';

    // ── Cookies / CSRF ───────────────────────────────────────────────
    function getCookie(nombre) {
        var salida = null;
        if (document.cookie) {
            document.cookie.split(';').forEach(function (bruto) {
                var c = bruto.trim();
                if (c.indexOf(nombre + '=') === 0) {
                    salida = decodeURIComponent(c.substring(nombre.length + 1));
                }
            });
        }
        return salida;
    }

    function csrfToken() {
        var campo = document.querySelector('input[name=csrfmiddlewaretoken]');
        if (campo && campo.value) return campo.value;
        return getCookie('csrftoken') || '';
    }

    // ── Formato chileno ──────────────────────────────────────────────
    function num(valor, decimales) {
        var v = Number(valor);
        if (!isFinite(v)) return '—';
        return v.toLocaleString('es-CL', {
            minimumFractionDigits: decimales === undefined ? 2 : decimales,
            maximumFractionDigits: decimales === undefined ? 2 : decimales
        });
    }

    function clp(valor) {
        var v = Number(valor);
        if (!isFinite(v)) return '—';
        return '$' + v.toLocaleString('es-CL', { maximumFractionDigits: 0 });
    }

    function compacto(valor) {
        var v = Number(valor);
        if (!isFinite(v)) return '—';
        var abs = Math.abs(v);
        if (abs >= 1e9) return (v / 1e9).toLocaleString('es-CL', { maximumFractionDigits: 1 }) + ' MM MM';
        if (abs >= 1e6) return (v / 1e6).toLocaleString('es-CL', { maximumFractionDigits: 1 }) + ' MM';
        if (abs >= 1e3) return (v / 1e3).toLocaleString('es-CL', { maximumFractionDigits: 0 }) + ' M';
        return num(v, 0);
    }

    /** Lee un número escrito con coma o punto decimal. */
    function parseNum(texto) {
        if (texto === null || texto === undefined) return NaN;
        var s = String(texto).trim().replace(/\s|%|\$/g, '');
        if (!s) return NaN;
        if (s.indexOf(',') > -1 && s.indexOf('.') > -1) {
            s = s.lastIndexOf(',') > s.lastIndexOf('.')
                ? s.replace(/\./g, '').replace(',', '.')
                : s.replace(/,/g, '');
        } else if (s.indexOf(',') > -1) {
            s = s.replace(',', '.');
        }
        return parseFloat(s);
    }

    // ── Colores del tema ─────────────────────────────────────────────
    function oscuro() {
        return global.matchMedia && global.matchMedia('(prefers-color-scheme: dark)').matches;
    }

    function css(varName, fallback) {
        var v = getComputedStyle(document.documentElement).getPropertyValue(varName);
        return (v && v.trim()) || fallback;
    }

    var Tema = {
        get accent() { return css('--accent', '#4f2d7f'); },
        get accentLight() { return css('--accent-light', '#a06dff'); },
        get success() { return css('--success', '#10b981'); },
        get danger() { return css('--danger', '#ce2c2c'); },
        get info() { return css('--info', '#00a4b3'); },
        get warning() { return css('--warning', '#f59e0b'); },
        get grid() { return oscuro() ? 'rgba(255,255,255,.10)' : 'rgba(43,20,77,.09)'; },
        get tick() { return css('--muted', '#666'); },
        get text() { return css('--text', '#2b144d'); }
    };

    /** Opciones base compartidas por todos los gráficos. */
    function chartOpts(extra) {
        var base = {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: false,
                    labels: { color: Tema.text, font: { family: 'Inter', size: 11 } }
                },
                tooltip: {
                    backgroundColor: oscuro() ? '#2a2335' : '#2b144d',
                    titleFont: { family: 'Inter', size: 12 },
                    bodyFont: { family: 'Inter', size: 12 },
                    padding: 10,
                    cornerRadius: 6
                }
            },
            scales: {
                x: {
                    grid: { color: Tema.grid, drawBorder: false },
                    ticks: { color: Tema.tick, font: { family: 'Inter', size: 10 } }
                },
                y: {
                    grid: { color: Tema.grid, drawBorder: false },
                    ticks: {
                        color: Tema.tick,
                        font: { family: 'Inter', size: 10 },
                        callback: function (v) { return compacto(v); }
                    }
                }
            }
        };
        return merge(base, extra || {});
    }

    function merge(a, b) {
        var out = Array.isArray(a) ? a.slice() : Object.assign({}, a);
        Object.keys(b || {}).forEach(function (k) {
            if (b[k] && typeof b[k] === 'object' && !Array.isArray(b[k]) &&
                out[k] && typeof out[k] === 'object' && !Array.isArray(out[k])) {
                out[k] = merge(out[k], b[k]);
            } else {
                out[k] = b[k];
            }
        });
        return out;
    }

    /** Interpola rojo→verde según la posición de `valor` dentro de [min, max]. */
    function colorMtM(valor, min, max) {
        var v = Number(valor);
        if (!isFinite(v)) return 'transparent';
        var rango = Math.max(Math.abs(min), Math.abs(max), 1e-9);
        var t = Math.max(-1, Math.min(1, v / rango));
        var alfa = 0.10 + Math.abs(t) * 0.50;
        if (t > 0) return 'rgba(16, 185, 129, ' + alfa.toFixed(3) + ')';
        if (t < 0) return 'rgba(206, 44, 44, ' + alfa.toFixed(3) + ')';
        return 'transparent';
    }

    /** Lee un <script type="application/json"> por id. */
    function jsonScript(id, porDefecto) {
        var el = document.getElementById(id);
        if (!el) return porDefecto;
        try { return JSON.parse(el.textContent || 'null') ?? porDefecto; }
        catch (e) { return porDefecto; }
    }

    // ── Comportamientos declarativos ─────────────────────────────────
    function initDismiss() {
        document.addEventListener('click', function (ev) {
            var b = ev.target.closest('[data-dismiss]');
            if (!b) return;
            var caja = b.closest('.alert');
            if (caja) caja.remove();
        });
    }

    /** Secciones colapsables: <button class="section-head" aria-expanded>. */
    function initSections() {
        document.addEventListener('click', function (ev) {
            var h = ev.target.closest('.section-head');
            if (!h) return;
            ev.preventDefault();
            var abierto = h.getAttribute('aria-expanded') !== 'false';
            h.setAttribute('aria-expanded', abierto ? 'false' : 'true');
        });
    }

    /** Envío automático de filtros al cambiar un <select data-autosubmit>. */
    function initAutoSubmit() {
        document.addEventListener('change', function (ev) {
            var el = ev.target.closest('[data-autosubmit]');
            if (el && el.form) el.form.submit();
        });
    }

    /** Casillas de selección masiva: data-check-all="grupo" / data-check="grupo". */
    function initCheckAll() {
        document.addEventListener('change', function (ev) {
            var maestro = ev.target.closest('[data-check-all]');
            if (maestro) {
                var grupo = maestro.getAttribute('data-check-all');
                document.querySelectorAll('[data-check="' + grupo + '"]').forEach(function (c) {
                    c.checked = maestro.checked;
                });
                anunciarSeleccion(grupo);
                return;
            }
            var hijo = ev.target.closest('[data-check]');
            if (hijo) anunciarSeleccion(hijo.getAttribute('data-check'));
        });

        document.addEventListener('click', function (ev) {
            var b = ev.target.closest('[data-check-set]');
            if (!b) return;
            ev.preventDefault();
            var grupo = b.getAttribute('data-check-set');
            var valor = b.getAttribute('data-check-value') === '1';
            document.querySelectorAll('[data-check="' + grupo + '"]').forEach(function (c) {
                c.checked = valor;
            });
            var maestro = document.querySelector('[data-check-all="' + grupo + '"]');
            if (maestro) maestro.checked = valor;
            anunciarSeleccion(grupo);
        });
    }

    function seleccionados(grupo) {
        return Array.prototype.slice
            .call(document.querySelectorAll('[data-check="' + grupo + '"]:checked'))
            .map(function (c) { return c.value; });
    }

    function anunciarSeleccion(grupo) {
        var cont = document.querySelector('[data-check-count="' + grupo + '"]');
        if (cont) {
            var n = seleccionados(grupo).length;
            var total = document.querySelectorAll('[data-check="' + grupo + '"]').length;
            cont.textContent = n === 0
                ? 'Ningún contrato marcado: se valorizan los ' + total + ' de la lista.'
                : n + ' de ' + total + ' contratos marcados.';
        }
    }

    global.App = {
        getCookie: getCookie,
        csrfToken: csrfToken,
        num: num,
        clp: clp,
        compacto: compacto,
        parseNum: parseNum,
        Tema: Tema,
        chartOpts: chartOpts,
        colorMtM: colorMtM,
        jsonScript: jsonScript,
        seleccionados: seleccionados,
        anunciarSeleccion: anunciarSeleccion,
        oscuro: oscuro
    };

    function iniciar() {
        initDismiss();
        initSections();
        initAutoSubmit();
        initCheckAll();
        document.querySelectorAll('[data-check-count]').forEach(function (el) {
            anunciarSeleccion(el.getAttribute('data-check-count'));
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciar);
    } else {
        iniciar();
    }
})(window);
