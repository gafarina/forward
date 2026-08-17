# Metodología de valorización de forwards FX USD/CLP

Documento técnico del motor `core/` del proyecto **forward_v2**. Describe el
producto, las fórmulas, las convenciones y los supuestos con los que se calcula
el valor razonable de un forward de tipo de cambio contra pesos chilenos.

Todas las cifras que aparecen en este documento fueron reproducidas ejecutando
el motor contra el libro `06052026 CalculadoraForward Cordada_v2.xlsm`
(valorización al 31-05-2026). No hay números ilustrativos.

---

## Índice

1. [El producto y la convención de signos](#1-el-producto-y-la-convención-de-signos)
2. [Fórmula del MtM y su descomposición](#2-fórmula-del-mtm-y-su-descomposición)
3. [Construcción de curvas](#3-construcción-de-curvas)
4. [Interpolación](#4-interpolación)
5. [Extrapolación y el caso Cordada](#5-extrapolación-y-el-caso-cordada)
6. [Convenciones de conteo de días](#6-convenciones-de-conteo-de-días)
7. [Descuento y capitalización](#7-descuento-y-capitalización)
8. [Calendario de días hábiles chileno](#8-calendario-de-días-hábiles-chileno)
9. [Sensibilidades](#9-sensibilidades)
10. [CVA y DVA](#10-cva-y-dva)
11. [Escenarios de sensibilidad](#11-escenarios-de-sensibilidad)
12. [Supuestos y limitaciones](#12-supuestos-y-limitaciones)

---

## 1. El producto y la convención de signos

Un **forward de tipo de cambio** es un acuerdo bilateral para intercambiar dos
monedas en una fecha futura `T` a un precio `K` fijado hoy. En el mercado local
el par relevante es USD/CLP, cotizado como pesos por dólar: la moneda **base**
es el USD (sobre la que se define el nocional `N`) y la moneda de
**cotización** es el CLP.

Existen dos modalidades:

| Modalidad | Liquidación en `T` |
|---|---|
| **Entrega física** | Se entregan `N` USD contra `N·K` CLP |
| **Compensación** (*non-deliverable*) | Se paga la diferencia en CLP contra el tipo de cambio de referencia (Dólar Observado) |

Para efectos de valorización ambas modalidades tienen el mismo valor razonable
mientras no exista riesgo de entrega. El motor no las distingue en el cálculo;
`modality` se guarda sólo como atributo descriptivo.

### Derivación del signo

Sea `S_T` el tipo de cambio spot en la fecha de vencimiento.

**Vendedor** (se comprometió a entregar USD y recibir CLP a `K`): su flujo en
`T` es

```
Flujo_venta(T) = (K − S_T) · N     [CLP]
```

Si el mercado cae por debajo del precio pactado (`S_T < K`), el vendedor
entrega dólares que en el mercado valen menos de lo que le pagan por ellos: la
diferencia `K − S_T` es su ganancia por cada dólar de nocional. **El vendedor
gana cuando el mercado cae.**

**Comprador**: su flujo es el opuesto,

```
Flujo_compra(T) = (S_T − K) · N
```

Definimos entonces

```
ε = +1   si la operación es una Venta de la moneda base
ε = −1   si es una Compra
```

de modo que un único código sirve para ambos lados:

```
Flujo(T) = ε · (K − S_T) · N
```

Implementación:

```python
# core/valuation.py
@property
def sign(self) -> int:
    return 1 if str(self.side).strip().lower().startswith("v") else -1
```

---

## 2. Fórmula del MtM y su descomposición

### 2.1 Valor razonable

Bajo la medida forward asociada al numerario del bono cero cupón en CLP a plazo
`T`, el valor esperado del spot futuro es precisamente el **forward outright de
mercado** `F_t` observado hoy para ese plazo. Descontando el flujo esperado:

```
MtM = ε · (K − F_t) · N · DF(t, T)
```

donde:

| Símbolo | Significado |
|---|---|
| `ε` | +1 venta, −1 compra |
| `K` | precio forward pactado (CLP por USD) |
| `F_t` | forward outright de mercado al plazo residual |
| `N` | nocional en moneda base (USD) |
| `DF(t,T)` | factor de descuento en CLP entre la fecha de valorización y el vencimiento |

```python
# core/valuation.py
mtm = eps * (K - F) * N * df
```

El descuento se hace en **moneda de cotización** (CLP) porque el flujo neto de
liquidación está denominado en CLP. Esto es correcto para la modalidad de
compensación; para entrega física con dos flujos brutos el tratamiento riguroso
requiere descontar cada pata en su moneda, lo que produce el mismo resultado
sólo si las curvas son consistentes con la paridad cubierta que genera `F_t`
(ver §12).

### 2.2 Descomposición: componente spot y puntos forward

El resultado de un forward se descompone en dos efectos económicamente
distintos:

```
Componente spot  = ε · (S₀ − S_t) · N · DF        ("reserva de cobertura")
Puntos forward   = MtM − Componente spot          ("resultado por puntos forward")
```

donde `S₀` es el tipo de cambio **spot vigente el día en que se pactó la
operación** y `S_t` es el spot de la fecha de valorización.

```python
# core/valuation.py
mtm = eps * (K - F) * N * df
spot_component = eps * (S0 - St) * N * df if S0 > 0 else 0.0
fwd_points = mtm - spot_component
```

**Identidad algebraica.** Definiendo los puntos forward pactados
`p₀ = K − S₀` y los puntos forward de mercado `p_t = F_t − S_t`:

```
Puntos forward = MtM − Componente spot
               = ε · [(K − F_t) − (S₀ − S_t)] · N · DF
               = ε · [(K − S₀) − (F_t − S_t)] · N · DF
               = ε · (p₀ − p_t) · N · DF
```

Es decir: **el componente spot mide cuánto se movió el tipo de cambio desde que
se pactó la operación, y los puntos forward miden cuánto se movió el
diferencial de tasas implícito.** Sin `S₀` la segunda pieza es indefinible.

Verificación numérica con el folio 756929 del libro Cordada:

| Magnitud | Valor |
|---|---|
| `S₀` (spot al inicio) | 887,71 |
| `K` (precio pactado) | 886,94 |
| `p₀ = K − S₀` | −0,770000 |
| `S_t` (spot al 31-05-2026) | 892,89 |
| `F_t` (forward a 37 días) | 892,054194 |
| `p_t = F_t − S_t` | −0,835806 |
| `DF` | 0,9965655190 |
| Componente spot = `(S₀−S_t)·N·DF` | −5.162.209,39 |
| Puntos forward = `(p₀−p_t)·N·DF` | 65.580,44 |
| MtM = suma | −5.096.628,95 |

Las tres cifras coinciden **al centavo** con las celdas `S5`, `T5` y `R5` de la
hoja *Forwards Cordada 31-05* del libro operativo.

### 2.3 Lectura contable

La propia planilla operativa rotula las columnas de forma explícita:

| Celda | Encabezado en el libro | Concepto del motor |
|---|---|---|
| `R3` | *Valor Contable Activo o (pasivo)* | `mtm` |
| `S3` | *ORI Reserva de Cobertura* | `spot_component` |
| `T3` | *ORI Puntos Forwards* | `fwd_points` |

Bajo contabilidad de coberturas (NIIF 9), cuando un forward se designa como
instrumento de cobertura de flujos de caja se puede separar el **elemento
spot** del **elemento de puntos forward**: el primero va a Otro Resultado
Integral como reserva de cobertura y se recicla a resultados cuando la partida
cubierta afecta resultados; el segundo puede tratarse como *costo de la
cobertura* y amortizarse en un componente separado de ORI. Esta es exactamente
la razón por la que el sistema necesita `S₀`: no es un dato decorativo, es lo
que permite la clasificación contable.

> **Consecuencia práctica.** Si `S₀` se puebla con el spot de la fecha de
> valorización (`S₀ = S_t`), el componente spot es idénticamente cero y todo el
> MtM se clasifica como puntos forward. La descomposición pierde sentido. Este
> era precisamente el defecto del cargador del repositorio original (ver
> `docs/AUDITORIA.md`, hallazgo M-06).

Cuando falta el dato, el motor no inventa: deja el componente en cero y levanta
una bandera visible.

```python
# core/valuation.py
if S0 <= 0:
    flags.append("Falta el tipo de cambio al inicio: la descomposición spot/puntos no es confiable")
```

---

## 3. Construcción de curvas

### 3.1 Curva de outrights

El motor consume la curva forward como **outrights**: para cada plazo en días
`d`, el precio forward `F(d)` en CLP por USD directamente cotizable. No
consume puntos forward ni tasas.

Nodos de la curva `FWDUSDCLP` del libro Cordada al 31-05-2026 (spot 892,89):

| Plazo (días) | Outright | Puntos = `F − S` | Diferencial implícito (simple, ACT/360) |
|---:|---:|---:|---:|
| 1 | 892,210 | −0,680 | −27,417 % |
| 2 | 892,205 | −0,685 | −13,809 % |
| 8 | 892,190 | −0,700 | −3,528 % |
| 15 | 892,130 | −0,760 | −2,043 % |
| 22 | 892,105 | −0,785 | −1,439 % |
| 31 | 892,060 | −0,830 | −1,079 % |
| 62 | 892,030 | −0,860 | −0,559 % |
| 93 | 891,980 | −0,910 | −0,395 % |
| 125 | 892,010 | −0,880 | −0,284 % |
| 184 | 892,040 | −0,850 | −0,186 % |
| 274 | 892,160 | −0,730 | −0,107 % |
| 365 | 892,360 | −0,530 | −0,059 % |

Los puntos forward son **negativos** en toda la curva: el USD se cotiza a
descuento contra el CLP. Los diferenciales implícitos de los plazos muy cortos
(1 y 2 días) son artefactos de anualizar una diferencia de centésimas sobre un
plazo minúsculo, no información económica; ese es un motivo adicional para no
construir la curva de descuento desde la curva de outrights.

### 3.2 Puntos forward y paridad cubierta de tasas

Los **puntos forward** son la diferencia entre el outright y el spot:

```
p(d) = F(d) − S
```

Bajo paridad cubierta de tasas de interés, con capitalización simple y base
ACT/360 en ambas monedas:

```
F(d) = S · (1 + r_CLP · d/360) / (1 + r_USD · d/360)

p(d) = F(d) − S = S · (d/360) · (r_CLP − r_USD) / (1 + r_USD · d/360)
```

De modo que **el signo de los puntos forward es el signo del diferencial de
tasas**. Puntos negativos ⇒ la tasa en CLP está por debajo de la tasa en USD
para ese plazo.

Verificación con el plazo de 37 días de la valorización Cordada, tomando la
tasa CLP de la curva de descuento (3,404065 % simple):

```
F(37) = 892,054194,  S = 892,89
r_USD implícito = [ (1 + r_CLP·t) · S / F − 1 ] / t = 4,318877 %
```

Un diferencial CLP − USD de −0,911 % anualizado a 37 días, coherente con
los puntos de −0,836 pesos.

### 3.3 Curva de descuento

La curva `CLP423` es una curva de **tasas cero en CLP expresadas en porcentaje
anual**, con capitalización compuesta y base 360 por defecto. Nodos del libro
Cordada:

| Plazo (días) | Tasa cero (%) |
|---:|---:|
| 92 | 3,48231 |
| 183 | 3,61177 |
| 271 | 3,70649 |
| 365 | 3,78017 |
| 731 | 3,98414 |
| 1.096 | 4,24534 |
| 1.461 | 4,42915 |
| 1.825 | 4,58862 |

**El primer nodo está en 92 días.** Esto es central: cualquier contrato con
plazo residual menor a 92 días queda fuera del rango de la curva y su tasa
depende enteramente de la política de extrapolación (§5).

### 3.4 Por qué separar las dos curvas

El motor no deriva la curva de descuento desde la de outrights ni viceversa.
Son insumos independientes porque:

1. Provienen de mercados distintos (outrights de la mesa de FX, tasas cero de
   la curva de swaps cámara) y tienen mallas de plazos distintas.
2. En la práctica no cumplen exactamente la paridad cubierta: hay *basis*
   cross-currency, costos de fondeo y spreads bid-offer.
3. Forzar la consistencia implicaría elegir cuál de las dos es la "verdad", una
   decisión de la mesa, no del sistema.

El costo de esta decisión es que **las mallas no coinciden**: la curva forward
empieza en 1 día y la de descuento en 92. El sistema debe manejar el
desencuentro de forma explícita, no en silencio.

---

## 4. Interpolación

Tres métodos, seleccionables por corrida.

### 4.1 Lineal

```
y(x) = y₀ + (x − x₀)/(x₁ − x₀) · (y₁ − y₀)
```

Es la convención de la planilla operativa y el método por defecto. Aplicada a
outrights preserva la monotonía local y es trivial de auditar celda por celda.

**Cuándo usarla:** para curvas de outrights, siempre que se quiera reproducir
la planilla. Para curvas de tasas cortas donde la curvatura es despreciable.

Verificación (folio 756929, 37 días, nodos 31 → 892,06 y 62 → 892,03):

```
F(37) = 892,06 + (37−31)/(62−31) · (892,03 − 892,06) = 892,054193548387
```

Coincide con la celda `M5` del libro.

### 4.2 Log-lineal sobre factores de descuento

Para curvas de **tasas** el método correcto no es interpolar linealmente el
logaritmo de la tasa, sino interpolar linealmente el logaritmo del **factor de
descuento**:

```
ln DF(x) = ln DF(x₀) + (x − x₀)/(x₁ − x₀) · [ln DF(x₁) − ln DF(x₀)]
```

Esto equivale a interpolar linealmente el producto `r_continua × t`, es decir,
a suponer que la **tasa forward instantánea es constante entre nodos**. Es el
estándar de mercado, y tiene dos propiedades que la interpolación sobre tasas
no tiene:

- **Consistencia libre de arbitraje entre nodos**: los factores interpolados
  son multiplicativamente consistentes.
- **Tolera tasas cero o negativas**, porque el factor de descuento es siempre
  positivo aunque la tasa no lo sea.

```python
# core/curves.py
log_df_curve = Curve(
    f"{self.curve.name}::logDF",
    list(xs),
    [math.log(df) for df in dfs],
    interp="Lineal",
    extrap=self.curve.extrap,
)
log_df = log_df_curve.value(x)
df = math.exp(log_df)
```

Comparación numérica sobre la curva `CLP423` (base 360, compuesta):

| Plazo | Tasa lineal sobre tasas | Tasa log-lineal sobre factores | Diferencia |
|---:|---:|---:|---:|
| 120 d | 3,522144 % | 3,543036 % | +2,09 pb |
| 150 d | 3,564823 % | 3,582962 % | +1,81 pb |
| 220 d | 3,651595 % | 3,660817 % | +0,92 pb |
| 300 d | 3,729221 % | 3,734140 % | +0,49 pb |

La diferencia máxima en el tramo interpolado es de unos 2 puntos base. Sobre el
contrato del folio 756929 (venta de USD 1 millón a 886,94) llevado a un
vencimiento de 120 días, el MtM pasa de −5.055.522,81 con interpolación lineal
sobre tasas a −5.055.182,76 con log-lineal sobre factores: **340,05 pesos de
diferencia**. A 150 días, 367,77 pesos. El efecto es del mismo orden que el de
la política de extrapolación (§5).

Con tasas negativas el método sigue definido:

| Plazo | Tasa interpolada | Factor |
|---:|---:|---:|
| 60 d | −0,040147 % | 1,00006693 |
| 90 d | +0,029902 % | 0,99992526 |
| 200 d | +0,199801 % | 0,99889172 |

(Curva de prueba con nodos 30 d → −0,25 %, 180 d → 0,10 %, 360 d → 0,60 %.)

**Cuándo usarla:** para la curva de descuento cuando se busca consistencia
libre de arbitraje, o cuando la curva tiene tramos con tasas cercanas a cero o
negativas.

### 4.3 Escalonada

```
y(x) = y₀   para todo x ∈ [x₀, x₁)
```

Mantiene constante el valor del nodo anterior hasta el siguiente nodo.

**Cuándo usarla:** para reproducir sistemas heredados que usan tablas de tasas
por tramos, o cuando la curva representa una variable que efectivamente es
escalonada (por ejemplo una tasa de política monetaria proyectada por reunión).
No es apropiada para outrights.

### 4.4 Manejo de nodos degenerados

El motor ordena los nodos y colapsa plazos duplicados quedándose con el último
valor cargado, antes de cualquier evaluación:

```python
# core/curves.py
merged: dict[float, float] = {}
for x, y in zip(self.xs, self.ys):
    merged[float(x)] = float(y)
pairs = sorted(merged.items())
```

Sin esto, una curva cargada con los plazos desordenados devuelve valores
arbitrarios sin ningún aviso.

---

## 5. Extrapolación y el caso Cordada

Esta es, en términos de impacto económico medible, la diferencia metodológica
más importante entre el motor original y el actual.

### 5.1 Las tres políticas

| Política | Fuera del rango |
|---|---|
| **Plana** | Devuelve el valor del nodo extremo: `y(x) = y₀` a la izquierda, `y(x) = y_n` a la derecha |
| **Lineal** | Prolonga la pendiente del primer (o último) tramo: `y(x) = y_ancla + m·(x − x_ancla)` |
| **Puntos** | Pensada para curvas de outrights: mantener constante la pendiente de puntos forward |

```python
# core/curves.py
if self.extrap == "Plana":
    return ys[0] if left else ys[-1]
...
slope = (y1 - y0) / (x1 - x0) if x1 != x0 else 0.0
if self.extrap == "Lineal":
    return anchor_y + slope * (x - anchor_x)
```

> **Nota de implementación.** En la versión actual del código la rama `"Puntos"`
> retorna la misma expresión que `"Lineal"` (`anchor_y + slope·(x − anchor_x)`),
> de modo que ambas políticas producen resultados idénticos. La distinción
> conceptual está documentada y la opción está expuesta en el formulario, pero
> la diferenciación numérica todavía no está implementada. Ver
> `docs/AUDITORIA.md`, hallazgo **P-01**.

### 5.2 El problema concreto

La curva de descuento `CLP423` tiene su primer nodo en **92 días**. La cartera
de ejemplo del libro Cordada tiene tres contratos, con plazos residuales de
**12, 37 y 43 días**. Los tres están fuera del rango por la izquierda.

- El motor original (`services/interpolation.py` de la v1) extrapola **plano**:
  los tres contratos se descuentan a 3,48231 %, la tasa del nodo de 92 días.
- La planilla operativa extrapola **linealmente**, prolongando la pendiente del
  primer tramo:

```
m = (3,61177 − 3,48231) / (183 − 92) = 0,0014226484 % por día

r(37) = 3,48231 − 0,0014226484 · (92 − 37) = 3,404065 %
r(43) = 3,48231 − 0,0014226484 · (92 − 43) = 3,412601 %
r(12) = 3,48231 − 0,0014226484 · (92 − 12) = 3,368499 %
```

Los tres valores coinciden dígito por dígito con las celdas `P5`, `P6` y `P7`
del libro.

### 5.3 Reconciliación numérica

Valorización al 31-05-2026, spot 892,89, interpolación lineal, ACT/360,
capitalización compuesta, sin ajuste de días hábiles.

| Folio | Vcto | Días | Nocional (USD) | `S₀` | `K` | `F_t` |
|---|---|---:|---:|---:|---:|---:|
| 756929 | 2026-07-07 | 37 | 1.000.000 | 887,71 | 886,94 | 892,054194 |
| 118039 | 2026-07-13 | 43 | 2.000.000 | 894,25 | 893,35 | 892,048387 |
| 116845 | 2026-06-12 | 12 | 2.000.000 | 890,33 | 889,98 | 892,155714 |

**Tasa de descuento y factor:**

| Folio | Tasa v1 (plana) | Tasa planilla / v2 (lineal) | DF v1 | DF planilla / v2 |
|---|---:|---:|---:|---:|
| 756929 | 3,482310 % | 3,404065 % | 0,9964880473 | 0,9965655190 |
| 118039 | 3,482310 % | 3,412601 % | 0,9959197048 | 0,9959998685 |
| 116845 | 3,482310 % | 3,368499 % | 0,9988596342 | 0,9988962736 |

**MtM resultante (CLP):**

| Folio | MtM motor v1 (plana) | MtM planilla | MtM motor v2 (lineal) | Diferencia v1 − planilla |
|---|---:|---:|---:|---:|
| 756929 | −5.096.232,74 | −5.096.628,95 | −5.096.628,95 | **+396,21** |
| 118039 | 2.592.603,88 | 2.592.812,56 | 2.592.812,56 | **−208,68** |
| 116845 | −4.346.466,35 | −4.346.625,78 | −4.346.625,78 | **+159,43** |
| **Total** | **−6.850.095,21** | **−6.850.442,17** | **−6.850.442,17** | **+346,96** |

Y la descomposición completa que produce el motor v2 con extrapolación lineal:

| Concepto | Motor v2 | Libro Cordada (celdas R9/S9/T9) |
|---|---:|---:|
| MtM total | −6.850.442,17 | −6.850.442,171624668 |
| Componente spot | −7.567.438,67 | −7.567.438,666818179 |
| Puntos forward | 716.996,50 | 716.996,4951935108 |

**Con extrapolación lineal el motor reproduce la planilla al centavo en los
tres contratos y en los tres agregados.**

### 5.4 Por qué importa

Una diferencia de 396 pesos sobre un contrato de USD 1 millón parece
irrelevante. No lo es, por tres razones:

1. **No es un error de redondeo, es un error de método.** La diferencia crece
   con el nocional y con la distancia al primer nodo. Una cartera de USD 200
   millones concentrada en el tramo corto acumula la misma proporción de error.
2. **Impide conciliar.** Si el sistema y la planilla no coinciden al centavo, no
   hay forma de distinguir un error de método de un error de datos. Se pierde la
   herramienta de control.
3. **Es sistemáticamente sesgada.** Con la curva al alza, la extrapolación plana
   sobreestima la tasa en el tramo corto para todos los contratos, subestimando
   sistemáticamente el valor absoluto de todos los MtM cortos.

Además, el motor original **no avisaba**. Su verificación de extrapolación en la
curva de descuento sólo miraba el extremo largo:

```python
# v1: valorizador/services/valuation.py
if days_to_mat > disc_xs[-1]:
    flags.append('Descuento extrapolado a largo plazo')
```

Los tres contratos del ejemplo salieron con la lista de banderas **vacía**. El
motor actual marca ambos extremos y en ambas curvas:

```python
# core/valuation.py
if disc_curve.is_outside(days_to_mat):
    flags.append(
        f"Descuento extrapolado: plazo {days_to_mat}d "
        f"fuera de [{int(disc_curve.min_tenor)}, {int(disc_curve.max_tenor)}]"
    )
```

### 5.5 Extrapolación en el extremo largo de la curva de outrights

Mantener el outright constante más allá del último nodo tiene una implicación
económica que rara vez es la deseada. Si `F(d) = F(d_max)` para todo
`d > d_max`, entonces los puntos forward dejan de crecer, y por la relación de
paridad cubierta:

```
p(d) = S · (d/360) · (r_CLP − r_USD) / (1 + r_USD · d/360)
```

un `p(d)` constante con `d` creciente implica `(r_CLP − r_USD) → 0`. Es decir:
la extrapolación plana de outrights afirma implícitamente que **el diferencial
de tasas colapsa a cero en el largo plazo**, lo que contradice la propia forma
de la curva de descuento (que en el ejemplo sube de 3,48 % a 4,59 % entre 92 y
1.825 días).

Comportamiento de las políticas sobre la curva `CLP423` truncada a tres nodos
(92, 183, 271):

| Plazo | Plana | Lineal | Puntos |
|---:|---:|---:|---:|
| 12 d | 3,482310 | 3,368499 | 3,368499 |
| 37 d | 3,482310 | 3,404065 | 3,404065 |
| 400 d | 3,706490 | 3,845341 | 3,845341 |
| 1.000 d | 3,706490 | 4,491159 | 4,491159 |

A 1.000 días la diferencia entre políticas es de 78 puntos base. En el extremo
largo la extrapolación lineal tampoco es inocua: prolonga indefinidamente una
pendiente que en las curvas reales se aplana. **Ninguna política de
extrapolación es "correcta"; lo importante es que sea explícita, esté
documentada y quede marcada en la línea de resultado.**

---

## 6. Convenciones de conteo de días

La convención determina la **fracción de año** `t` que entra en el factor de
descuento. No determina el plazo con el que se interpolan las curvas: para eso
siempre se usan **días corridos**, porque las curvas están cotizadas en días
corridos.

```python
# core/valuation.py
days_to_mat = (mat_date - val_date).days                       # para interpolar curvas
year_fraction = day_count_fraction(val_date, mat_date, config.day_count)  # para descontar
```

### 6.1 Convenciones soportadas

| Convención | Numerador | Denominador |
|---|---|---|
| **ACT/360** | días corridos | 360 |
| **ACT/365** | días corridos | 365 |
| **30/360** (US, *Bond Basis*, NASD) | días bajo la regla 30/360 US | 360 |
| **30E/360** (Eurobond, ISDA) | días bajo la regla 30E/360 | 360 |
| **ACT/ACT** (ISDA) | días corridos por año calendario | 365 o 366 según el año |

La convención del mercado local para instrumentos de tasa en CLP es **ACT/360**,
y es el valor por defecto del motor.

### 6.2 Regla exacta de 30/360 US (NASD)

Sean `D1 = (Y1, M1, DD1)` la fecha inicial y `D2 = (Y2, M2, DD2)` la final. Se
aplican **en este orden**:

1. Si `D1` es el último día de febrero y `D2` es el último día de febrero,
   entonces `DD2 = 30`.
2. Si `D1` es el último día de febrero, entonces `DD1 = 30`.
3. Si `DD2 = 31` y `DD1 ≥ 30`, entonces `DD2 = 30`.
4. Si `DD1 = 31`, entonces `DD1 = 30`.

```
Días = 360·(Y2 − Y1) + 30·(M2 − M1) + (DD2 − DD1)
```

```python
# core/daycount.py
def _days_30_360_us(d1: date, d2: date) -> int:
    dd1, dd2 = d1.day, d2.day
    if _is_last_day_of_february(d1) and _is_last_day_of_february(d2):
        dd2 = 30
    if _is_last_day_of_february(d1):
        dd1 = 30
    if dd2 == 31 and dd1 >= 30:
        dd2 = 30
    if dd1 == 31:
        dd1 = 30
    return 360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (dd2 - dd1)
```

### 6.3 Regla exacta de 30E/360 (Eurobond)

Más simple: **no hay regla de febrero** y ambos extremos se truncan.

1. Si `DD1 = 31`, entonces `DD1 = 30`.
2. Si `DD2 = 31`, entonces `DD2 = 30`.

```
Días = 360·(Y2 − Y1) + 30·(M2 − M1) + (DD2 − DD1)
```

### 6.4 Ejemplos numéricos donde difieren

| Desde | Hasta | ACT | 30/360 US | 30E/360 | Comentario |
|---|---|---:|---:|---:|---|
| 2026-02-28 | 2026-03-31 | 31 | **30** | **32** | Fin de febrero: US lleva `DD1` a 30 y luego `DD2` a 30; 30E deja `DD1=28` y lleva `DD2` a 30 |
| 2026-08-31 | 2026-12-31 | 122 | 120 | 120 | Ambas coinciden: `DD1=31 → 30`, luego `DD2=31 → 30` |
| 2025-12-31 | 2026-12-31 | 365 | 360 | 360 | Un año exacto vale 1,0 en base 30/360 y 1,0139 en ACT/360 |
| 2024-02-29 | 2024-08-31 | 184 | **180** | **181** | Año bisiesto: US aplica la regla de febrero, 30E no |
| 2026-05-31 | 2026-07-07 | 37 | 37 | 37 | Coinciden |

Fracciones de año correspondientes:

| Desde | Hasta | ACT/360 | ACT/365 | 30/360 | 30E/360 | ACT/ACT |
|---|---|---:|---:|---:|---:|---:|
| 2026-02-28 | 2026-03-31 | 0,086111 | 0,084932 | 0,083333 | 0,088889 | 0,084932 |
| 2024-02-29 | 2024-08-31 | 0,511111 | 0,504110 | 0,500000 | 0,502778 | 0,502732 |
| 2025-12-31 | 2026-12-31 | 1,013889 | 1,000000 | 1,000000 | 1,000000 | 1,000000 |

### 6.5 Impacto en el MtM

Contrato de venta de USD 1.000.000 a `K = 886,94` con vencimiento el
2026-08-31 (92 días corridos desde el 31-05-2026), curvas Cordada:

| Convención | Días corridos | Fracción de año | Factor de descuento | MtM (CLP) |
|---|---:|---:|---:|---:|
| ACT/360 | 92 | 0,25555556 | 0,9912903576 | −4.997.702,26 |
| ACT/365 | 92 | 0,25205479 | 0,9914091538 | −4.998.301,18 |
| 30/360 | 92 | 0,25000000 | 0,9914788887 | −4.998.652,76 |
| 30E/360 | 92 | 0,25000000 | 0,9914788887 | −4.998.652,76 |
| ACT/ACT | 92 | 0,25205479 | 0,9914091538 | −4.998.301,18 |

Rango total: 950 pesos sobre un MtM de −5,0 millones (0,019 %). Es pequeño en
plazos cortos y crece con el plazo. A 5 años (2026-05-31 → 2031-05-31, tasa
4,42915 %):

| Convención | Fracción de año | Factor de descuento |
|---|---:|---:|
| ACT/360 | 5,072222 | 0,80266058 |
| 30/360 | 5,000000 | 0,80517686 |

La fracción de año difiere **1,44 %** y el factor de descuento **0,313 %**, es
decir 2.516 pesos por cada millón de valor presente.

Obsérvese que **los días corridos son 92 en todos los casos**: la convención
sólo afecta el denominador del descuento, nunca el punto de la curva que se
interpola.

### 6.6 ACT/ACT ISDA

Es la única convención cuyo denominador no es constante. Reparte los días entre
años bisiestos y no bisiestos:

```
t = Σ_años  (días del intervalo en ese año) / (366 si bisiesto, si no 365)
```

```python
# core/daycount.py
for year in range(d1.year, d2.year + 1):
    y_start = max(d1, date(year, 1, 1))
    y_end = min(d2, date(year + 1, 1, 1))
    if y_end <= y_start:
        continue
    is_leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
    total += (y_end - y_start).days / (366.0 if is_leap else 365.0)
```

---

## 7. Descuento y capitalización

La curva entrega una **tasa cero anual en porcentaje**. El factor de descuento
depende de la convención de capitalización:

| Convención | Factor |
|---|---|
| **Compuesta** | `DF = (1 + r)^(−t)` |
| **Simple** | `DF = 1 / (1 + r·t)` |
| **Continua** | `DF = exp(−r·t)` |

con `r` expresada como fracción (`r = rate_pct / 100`) y `t` la fracción de año
según §6.

```python
# core/curves.py
if compounding == "Simple":
    return 1.0 / (1.0 + r * t)
if compounding == "Continua":
    return math.exp(-r * t)
if compounding == "Compuesta":
    return (1.0 + r) ** (-t)
```

**Convención del mercado local.** Las curvas cero en CLP construidas a partir de
swaps de cámara promedio se publican en **capitalización compuesta, base 360**,
y así se usan tanto en la planilla operativa como en el motor por defecto. La
capitalización simple aparece en instrumentos de mercado monetario a plazos
menores a un año (depósitos a plazo, pactos); la continua es una comodidad
matemática que en el mercado local no se usa para cotizar.

Comparación con `r = 3,78017 %` y `t = 365/360 = 1,013889`:

| Convención | Factor de descuento | Valor presente de CLP 1.000.000 |
|---|---:|---:|
| Compuesta | 0,9630787744 | 963.078,77 |
| Simple | 0,9630879927 | 963.087,99 |
| Continua | 0,9623984512 | 962.398,45 |

A un año la diferencia entre compuesta y simple es de 9 pesos por millón; entre
compuesta y continua, de 680 pesos por millón. Las diferencias crecen
rápidamente con el plazo y con el nivel de tasas.

**Robustez.** El motor rechaza explícitamente factores no definidos en lugar de
devolver `nan`:

```python
# core/curves.py
if denom <= 0:
    raise ValueError("Factor de descuento simple no definido (1 + r·t ≤ 0).")
...
if base <= 0:
    raise ValueError("Factor de descuento compuesto no definido (1 + r ≤ 0).")
```

---

## 8. Calendario de días hábiles chileno

### 8.1 Para qué se usa

El calendario cumple dos funciones:

1. **Ajustar el vencimiento** cuando la fecha pactada cae en día inhábil, según
   la convención de la operación.
2. Servir de base para el cómputo de fechas de liquidación spot (T+1 en el
   mercado local para USD/CLP).

El ajuste del vencimiento **cambia el plazo residual**, y por lo tanto cambia
tanto el punto interpolado de la curva como el factor de descuento. Ignorar
feriados sesga sistemáticamente el plazo a la baja.

### 8.2 Convenciones de ajuste

| Convención | Regla |
|---|---|
| **Exacto** | No se ajusta. Se usa la fecha tal como está pactada |
| **Following** | Primer día hábil siguiente |
| **ModifiedFollowing** | Primer día hábil siguiente, salvo que cambie de mes; en ese caso, el día hábil anterior |
| **Preceding** | Primer día hábil anterior |
| **ModifiedPreceding** | Simétrica de la anterior |

Por defecto el motor usa **Exacto**, para reproducir la planilla operativa, que
tampoco ajusta.

### 8.3 Feriados legales chilenos

Base legal implementada:

| Feriado | Fecha | Norma / regla |
|---|---|---|
| Año Nuevo | 1 de enero | Fijo |
| Viernes Santo y Sábado Santo | Móviles | Derivados de Pascua (algoritmo gregoriano anónimo) |
| Día del Trabajo | 1 de mayo | Fijo |
| Glorias Navales | 21 de mayo | Fijo |
| Día Nacional de los Pueblos Indígenas | Solsticio de junio | Ley 21.357; fecha tabulada 2021-2030 |
| San Pedro y San Pablo | 29 de junio | **Ley 20.215**: traslado a lunes |
| Virgen del Carmen | 16 de julio | Fijo |
| Asunción de la Virgen | 15 de agosto | Fijo |
| Independencia Nacional | 18 de septiembre | Fijo |
| Glorias del Ejército | 19 de septiembre | Fijo |
| Feriado adicional de Fiestas Patrias | 17 o 20 de septiembre | **Ley 20.215**: si el 18 cae martes, el 17 es feriado; si cae miércoles, el 20 |
| Encuentro de Dos Mundos | 12 de octubre | **Ley 20.215**: traslado a lunes |
| Iglesias Evangélicas y Protestantes | 31 de octubre | **Ley 20.299**: si cae martes se adelanta al viernes anterior; si cae miércoles se posterga al viernes siguiente |
| Día de Todos los Santos | 1 de noviembre | Fijo |
| Inmaculada Concepción | 8 de diciembre | Fijo |
| Navidad | 25 de diciembre | Fijo |
| **Feriado bancario** | 31 de diciembre | No es día hábil bancario para liquidación de operaciones de cambio |

**Regla de traslado a lunes (Ley 20.215):**

```python
# core/calendars.py
def _traslado_lunes(d: date) -> date:
    wd = d.weekday()               # 0 = lunes
    if wd in (1, 2, 3):            # martes / miércoles / jueves
        return d - timedelta(days=wd)
    if wd == 4:                    # viernes
        return d + timedelta(days=3)
    return d
```

Es decir: si cae martes, miércoles o jueves se adelanta al **lunes de la misma
semana**; si cae viernes se posterga al **lunes de la semana siguiente**; si cae
sábado, domingo o lunes se mantiene.

**Regla del Día de las Iglesias Evangélicas (Ley 20.299):**

```python
# core/calendars.py
d = date(year, 10, 31)
wd = d.weekday()
if wd == 1:                    # martes -> viernes anterior (27 de octubre)
    return d - timedelta(days=4)
if wd == 2:                    # miércoles -> viernes siguiente (2 de noviembre)
    return d + timedelta(days=2)
return d
```

La Ley 19.973 es la que estableció originalmente el 31 de diciembre como feriado
(posteriormente derogado como feriado general y mantenido como feriado
bancario) y declaró irrenunciable el descanso en ciertos feriados; se cita como
antecedente de la construcción del calendario bancario.

**Feriados chilenos generados para 2026** (Pascua: 5 de abril de 2026):

| Fecha | Día | Feriado |
|---|---|---|
| 2026-01-01 | jue | Año Nuevo |
| 2026-04-03 | vie | Viernes Santo |
| 2026-04-04 | sáb | Sábado Santo |
| 2026-05-01 | vie | Día del Trabajo |
| 2026-05-21 | jue | Glorias Navales |
| 2026-06-21 | dom | Pueblos Indígenas |
| 2026-06-29 | lun | San Pedro y San Pablo (cae lunes, no se traslada) |
| 2026-07-16 | jue | Virgen del Carmen |
| 2026-08-15 | sáb | Asunción |
| 2026-09-18 | vie | Independencia |
| 2026-09-19 | sáb | Glorias del Ejército |
| 2026-10-12 | lun | Encuentro de Dos Mundos |
| 2026-10-31 | sáb | Iglesias Evangélicas (cae sábado, no se traslada) |
| 2026-11-01 | dom | Todos los Santos |
| 2026-12-08 | mar | Inmaculada Concepción |
| 2026-12-25 | vie | Navidad |
| 2026-12-31 | jue | Feriado bancario |

### 8.4 Calendario conjunto CL+US

Para un forward USD/CLP con entrega física, la liquidación requiere que ambos
sistemas de pago estén operativos. El calendario conjunto declara hábil un día
sólo si lo es en Chile **y** en Estados Unidos:

```python
# core/calendars.py
class JointCalendar(Calendar):
    """Unión de calendarios: un día es hábil sólo si lo es en todos."""
    def holidays(self, year: int) -> frozenset[date]:
        out: frozenset[date] = frozenset()
        for c in self._calendars:
            out = out | c.holidays(year)
        return out
```

Para 2026: 17 feriados chilenos + feriados federales de EE.UU. (con regla de
observancia sábado → viernes, domingo → lunes) dan **25 fechas inhábiles
distintas** en el calendario conjunto.

### 8.5 Efecto del ajuste

Con `Following` sobre el calendario chileno:

| Fecha pactada | ¿Hábil? | Following | ModifiedFollowing |
|---|---|---|---|
| 2026-09-18 (vie) | No | 2026-09-21 | 2026-09-21 |
| 2026-09-19 (sáb) | No | 2026-09-21 | 2026-09-21 |
| 2026-06-29 (lun) | No | 2026-06-30 | 2026-06-30 |
| 2026-10-12 (lun) | No | 2026-10-13 | 2026-10-13 |
| 2026-10-31 (sáb) | No | 2026-11-02 | **2026-10-30** |
| 2026-12-31 (jue) | No | 2027-01-04 | **2026-12-30** |

Los dos últimos casos muestran la diferencia entre `Following` y
`ModifiedFollowing`: cuando el salto cruzaría de mes, la convención modificada
retrocede.

---

## 9. Sensibilidades

Todas las sensibilidades se calculan por **bump y revaluación** usando el mismo
código de valorización, de modo que son internamente consistentes con el MtM
reportado. La única excepción es gamma, que es exactamente cero por argumento
analítico.

### 9.1 Delta

**Definición:** variación del MtM ante un desplazamiento de +1 peso en el tipo
de cambio spot, manteniendo constantes los puntos forward.

La hipótesis clave es que **la curva de outrights se desplaza 1:1 con el spot**.
Es decir, un movimiento del spot no altera el diferencial de tasas y por lo
tanto se traslada íntegramente a todos los outrights:

```
S → S + 1   ⟹   F(d) → F(d) + 1   para todo d
```

```python
# core/valuation.py
f_up = fwd_curve.shifted(additive=1.0).value(days_to_mat)
mtm_spot_up = eps * (K - f_up) * N * df
delta = mtm_spot_up - mtm
```

Bajo ese supuesto el resultado analítico es

```
Δ = −ε · N · DF
```

que es exactamente lo que devuelve el bump. Interpretación: **el delta es el
nocional descontado, con signo opuesto al lado**. Un vendedor de USD tiene
delta negativo: pierde cuando el peso se deprecia.

El motor también reporta `delta_pct`, la variación del MtM ante un movimiento
del 1 % del spot, que es la magnitud que un comité de riesgo lee más
naturalmente.

Verificación numérica sobre la cartera Cordada:

| Folio | Lado | Nocional | DF | `−ε·N·DF` | Delta del motor | Delta 1 % |
|---|---|---:|---:|---:|---:|---:|
| 756929 | Venta | 1.000.000 | 0,9965655190 | −996.565,52 | −996.565,52 | −8.898.233,86 |
| 118039 | Venta | 2.000.000 | 0,9959998685 | −1.991.999,74 | −1.991.999,74 | — |
| 116845 | Venta | 2.000.000 | 0,9988962736 | −1.997.792,55 | −1.997.792,55 | −17.838.089,88 |
| **Total** | | 5.000.000 | | | **−4.986.357,81** | |

Contraste con la revalorización completa (bump del spot arrastrando la curva):

```
MtM(S − 1) = −1.864.084,37
MtM(S)     = −6.850.442,17
MtM(S + 1) = −11.836.799,98

Delta por diferencias centradas = [MtM(S+1) − MtM(S−1)] / 2 = −4.986.357,81
```

Coincide exactamente con el delta reportado.

### 9.2 Gamma: por qué es exactamente cero

El MtM es una función **afín** del forward de mercado:

```
MtM(F) = ε · (K − F) · N · DF = ε·K·N·DF − ε·N·DF · F
```

La segunda derivada respecto de `F` (y, bajo el supuesto de traslado 1:1,
respecto de `S`) es idénticamente nula:

```
∂²MtM/∂S² = 0
```

Un forward no tiene opcionalidad: su payoff es lineal. Por eso el motor reporta
`gamma = 0` de forma explícita en lugar de calcularlo numéricamente:

```python
# core/valuation.py
"gamma": 0.0,  # el payoff es lineal en el forward: gamma exacta = 0
```

Verificación empírica sobre la cartera:

```
MtM(S+1) − 2·MtM(S) + MtM(S−1) = −0,01 CLP
```

sobre un MtM de −6,85 millones: ruido puro de redondeo a dos decimales.

**Implicación práctica:** el delta de un libro de forwards no cambia con el
nivel del spot. Las coberturas delta no requieren rebalanceo por movimiento del
mercado, sólo por el paso del tiempo (theta) y por vencimientos. Ese es
exactamente el atractivo del producto como instrumento de cobertura.

### 9.3 DV01 (rho)

**Definición:** variación del MtM ante un desplazamiento paralelo de +1 punto
base (0,01 %) de la curva de descuento.

```python
# core/valuation.py
disc_up = disc_curve.shifted_bp(1.0)
df_up = disc_up.factor(days_to_mat, year_fraction)
dv01 = eps * (K - F) * N * df_up - mtm
```

Aproximación analítica, con capitalización compuesta:

```
DV01 ≈ −MtM · t / (1 + r) · 0,0001
```

Es decir, **DV01 tiene signo opuesto al MtM**: si el MtM es un pasivo (negativo),
una tasa más alta lo descuenta más y lo acerca a cero, mejorando la posición.

| Folio | MtM | Días | DV01 |
|---|---:|---:|---:|
| 756929 | −5.096.628,95 | 37 | **+50,65** |
| 118039 | +2.592.812,56 | 43 | **−29,95** |
| 116845 | −4.346.625,78 | 12 | **+14,02** |
| **Total** | −6.850.442,17 | | **+34,72** |

El DV01 de un forward FX es de segundo orden: el instrumento no tiene flujos
intermedios y su exposición a tasas viene sólo del descuento del MtM. Un DV01
total de 35 pesos por punto base sobre un MtM de 6,9 millones es despreciable
frente al delta de 5 millones por peso de spot. Esa jerarquía es una propiedad
del producto y conviene tenerla presente al leer el mapa de calor.

El campo `rho` se conserva como alias retrocompatible con la nomenclatura del
sistema anterior, que llamaba "rho" a esta misma cantidad.

### 9.4 Theta

**Definición:** variación del MtM por el paso de un día calendario, con las
curvas congeladas.

```python
# core/valuation.py
def _theta_one_day(contract, market, config, fwd_curve, disc_curve, mtm_base) -> float:
    next_day = market.valuation_date + timedelta(days=1)
    d = (mat_date - next_day).days
    yf = day_count_fraction(next_day, mat_date, config.day_count)
    F = fwd_curve.value(d)
    df = disc_curve.factor(d, yf)
    mtm_next = eps * (float(contract.fwd_price) - F) * float(contract.notional) * df
    return mtm_next - mtm_base
```

Theta captura dos efectos simultáneos:

1. **Rodadura sobre la curva de forwards** (*roll-down*): al acortarse el plazo
   residual, el contrato se revalúa contra un punto distinto de la curva de
   outrights. Este es el efecto dominante.
2. **Desarme del descuento**: el factor de descuento se acerca a 1, lo que
   amplifica el valor absoluto del MtM.

| Folio | Días | MtM | Theta (1 día) | Theta / |MtM| |
|---|---:|---:|---:|---:|
| 756929 | 37 | −5.096.628,95 | −1.445,45 | 0,028 % |
| 118039 | 43 | +2.592.812,56 | −1.682,07 | 0,065 % |
| 116845 | 12 | −4.346.625,78 | **−17.527,38** | 0,403 % |
| **Total** | | −6.850.442,17 | **−20.654,90** | |

El folio 116845 tiene un theta doce veces mayor que los otros dos pese a un MtM
similar. La razón es la **pendiente local de la curva de outrights**: a 12 días
el contrato rueda sobre el tramo 8-15 días, donde la curva cae 0,06 pesos en 7
días (−0,0086 pesos por día), mientras que a 37 días rueda sobre el tramo 31-62,
donde cae 0,03 pesos en 31 días (−0,00097 por día), casi nueve veces más plano.
Theta no es proporcional al plazo: depende de dónde está el contrato sobre la
curva.

---

## 10. CVA y DVA

### 10.1 Qué son

- **CVA** (*Credit Valuation Adjustment*): valor esperado de la pérdida por
  incumplimiento de la **contraparte**, condicional a que el contrato esté a
  favor nuestro cuando esa contraparte incumpla. Reduce el valor del activo.
- **DVA** (*Debit Valuation Adjustment*): el simétrico, por nuestro propio
  incumplimiento cuando el contrato está en contra nuestra. Aumenta (mejora) el
  valor reportado.

```
MtM ajustado = MtM − CVA + DVA
```

### 10.2 Modelo de intensidad de default

La probabilidad de incumplimiento se modela en forma reducida. Dado un spread de
crédito `s` (en puntos base) y una tasa de recuperación `R`:

```
LGD = 1 − R                      severidad
h   = s / (1 − R)                intensidad de default (hazard rate) constante
S(t) = exp(−h · t)               probabilidad de supervivencia hasta t
```

```python
# core/credit.py
@property
def hazard(self) -> float:
    lgd = max(self.lgd, 1e-6)
    return (self.spread_bp / 10_000.0) / lgd

def survival(self, t_years: float) -> float:
    return math.exp(-self.hazard * max(t_years, 0.0))
```

La relación `h = s/(1−R)` es la aproximación de primer orden del *credit
triangle*: un spread de crédito compensa la pérdida esperada por unidad de
tiempo, que es la intensidad de default multiplicada por la severidad.

El CVA es entonces la suma sobre una malla temporal de la exposición esperada
positiva ponderada por la probabilidad marginal de default en cada intervalo:

```
CVA = (1 − R) · Σᵢ EPE(tᵢ) · [S(tᵢ₋₁) − S(tᵢ)]
DVA = (1 − R_propio) · Σᵢ ENE(tᵢ) · [S_propio(tᵢ₋₁) − S_propio(tᵢ)]
```

```python
# core/credit.py
pd_marginal = max(prev_s - surv, 0.0)
cva_step = credit.lgd * epe_set * pd_marginal
dva_step = credit.own_lgd * ene_set * pd_own_marginal
```

La malla es mensual por defecto (`steps_per_year = 12`) hasta el vencimiento más
largo del conjunto.

### 10.3 Exposición esperada bajo Bachelier

La pieza no trivial es la **exposición esperada positiva** `EPE(t)`: cuánto vale
en promedio el contrato en `t`, condicional a que valga algo positivo.

Para un forward FX el valor en `t` es lineal en el precio forward:

```
V(t) = ε · (K − F_t) · N · DF(t)
```

Se modela `F_t` como un proceso **normal (Bachelier)** alrededor del forward
actual:

```
F_t ~ N(F₀, σ_F² · t)
```

La elección de un modelo normal en lugar de lognormal es deliberada: el
producto es lineal, el horizonte es corto, y el modelo normal admite solución
cerrada sin necesidad de simulación. Definiendo

```
m = ε · (K − F₀) · N · DF(t)        valor esperado de la exposición
v = σ_F · √t · N · DF(t)            desviación estándar de la exposición
z = m / v
```

se obtienen las fórmulas cerradas:

```
EPE(t) = E[max(V(t), 0)]  =  m · Φ(z)  + v · φ(z)
ENE(t) = E[max(−V(t), 0)] = −m · Φ(−z) + v · φ(−z)
```

donde `Φ` es la normal estándar acumulada y `φ` su densidad.

```python
# core/credit.py
m = sign * (strike - forward) * notional * discount
v = vol_abs * math.sqrt(max(t_years, 0.0)) * notional * discount
z = m / v
epe = m * _Phi(z) + v * _phi(z)
ene = -m * _Phi(-z) + v * _phi(-z)
```

**La propiedad crucial:** cuando el contrato está *at-the-money* (`m = 0`, es
decir `K = F₀`), la fórmula da

```
EPE = v · φ(0) = v / √(2π) ≈ 0,3989 · σ_F · √t · N · DF  >  0
```

La exposición esperada de un forward at-the-money **no es cero**. Es
proporcional a la volatilidad y a la raíz del plazo. Este es el punto exacto en
el que un modelo basado en el MtM de hoy falla.

### 10.4 Neteo

Bajo un contrato marco ISDA con cláusula de neteo, en caso de incumplimiento se
liquida la **posición neta** frente a la contraparte, no operación por
operación. Por lo tanto la exposición relevante es

```
EPE_conjunto(t) = E[ max( Σⱼ Vⱼ(t), 0 ) ]   ≤   Σⱼ E[ max( Vⱼ(t), 0 ) ]
```

por la desigualdad de Jensen aplicada a la función convexa `max(·, 0)`. Ignorar
el neteo **sobrestima** siempre el CVA.

El motor agrega media y varianza del valor del conjunto antes de aplicar las
fórmulas cerradas:

```python
# core/credit.py
netted_value += s.sign * (s.strike - fwd) * s.notional * df
netted_var += (vol_abs * math.sqrt(t_eff) * s.notional * df) ** 2
...
if netting:
    v = math.sqrt(netted_var)
    z = netted_value / v
    epe_set = netted_value * _Phi(z) + v * _phi(z)
    ene_set = -netted_value * _Phi(-z) + v * _phi(-z)
```

> **Supuesto declarado.** La agregación de varianzas asume correlación nula
> entre los factores de riesgo de las distintas operaciones del conjunto. Para
> operaciones sobre el mismo par de monedas la correlación real es cercana a 1,
> de modo que el motor **subestima la varianza del conjunto neteado**. Es una
> limitación conocida (ver §12).

El CVA del conjunto se asigna después a cada operación en proporción a su
contribución a la exposición esperada bruta:

```python
# core/credit.py
if epe_sum > 0:
    for k, v_epe in per_trade_epe.items():
        contrib_epe[k] += cva_step * (v_epe / epe_sum)
```

### 10.5 Comparación con el enfoque anterior

El motor original calculaba:

```python
# v1: valorizador/services/valuation.py
credit_spread = 0.005                        # 50 bps fijos para toda contraparte
risk_proxy = credit_spread * (days_to_mat / year_days)
if mtm > 0:
    cva = mtm * risk_proxy
elif mtm < 0:
    dva = abs(mtm) * risk_proxy
mtm = mtm - cva + dva
```

Tres defectos de fondo:

| # | Defecto | Consecuencia |
|---|---|---|
| 1 | Usa el MtM de hoy como exposición esperada de toda la vida del contrato | Un contrato at-the-money tiene CVA **cero**, cuando su exposición futura esperada es estrictamente positiva |
| 2 | Aproxima la probabilidad de default por `spread × t`, sin severidad ni supervivencia acumulada | Sobrestima en plazos largos; ignora que `PD` está acotada por 1 |
| 3 | Aplica el spread a nivel de operación, sin reconocer neteo | Sobrestima cuando hay posiciones opuestas con el mismo banco |

**Evidencia numérica del defecto 1.** Contrato de venta de USD 1.000.000 a 365
días pactado exactamente al forward de mercado (`K = F₀ = 892,36`), spread 100
pb, recovery 40 %, volatilidad FX 12 %:

| Enfoque | MtM | CVA | DVA |
|---|---:|---:|---:|
| v1 (`mtm × spread × t`) | 0,00 | **0,00** | **0,00** |
| v2 (Bachelier + intensidad) | 0,00 | **286.672,82** | **172.677,24** |

El enfoque anterior reporta riesgo de crédito nulo en una operación con
exposición esperada de cientos de millones de pesos a lo largo del año.

**Evidencia numérica del defecto 3.** Cartera Cordada, contraparte Bice con dos
operaciones de signo opuesto (MtM +2.592.813 y −4.346.626):

| | CVA total | DVA total |
|---|---:|---:|
| Con neteo | 41.944,30 | 27.979,14 |
| Sin neteo | 48.085,73 | 31.664,72 |
| **Sobrestimación por ignorar el neteo** | **+14,6 %** | **+13,2 %** |

**Comparación de resultados sobre la cartera Cordada completa** (spread 100 pb,
recovery 40 %, spread propio 60 pb, vol FX 12 %, con neteo):

| Folio | MtM | CVA v1 (50 pb) | DVA v1 | CVA v2 | DVA v2 |
|---|---:|---:|---:|---:|---:|
| 756929 | −5.096.628,95 | 0,00 | 2.619,10 | 9.318,36 | 8.691,40 |
| 118039 | +2.592.812,56 | 1.548,49 | 0,00 | 27.065,83 | 14.780,90 |
| 116845 | −4.346.625,78 | 0,00 | 724,44 | 5.560,11 | 4.506,84 |
| **Total** | **−6.850.442,17** | **1.548,49** | **3.343,54** | **41.944,30** | **27.979,14** |

El enfoque v1 reporta un CVA de 1.548 pesos; el modelo de exposición esperada
reporta 41.944. La diferencia no es de calibración: es que el modelo v1 no mide
exposición futura.

Además, el motor original **sobrescribía el MtM** con el valor ajustado:

```python
mtm = mtm - cva + dva     # el MtM reportado queda contaminado
```

de modo que con CVA activado el MtM guardado ya no coincidía con
`componente spot + puntos forward`. Verificado: con CVA activado el folio 756929
reportaba `mtm = −5.093.613,84` mientras que `spot_component + fwd_points =
−5.096.232,74`. El motor actual mantiene `mtm` y `mtm_ajustado` como campos
separados.

### 10.6 Parámetros

| Parámetro | Símbolo | Por defecto | Fuente recomendada |
|---|---|---:|---|
| Spread de crédito de la contraparte | `s` | 100 pb | CDS cotizado o proxy por rating |
| Tasa de recuperación | `R` | 0,40 | Convención de mercado para deuda senior no garantizada |
| Spread propio | `s_propio` | 60 pb | Costo de fondeo propio |
| Volatilidad FX anualizada | `σ` | 12 % | Volatilidad implícita ATM del plazo relevante |
| Pasos por año de la malla | | 12 | — |

El modelo `Contraparte` permite fijar `spread_bp`, `recovery` y
`tiene_isda_neteo` por contraparte, reemplazando el spread fijo de 50 pb que el
sistema anterior aplicaba a todo el mundo por igual.

---

## 11. Escenarios de sensibilidad

### 11.1 Construcción de la matriz

La matriz cruza dos ejes, ambos en porcentaje:

- **Eje vertical: desplazamiento del spot.** Un shock de `s %` lleva el spot de
  `S` a `S·(1 + s/100)`. La diferencia absoluta `ΔS = S·s/100` se aplica
  **aditivamente a todos los nodos de la curva de outrights**.
- **Eje horizontal: desplazamiento de la curva forward.** Un shock de `c %` se
  aplica **multiplicativamente** sobre la curva ya desplazada, y representa un
  cambio en el diferencial de tasas implícito.

```python
# core/valuation.py
for name, curve in market.curves.items():
    if name.upper().startswith("FWD"):
        curves[name] = curve.shifted(additive=delta_spot, multiplicative=c_pct / 100.0)
    else:
        curves[name] = curve
```

```python
# core/curves.py
def shifted(self, *, additive: float = 0.0, multiplicative: float = 0.0) -> "Curve":
    ys = [(y + additive) * (1.0 + multiplicative) for y in self.ys]
    return Curve(self.name, list(self.xs), ys, self.interp, self.extrap)
```

### 11.2 Por qué el shock de spot arrastra la curva de outrights

Un outright es, por definición, `F(d) = S + p(d)`. Los puntos forward `p(d)`
dependen del **diferencial de tasas**, no del nivel del tipo de cambio. Si el
spot se mueve por una razón que no altera las tasas relativas de las dos
monedas (un flujo de portafolio, una intervención, una noticia de términos de
intercambio), la curva completa de outrights se desplaza en paralelo:

```
S → S + ΔS   ⟹   F(d) = S + p(d) → (S + ΔS) + p(d) = F(d) + ΔS
```

**Si el shock de spot no arrastrara la curva, la matriz estaría midiendo un
cambio del diferencial de tasas disfrazado de cambio del spot**, y la fila
central del eje de curva no coincidiría con el MtM base.

Por eso los dos ejes están separados: el vertical mueve el nivel manteniendo los
puntos, el horizontal mueve los puntos. Sólo se desplazan las curvas cuyo
nombre empieza con `FWD`; la curva de descuento queda intacta, porque un
movimiento del spot no altera la curva cero en CLP.

### 11.3 Revaluación completa vs. aproximación por delta

Por defecto cada celda es una **revalorización completa** de la cartera
(`full_revaluation=True`): se construye una `MarketData` sintética y se llama al
mismo `price_portfolio` que produce el resultado base. Para carteras grandes se
puede usar la aproximación de primer orden

```
MtM(S + ΔS) ≈ MtM(S) + Δ · ΔS
```

que para este producto es exacta salvo por el efecto del descuento sobre el
plazo, dado que gamma es cero (§9.2).

### 11.4 Ejemplo

Cartera Cordada, shock máximo 5 %, 5 puntos por eje. Filas: desplazamiento del
spot (mayor arriba). Columnas: desplazamiento de la curva forward. MtM en CLP.

| Spot | Valor | −5 % | −2,5 % | 0 % | +2,5 % | +5 % |
|---:|---:|---:|---:|---:|---:|---:|
| **+5 %** | 937,53 | 4.081.411 | −112.691.241 | −229.463.893 | −346.236.545 | −463.009.198 |
| **+2,5 %** | 915,21 | 109.822.801 | −4.167.184 | −118.157.168 | −232.147.152 | −346.137.136 |
| **0 %** | 892,89 | 215.564.190 | 104.356.874 | **−6.850.442** | −118.057.758 | −229.265.074 |
| **−2,5 %** | 870,57 | 321.305.579 | 212.880.931 | 104.456.283 | −3.968.365 | −112.393.012 |
| **−5 %** | 848,25 | 427.046.968 | 321.404.988 | 215.763.009 | 110.121.029 | 4.479.049 |

La celda central es exactamente el MtM base, lo que sirve de verificación de
consistencia. La cartera es vendedora neta de USD: gana cuando el peso se
aprecia (spot baja) y pierde cuando se deprecia.

**Cuidado con la interpretación del eje horizontal.** Un shock multiplicativo
del 5 % sobre una curva de outrights en torno a 892 equivale a mover la curva
44,6 pesos, un movimiento enorme. Los valores de las esquinas del eje horizontal
no representan escenarios de diferencial de tasas plausibles, sino un shock
combinado de nivel. Para análisis de diferencial de tasas conviene usar
desplazamientos pequeños (0,1 %-0,5 %) o, mejor, un shock aditivo en puntos
forward.

---

## 12. Supuestos y limitaciones

Lo que el modelo **sí** hace está descrito arriba. Esta sección declara
explícitamente lo que **no** hace, para que nadie lo suponga.

### 12.1 Sobre el producto

- **No hay opcionalidad.** El motor valoriza forwards y sólo forwards. No hay
  opciones, ni forwards con rango, ni estructuras con barreras. Por eso gamma es
  cero y por eso no existe superficie de volatilidad en el modelo de
  valorización.
- **No hay superficie de volatilidad.** La única volatilidad del sistema es el
  parámetro escalar `fx_vol` del perfil de crédito, usada exclusivamente para
  proyectar exposición esperada en el cálculo de CVA/DVA. No hay estructura
  temporal ni sonrisa (*smile*).
- **No hay ajuste por convexidad.** El descuento se hace sobre el flujo neto en
  CLP tratando la curva de descuento como determinista. No se corrige por la
  correlación entre el tipo de cambio y las tasas (efecto *quanto*/convexidad),
  que para plazos cortos es de segundo orden pero no es cero.
- **Modalidad indistinta.** El valor es el mismo para compensación y entrega
  física. La entrega física rigurosa requeriría descontar cada pata en su propia
  curva; el motor lo aproxima usando el outright de mercado y una única curva de
  descuento en CLP.

### 12.2 Sobre las curvas

- **Las curvas son insumos, no se construyen.** El motor no hace *bootstrapping*
  desde swaps ni depósitos: consume los nodos tal como se cargan. La calidad del
  resultado es la calidad del insumo.
- **No se verifica consistencia entre curvas.** El motor no comprueba que la
  curva de outrights y la de descuento satisfagan paridad cubierta con una
  curva USD razonable. Una curva de outrights cargada con error de digitación
  produce un MtM equivocado sin ninguna alarma más allá de los rangos de tasa.
- **Sin interpolación con forma.** No hay *splines* monótonos ni interpolación
  tensionada. Con nodos ruidosos, la interpolación lineal transmite el ruido a
  las tasas forward implícitas.
- **Extrapolación siempre marcada, nunca "correcta".** Cualquier plazo fuera del
  rango de nodos produce una bandera. La política elegida es una decisión de
  política contable, no una propiedad del mercado.

### 12.3 Sobre crédito

- **No hay curva de crédito por plazo.** El spread es un escalar por
  contraparte; la intensidad de default `h` es constante en el tiempo. Una
  estructura temporal de CDS (que en la práctica tiene pendiente) no se puede
  representar.
- **No hay colateral ni CSA.** El modelo supone exposición sin garantías. Con un
  acuerdo de colateral (CSA) con llamadas diarias, el CVA real es una fracción
  del calculado, y aparecería en cambio un ajuste por costo de financiamiento
  del colateral. El motor **no calcula FVA, MVA, ColVA ni KVA**.
- **Wrong-way risk ignorado.** Se supone independencia entre la exposición y la
  probabilidad de default de la contraparte. Para un banco local cuyo riesgo de
  crédito correlaciona con una depreciación fuerte del peso, ese supuesto
  subestima el CVA.
- **Correlación nula entre operaciones del conjunto neteado.** Como se detalla en
  §10.4, la varianza del conjunto se agrega como suma de varianzas. Para
  operaciones sobre el mismo par de monedas la correlación real es cercana a 1 y
  el motor subestima la dispersión del valor neto.
- **Distribución normal del forward.** El modelo Bachelier admite forwards
  negativos con probabilidad positiva. Para un tipo de cambio en torno a 890 con
  volatilidad de 12 % anual, esa probabilidad es numéricamente despreciable en
  los plazos de interés, pero conceptualmente el modelo es inconsistente con el
  hecho de que un tipo de cambio no puede ser negativo.
- **DVA con parámetros del usuario.** El spread propio se ingresa manualmente.
  El motor no lo deriva de nada.

### 12.4 Sobre las convenciones

- **Los días corridos mandan para interpolar.** La convención de conteo de días
  afecta sólo el descuento, no el punto de la curva. Si la curva estuviera
  cotizada en días hábiles, el motor daría resultados equivocados.
- **Calendario de feriados tabulado hasta 2030** para el solsticio de junio (Día
  Nacional de los Pueblos Indígenas). Fuera de ese rango ese feriado
  simplemente no se incluye. Los feriados por ley especial (elecciones,
  conmemoraciones puntuales) no están y deben agregarse manualmente.
- **Sin fecha de liquidación spot explícita.** El motor valoriza a la fecha de
  valorización, no a la fecha de liquidación spot (T+1). Para plazos largos es
  irrelevante; para un contrato que vence en uno o dos días la distinción
  importa.
- **Aproximación en el descuento log-lineal.** Los factores de los nodos se
  calculan con `t = días/base`, mientras que el factor final usa la fracción de
  año de la convención elegida. Con ACT/360 ambas coinciden; con 30/360 o
  ACT/ACT hay una inconsistencia de segundo orden en el tramo interpolado.

### 12.5 Sobre el uso

- **El motor no es la fuente de la verdad contable.** Es una herramienta de
  cálculo y control. La conciliación contra la planilla operativa y contra las
  confirmaciones de las contrapartes sigue siendo necesaria.
- **Sin auditoría de datos de mercado.** No hay validación de que el spot
  cargado corresponda al Dólar Observado publicado, ni de que las curvas
  correspondan a la fecha declarada.
- **Los resultados dependen de la configuración elegida.** Dos corridas con
  distinta política de extrapolación producen números distintos y ambos son
  "correctos" según su propia definición. La configuración se guarda con cada
  valorización (`config_json`) precisamente para que esto sea trazable.

---

## Referencias del código

| Concepto | Archivo |
|---|---|
| Contrato, mercado, configuración, MtM, griegas, escenarios | `core/valuation.py` |
| Curvas, interpolación, extrapolación, factores de descuento | `core/curves.py` |
| Convenciones de conteo de días | `core/daycount.py` |
| Calendarios y reglas de traslado | `core/calendars.py` |
| CVA, DVA, exposición esperada, neteo | `core/credit.py` |
| Réplica del motor en fórmulas nativas de Excel | `core/excel_model.py` |
| Caso de referencia Cordada 31-05-2026 | `valorizador/management/commands/cargar_demo.py` |
| Lectura del libro operativo | `valorizador/services/cordada_excel.py` |
| Tests de la metodología | `core/tests/` (175 casos) |

Auditoría del sistema anterior y trazabilidad de cada cambio metodológico:
[`docs/AUDITORIA.md`](AUDITORIA.md).
