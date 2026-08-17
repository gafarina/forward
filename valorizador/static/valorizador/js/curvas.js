/* ==========================================================================
   curvas.js — editor de nodos de curva (forward y descuento)
   Requiere app.js y Chart.js.
   ========================================================================== */
(function () {
    'use strict';

    var raiz = document.getElementById('curve-editor');
    if (!raiz) return;

    var importUrl = raiz.getAttribute('data-import-url');
    var grafico = null;

    /** @type {{forward: Editor, descuento: Editor}} */
    var editores = {};

    function Editor(tipo) {
        this.tipo = tipo;                       // 'forward' | 'descuento'
        this.decimales = tipo === 'forward' ? 4 : 6;
        this.cuerpo = document.getElementById('tbody-' + tipo);
        this.hidden = document.getElementById('hidden-' + tipo);
        this.contador = document.querySelector('[data-count="' + tipo + '"]');
        this.avisos = document.getElementById('avisos-' + tipo);
    }

    Editor.prototype.filas = function () {
        return Array.prototype.slice.call(this.cuerpo.querySelectorAll('tr'));
    };

    Editor.prototype.agregar = function (dias, valor, foco) {
        var tr = document.createElement('tr');
        tr.innerHTML =
            '<td><input type="text" inputmode="numeric" class="dias" aria-label="Plazo en días"></td>' +
            '<td><input type="text" inputmode="decimal" class="valor" aria-label="Valor del nodo"></td>' +
            '<td class="act"><button type="button" class="btn-icon danger" data-quitar aria-label="Quitar este nodo" title="Quitar">×</button></td>';
        this.cuerpo.appendChild(tr);
        if (dias !== undefined && dias !== null && dias !== '') {
            tr.querySelector('.dias').value = dias;
        }
        if (valor !== undefined && valor !== null && valor !== '') {
            tr.querySelector('.valor').value = String(valor).replace('.', ',');
        }
        if (foco) tr.querySelector('.dias').focus();
        return tr;
    };

    Editor.prototype.limpiar = function () {
        this.cuerpo.innerHTML = '';
    };

    Editor.prototype.cargar = function (puntos) {
        this.limpiar();
        (puntos || []).forEach(function (p) {
            this.agregar(p.tenor_days, p.value);
        }, this);
        if (!this.cuerpo.children.length) this.agregar();
        this.sincronizar();
    };

    /** Lee las filas visibles y devuelve los nodos válidos, ordenados y sin duplicados. */
    Editor.prototype.leer = function () {
        var mapa = {};
        this.filas().forEach(function (tr) {
            var d = App.parseNum(tr.querySelector('.dias').value);
            var v = App.parseNum(tr.querySelector('.valor').value);
            var vacia = !tr.querySelector('.dias').value.trim() && !tr.querySelector('.valor').value.trim();
            tr.classList.toggle('row-error', !vacia && (!isFinite(d) || !isFinite(v) || d < 0));
            if (!isFinite(d) || !isFinite(v) || d < 0) return;
            mapa[Math.round(d)] = v;
        });
        return Object.keys(mapa)
            .map(Number)
            .sort(function (a, b) { return a - b; })
            .map(function (d) { return { tenor_days: d, value: mapa[d] }; });
    };

    Editor.prototype.sincronizar = function () {
        var puntos = this.leer();
        this.hidden.value = JSON.stringify(puntos);
        if (this.contador) {
            this.contador.textContent = puntos.length + (puntos.length === 1 ? ' nodo válido' : ' nodos válidos');
        }
        dibujar();
    };

    Editor.prototype.mostrarAvisos = function (lista, clase) {
        if (!this.avisos) return;
        if (!lista || !lista.length) { this.avisos.innerHTML = ''; return; }
        var items = lista.map(function (a) {
            var li = document.createElement('li');
            li.textContent = a;
            return li.outerHTML;
        }).join('');
        this.avisos.innerHTML =
            '<div class="alert ' + (clase || 'warning') + '">' +
            '<div class="txt"><strong>' + (clase === 'error' ? 'No se pudo importar' : 'Avisos de la importación') +
            '</strong><ul>' + items + '</ul></div>' +
            '<button type="button" class="close" data-dismiss aria-label="Cerrar aviso">&times;</button></div>';
    };

    // ── Pegado desde el portapapeles ─────────────────────────────────
    /** Acepta dos columnas separadas por tabulación, punto y coma o coma+espacio. */
    function parsearPegado(texto) {
        var puntos = [];
        var descartadas = 0;
        texto.split(/\r?\n/).forEach(function (linea) {
            if (!linea.trim()) return;
            var partes = linea.split(/\t|;|\s{2,}|\|/).filter(function (x) { return x.trim() !== ''; });
            if (partes.length < 2) {
                partes = linea.trim().split(/\s+/);
            }
            if (partes.length < 2) { descartadas++; return; }
            var d = App.parseNum(partes[0]);
            var v = App.parseNum(partes[1]);
            if (!isFinite(d) || !isFinite(v)) { descartadas++; return; }
            puntos.push({ tenor_days: Math.round(d), value: v });
        });
        return { puntos: puntos, descartadas: descartadas };
    }

    // ── Gráfico de vista previa ──────────────────────────────────────
    function dibujar() {
        var lienzo = document.getElementById('chartPreview');
        if (!lienzo || typeof Chart === 'undefined') return;

        var fwd = editores.forward ? editores.forward.leer() : [];
        var desc = editores.descuento ? editores.descuento.leer() : [];

        var datos = {
            datasets: [
                {
                    label: 'Forward outright',
                    data: fwd.map(function (p) { return { x: p.tenor_days, y: p.value }; }),
                    borderColor: App.Tema.accent,
                    backgroundColor: 'rgba(79,45,127,.12)',
                    yAxisID: 'y',
                    tension: .2,
                    pointRadius: 3,
                    fill: false
                },
                {
                    label: 'Descuento (%)',
                    data: desc.map(function (p) { return { x: p.tenor_days, y: p.value }; }),
                    borderColor: App.Tema.info,
                    backgroundColor: 'rgba(0,164,179,.12)',
                    yAxisID: 'y1',
                    tension: .2,
                    pointRadius: 3,
                    fill: false
                }
            ]
        };

        if (grafico) {
            grafico.data = datos;
            grafico.update('none');
            return;
        }

        grafico = new Chart(lienzo, {
            type: 'line',
            data: datos,
            options: App.chartOpts({
                plugins: { legend: { display: true, position: 'bottom' } },
                scales: {
                    x: {
                        type: 'linear',
                        title: { display: true, text: 'Plazo (días)', color: App.Tema.tick, font: { size: 10 } }
                    },
                    y: {
                        position: 'left',
                        title: { display: true, text: 'Outright', color: App.Tema.tick, font: { size: 10 } },
                        ticks: { callback: function (v) { return App.num(v, 2); } }
                    },
                    y1: {
                        position: 'right',
                        grid: { drawOnChartArea: false },
                        title: { display: true, text: 'Tasa %', color: App.Tema.tick, font: { size: 10 } },
                        ticks: { callback: function (v) { return App.num(v, 2) + '%'; } }
                    }
                }
            })
        });
    }

    // ── Importación por archivo (AJAX) ───────────────────────────────
    async function importar(tipo, archivo, reemplazar) {
        var ed = editores[tipo];
        var datos = new FormData();
        datos.append('archivo', archivo);
        datos.append('type', tipo);

        var estado = document.querySelector('[data-import-status="' + tipo + '"]');
        if (estado) estado.textContent = 'Procesando ' + archivo.name + '...';
        ed.mostrarAvisos([]);

        try {
            var resp = await fetch(importUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'X-CSRFToken': App.csrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
                body: datos
            });
            var json = {};
            try { json = await resp.json(); } catch (e) { json = {}; }

            if (!resp.ok || json.error) {
                var detalles = json.detalles || [];
                ed.mostrarAvisos([json.error || 'No se pudo procesar el archivo.'].concat(detalles), 'error');
                if (estado) estado.textContent = '';
                return;
            }

            var puntos = json.points || [];
            if (reemplazar) {
                ed.cargar(puntos);
            } else {
                puntos.forEach(function (p) { ed.agregar(p.tenor_days, p.value); });
                ed.sincronizar();
            }
            if (estado) {
                estado.textContent = puntos.length + ' nodos importados desde ' + archivo.name + '.';
            }
            if (json.avisos && json.avisos.length) ed.mostrarAvisos(json.avisos, 'warning');
        } catch (e) {
            ed.mostrarAvisos(['Error de conexión al importar el archivo.'], 'error');
            if (estado) estado.textContent = '';
        }
    }

    // ── Arranque ─────────────────────────────────────────────────────
    ['forward', 'descuento'].forEach(function (tipo) {
        editores[tipo] = new Editor(tipo);
    });

    function inicial(ed) {
        try {
            var v = JSON.parse(ed.hidden.value || '[]');
            return Array.isArray(v) ? v : [];
        } catch (e) { return []; }
    }

    editores.forward.cargar(inicial(editores.forward));
    editores.descuento.cargar(inicial(editores.descuento));

    raiz.addEventListener('input', function (ev) {
        var tr = ev.target.closest('tr');
        if (!tr) return;
        var tipo = tr.closest('tbody').id.replace('tbody-', '');
        if (editores[tipo]) editores[tipo].sincronizar();
    });

    raiz.addEventListener('click', function (ev) {
        var tipo;

        if (ev.target.closest('[data-quitar]')) {
            var tr = ev.target.closest('tr');
            tipo = tr.closest('tbody').id.replace('tbody-', '');
            tr.remove();
            if (!editores[tipo].cuerpo.children.length) editores[tipo].agregar();
            editores[tipo].sincronizar();
            return;
        }

        var agregar = ev.target.closest('[data-agregar]');
        if (agregar) {
            tipo = agregar.getAttribute('data-agregar');
            editores[tipo].agregar('', '', true);
            editores[tipo].sincronizar();
            return;
        }

        var vaciar = ev.target.closest('[data-vaciar]');
        if (vaciar) {
            tipo = vaciar.getAttribute('data-vaciar');
            if (!confirm('¿Vaciar todos los nodos de la curva ' + tipo + '?')) return;
            editores[tipo].limpiar();
            editores[tipo].agregar();
            editores[tipo].sincronizar();
            return;
        }

        var aplicar = ev.target.closest('[data-pegar-aplicar]');
        if (aplicar) {
            tipo = aplicar.getAttribute('data-pegar-aplicar');
            var caja = document.getElementById('paste-' + tipo);
            var res = parsearPegado(caja.value);
            if (!res.puntos.length) {
                editores[tipo].mostrarAvisos(
                    ['No se reconoció ninguna fila. Usa dos columnas: plazo en días y valor, separadas por tabulación.'],
                    'error'
                );
                return;
            }
            editores[tipo].cargar(res.puntos);
            var avisos = [res.puntos.length + ' nodos pegados.'];
            if (res.descartadas) avisos.push(res.descartadas + ' líneas no se pudieron interpretar y se omitieron.');
            editores[tipo].mostrarAvisos(avisos, 'info');
            caja.value = '';
        }
    });

    raiz.addEventListener('change', function (ev) {
        var input = ev.target.closest('[data-import-file]');
        if (!input || !input.files || !input.files.length) return;
        var tipo = input.getAttribute('data-import-file');
        var reemplazar = document.querySelector('[data-import-replace="' + tipo + '"]');
        importar(tipo, input.files[0], !reemplazar || reemplazar.checked);
        input.value = '';
    });

    // Al enviar, garantiza que los hidden estén al día.
    var formulario = document.getElementById('curvas-form');
    if (formulario) {
        formulario.addEventListener('submit', function (ev) {
            editores.forward.sincronizar();
            editores.descuento.sincronizar();
            var f = editores.forward.leer().length;
            var d = editores.descuento.leer().length;
            if (!f || !d) {
                ev.preventDefault();
                alert('Debes cargar al menos un nodo en la curva forward y uno en la de descuento.');
            }
        });
    }
})();
