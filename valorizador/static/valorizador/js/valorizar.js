/* ==========================================================================
   valorizar.js — pantalla de valorización
   · selección de contratos → hidden contract_ids
   · mostrar/ocultar parámetros de crédito según "Calcular CVA / DVA"
   · coloreado del mapa de calor de sensibilidad
   ========================================================================== */
(function () {
    'use strict';

    // ── 1. Selección de contratos ────────────────────────────────────
    var form = document.getElementById('valorizar-form');
    var hidden = document.getElementById('id_contract_ids');

    function sincronizarSeleccion() {
        if (!hidden) return;
        hidden.value = App.seleccionados('contratos').join(',');
    }

    if (form) {
        form.addEventListener('change', sincronizarSeleccion);
        form.addEventListener('click', function (ev) {
            if (ev.target.closest('[data-check-set]')) {
                setTimeout(sincronizarSeleccion, 0);
            }
        });
        form.addEventListener('submit', sincronizarSeleccion);
        sincronizarSeleccion();
    }

    // ── 2. Parámetros de crédito condicionales ───────────────────────
    var cva = document.getElementById('id_calc_cva');
    var bloqueCredito = document.getElementById('bloque-credito');

    function alternarCredito() {
        if (!cva || !bloqueCredito) return;
        bloqueCredito.classList.toggle('hidden', !cva.checked);
    }

    if (cva) {
        cva.addEventListener('change', alternarCredito);
        alternarCredito();
    }

    // ── 3. Mapa de calor ─────────────────────────────────────────────
    var heat = document.getElementById('heatmap');
    if (heat) {
        var min = parseFloat(heat.getAttribute('data-min'));
        var max = parseFloat(heat.getAttribute('data-max'));
        var base = parseFloat(heat.getAttribute('data-base'));
        var rango = Math.max(Math.abs(max - base), Math.abs(base - min), 1e-9);

        heat.querySelectorAll('td[data-mtm]').forEach(function (td) {
            var v = parseFloat(td.getAttribute('data-mtm'));
            if (!isFinite(v)) return;
            var t = Math.max(-1, Math.min(1, (v - base) / rango));
            var alfa = (0.08 + Math.abs(t) * 0.52).toFixed(3);
            if (t > 0.002) {
                td.style.background = 'rgba(16, 185, 129, ' + alfa + ')';
            } else if (t < -0.002) {
                td.style.background = 'rgba(206, 44, 44, ' + alfa + ')';
            }
            var etiqueta = td.querySelector('.cell-main');
            if (etiqueta) etiqueta.classList.add(v < 0 ? 'neg' : 'pos');
        });
    }

    // ── 4. Gráfico de MtM por contraparte del resultado ──────────────
    // Los datos se leen de la propia tabla para no inyectar JSON en la página.
    var tablaCP = document.getElementById('tabla-contraparte');
    var lienzo = document.getElementById('chartResultCP');
    if (tablaCP && lienzo && typeof Chart !== 'undefined') {
        var filas = Array.prototype.slice.call(tablaCP.querySelectorAll('tbody tr[data-cp]'))
            .map(function (tr) {
                return { nombre: tr.getAttribute('data-cp'), mtm: parseFloat(tr.getAttribute('data-mtm')) };
            })
            .filter(function (f) { return isFinite(f.mtm); });
        if (filas.length) {
            new Chart(lienzo, {
                type: 'bar',
                data: {
                    labels: filas.map(function (f) { return f.nombre; }),
                    datasets: [{
                        label: 'MtM',
                        data: filas.map(function (f) { return f.mtm; }),
                        backgroundColor: filas.map(function (f) {
                            return f.mtm >= 0 ? 'rgba(16,185,129,.75)' : 'rgba(206,44,44,.75)';
                        }),
                        borderWidth: 0,
                        borderRadius: 4
                    }]
                },
                options: App.chartOpts({
                    plugins: {
                        tooltip: {
                            callbacks: { label: function (ctx) { return 'MtM: ' + App.clp(ctx.parsed.y); } }
                        }
                    }
                })
            });
        }
    }
})();
