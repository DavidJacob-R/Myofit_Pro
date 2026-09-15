# MyoFit Pro (Python) — EMGTrainer migrado a stack 100% Python

Migración completa de EMGTrainer (antes en C#/WPF) al stack:

- **GUI**: PySide6 + PySide6-Fluent-Widgets + PyQtGraph
- **Hardware**: pyserial (USB, usado por MYOblue) + bleak (BLE, stub para futuro)
- **DSP**: numpy + scipy.signal (Butterworth real de 4to orden, igual al Python original de elemyo)
- **ML**: pandas + scikit-learn + xgboost + lightgbm
- **DB relacional**: SQLite + SQLAlchemy 2.0
- **DB de series de tiempo**: DuckDB (ráfagas EMG completas)
- **Entorno**: `uv`
- **Empaquetado**: Nuitka o PyInstaller
- **Tests**: pytest (21 tests ya escritos y pasando sobre el pipeline DSP y el protocolo binario)

El proyecto C#/WPF queda abandonado — todo el desarrollo continúa aquí.

---

## 1. Instalación con `uv`

```bash
# Si no tienes uv instalado:
curl -LsSf https://astral.sh/uv/install.sh | sh          # Linux/macOS
powershell -c "irm https://astral.sh/uv/install.ps1 | iex" # Windows

# Dentro de la carpeta del proyecto:
uv sync                    # instala TODAS las dependencias (incluye dev: pytest, nuitka, pyinstaller)
```

`uv sync` lee `pyproject.toml` y crea un `.venv` local con todo resuelto y bloqueado
(genera `uv.lock` automáticamente la primera vez).

## 2. Ejecutar la app

```bash
uv run myofit-pro
```

o directamente:

```bash
uv run python -m myofit_pro.main
```

## 3. Correr los tests

```bash
uv run pytest tests/ -v
```

Ahora mismo hay **21 tests** cubriendo:
- Parser del protocolo binario (`test_protocol.py`): paquetes válidos, corruptos, resincronización, residuos parciales.
- Pipeline DSP (`test_filters.py`): bandpass Butterworth (atenúa fuera de banda, pasa dentro de banda, DC removido), notch (atenúa 60Hz, no toca otras frecuencias), envolvente (suaviza, no negativa), RMS (cero en silencio, valor correcto en señal constante).

Todos verificados con señales sintéticas reales, no solo revisión de código.

---

## 4. Mapa de módulos (qué reemplaza a qué del C#)

```
src/myofit_pro/
├── main.py                        → App.xaml.cs (punto de entrada)
├── sensors/                       → Sensors/*.cs (integración MYOblue)
│   ├── protocol.py                → MyoBlueProtocol.cs
│   ├── filters.py                 → Filters.cs (auditado línea por línea contra el Python original de elemyo, ver sección 9)
│   ├── channel.py                 → MyoBlueChannel.cs
│   └── service.py                 → MyoBlueService.cs (pyserial + señales Qt)
├── database/                      → Database/*.cs + Models/*.cs
│   ├── models.py                  → Models/*.cs (SQLAlchemy ORM)
│   ├── engine.py                  → DatabaseService.cs
│   ├── repositories.py            → Database/*Repository.cs
│   └── duckdb_store.py            → (NUEVO) ráfagas EMG completas, no existía en C#
├── ml/                            → (NUEVO) no existía en la versión C#
│   ├── features.py                → extracción de features de la señal
│   ├── activation_classifier.py   → clasificación de patrones de activación
│   └── fatigue_predictor.py       → detección de fatiga + alertas de compensación
└── gui/                           → Views/*.xaml(.cs)
    ├── app_state.py               → MainShell.xaml.cs (estado global + repos)
    ├── main_window.py             → MainShell.xaml (navegación, FluentWindow)
    ├── login_view.py              → LoginView.xaml(.cs)
    ├── register_view.py           → RegisterView.xaml(.cs)
    ├── clients_view.py            → ClientsListView + AddEditClientView
    ├── sensors_view.py            → SensorsView.xaml(.cs)
    ├── sensor_test_window.py      → SensorTestWindow.xaml(.cs) [modal de prueba]
    ├── evaluation_wizard.py       → EvaluationStartView + EvaluationStep1View
    ├── evaluation_wizard_container.py → contenedor de los 6 pasos + navegación interna
    ├── evaluation_step2_view.py   → EvaluationStep2View (guía de colocación de electrodos)
    ├── evaluation_step3_view.py   → EvaluationStep3View (verificación de conexión de sensores)
    ├── evaluation_step4_view.py   → EvaluationStep4View (calibración MVC)
    ├── evaluation_step5_view.py   → EvaluationStep5View (evaluación en vivo)
    ├── evaluation_step6_view.py   → EvaluationStep6View (reporte de la evaluación recién hecha)
    ├── history_view.py            → HistoryView.xaml (historial con sparklines, retomar/cancelar)
    ├── report_view.py             → ReportView.xaml (detalle de una evaluación pasada)
    ├── routine_view.py            → RoutineView.xaml (rutina generada desde evaluaciones)
    ├── alerts_view.py             → AlertsView.xaml (batería baja + recalibraciones vencidas)
    ├── client_profile_view.py     → ClientProfileView.xaml
    └── trainer_profile_view.py    → TrainerProfileView.xaml
```

---

## 5. Estado de cada módulo

| Módulo | Estado |
|---|---|
| Sensores (protocolo, filtros DSP, servicio) | ✅ Completo y probado con pytest |
| Base de datos relacional (SQLAlchemy) | ✅ Completo, probado end-to-end |
| Base de datos de ráfagas (DuckDB) | ✅ Completo, probado end-to-end |
| Login / Registro | ✅ Completo, probado con hash bcrypt real |
| Gestión de clientes (CRUD) | ✅ Completo |
| Sensores sEMG (conexión, batería, modal de prueba) | ✅ Completo (reusa toda la lógica ya validada en la Fase 1 de C#) |
| Wizard — Inicio + Paso 1 (cliente/músculo) | ✅ Completo |
| Wizard — Paso 2: Guía de colocación de electrodos | ✅ Completo |
| Wizard — Paso 3: Verificación de conexión de sensores | ✅ Completo |
| Wizard — Paso 4: Calibración MVC | ✅ Completo — probado con señales simuladas end-to-end |
| Wizard — Paso 5: Evaluación en vivo | ✅ Completo — probado con señales simuladas end-to-end |
| Wizard — Paso 6: Reporte de la evaluación | ✅ Completo |
| Historial sEMG | ✅ Completo — sparklines desde DuckDB, retomar/cancelar evaluaciones en curso |
| Reporte muscular | ✅ Completo |
| Rutina generada | ✅ Completo — genera a partir de calibraciones MVC del cliente |
| Alertas | ✅ Completo — batería baja + calibraciones vencidas (>30 días) |
| Mi perfil / Perfil de cliente | ✅ Completo |
| Sensor BLE nativo (`connect_ble`) | 🟡 Stub intencional — el MYOblue v1.2 usa dongle USB, no BLE directo |
| ML — clasificación de activación | ✅ Heurística funcionando ya; `fit()` con ML real listo para cuando haya datos etiquetados |
| ML — detección de fatiga / compensación | ✅ Heurística funcionando ya (probada); `FatigueGradientBooster` listo para entrenar con historial |

**Importante sobre ML**: los modelos de scikit-learn/xgboost/lightgbm no vienen "pre-entrenados" — no existe un dataset todavía. Lo que sí funciona hoy mismo son las heurísticas basadas en reglas (`rule_based_label`, `fatigue_trend_from_reps`, `execution_balance_alert`), que dan valor inmediato sin necesitar entrenamiento. Cuando acumules evaluaciones reales vía `EmgBurstStore`, `ActivationPatternClassifier.fit()` y `FatigueGradientBooster.fit()` quedan listos para entrenarse con esos datos.

---

## 5.1 Sistema de diseño ("Deep Ink")

Todo el "chrome" visual sale de `gui/theme.py`. Ninguna vista debe
definir colores a mano: si un color no está en los tokens, se agrega al
tema, no a la vista.

**Tokens**: fondo tinta (`BG_MAIN`), superficies (`BG_CARD`,
`BG_ELEVATED`), bordes hairline (`BORDER`), acentos (`ACCENT_VIOLET`
primario, `ACCENT_TEAL` = Sensor A, `ACCENT_BLUE` = Sensor B, ámbar,
rojo, lima) y tipografía (`TEXT_PRIMARY`/`SECONDARY`/`MUTED`).

**Reglas que sigue la app**:

- **Nada de tablas.** Las listas de datos usan `ListRow` (fila-tarjeta
  con avatar, título, subtítulo, valor a color y chevron), no
  `QTableWidget`: una tabla se lee como hoja de cálculo, no como
  producto. El historial del perfil de cliente y las evaluaciones
  recientes del dashboard ya usan este componente.
- **Elegir = tarjeta, no lista de texto.** Los pasos donde el usuario
  escoge algo (cliente, músculo) usan `SelectableCard`, y el botón de
  continuar permanece deshabilitado hasta que haya selección.
- **Color semántico, no decorativo.** `score_color()` mapea 0-100 a
  lima/teal/ámbar/rojo, y `goal_color()` da un color fijo por objetivo
  para que "Hipertrofia" se vea igual en toda la app.
- **Iconos vectoriales**, no emoji multicolor, dentro de `IconBadge` y
  `StatCard` (los emoji grandes se reservan para `EmptyState`).
- **Fechas en español** vía `format_date_es()`: `strftime("%B")` depende
  del locale del sistema y sale en inglés por defecto.

**Componentes**: `Card`, `StatCard`, `ListRow`, `SelectableCard`,
`ClientCard`, `Pill`, `IconBadge`, `Avatar`, `PageHeader`,
`SectionTitle`, `EmptyState`, `Sparkline`, `ScoreRing`, `MeterBar`,
`StepProgressBar`.

El tema se aplica con `apply_app_theme()` **al arrancar la app**, antes
de construir cualquier ventana — si solo se aplicara dentro de
`MainWindow`, el Login y el Registro saldrían en tema claro.

---

## 6. Empaquetado a ejecutable

### Opción A — Nuitka (recomendado, más rápido en ejecución)

```bash
uv run python -m nuitka \
  --standalone \
  --enable-plugin=pyside6 \
  --include-package=myofit_pro \
  --output-dir=dist \
  src/myofit_pro/main.py
```

En Windows agrega `--windows-console-mode=disable` para que no abra una consola detrás.
En macOS agrega `--macos-create-app-bundle` para generar un `.app`.

### Opción B — PyInstaller (más simple de configurar)

```bash
uv run pyinstaller \
  --name MyoFitPro \
  --windowed \
  --collect-all PySide6 \
  --collect-all qfluentwidgets \
  --collect-all duckdb \
  src/myofit_pro/main.py
```

`--collect-all` es necesario para PySide6/qfluentwidgets/duckdb porque tienen
archivos de datos (plugins Qt, binarios nativos) que PyInstaller no detecta
automáticamente por análisis estático.

**Nota sobre xgboost/lightgbm**: ambos traen binarios nativos (`.dll`/`.so`)
que a veces PyInstaller no empaqueta bien de forma automática. Si el ejecutable
falla al importar estos módulos, agrega también `--collect-all xgboost --collect-all lightgbm`.

---

## 7. Monitoreo previo del hardware (Serial Studio)

Antes de conectar el receptor USB a la app, puedes verificar que el hardware
esté transmitiendo usando [Serial Studio](https://serial-studio.github.io/):
conecta el puerto COM a 1,000,000 baudios y deberías ver actividad binaria
constante. Esto ayuda a descartar problemas de driver/cable antes de
depurar dentro de la app.

---

## 8. Diferencias de diseño respecto a la versión C#

- **DSP real, no aproximado**: la versión C# usaba biquads RBJ de 2do orden
  por simplicidad (sin dependencias matemáticas pesadas en .NET). Aquí,
  con scipy disponible, se usa el Butterworth de 4to orden real — el mismo
  algoritmo del `MYOblue_GUI.py` original de elemyo.
- **Señales Qt en vez de eventos .NET + Dispatcher.Invoke**: PySide6 encola
  automáticamente las señales emitidas desde el hilo de lectura serial hacia
  el hilo de la UI, así que no hace falta el equivalente a
  `Dispatcher.Invoke(...)` que se usaba en WPF.
- **DuckDB es nuevo**: la versión C# guardaba solo metadatos de cada lectura
  (`EmgReading.cs`) sin la señal cruda completa. Ahora cada "ráfaga" completa
  (tiempo, µV, filtrada, envolvente, RMS) se guarda en DuckDB, indexada por
  cliente/sesión — esto es lo que alimenta al módulo de ML más adelante.

---

## 9. Auditoría de fidelidad contra el Python original de elemyo

Como todo el stack ahora es Python (antes había que comparar mentalmente
contra un C# intermedio), se hizo una auditoría línea por línea de
`sensors/filters.py` y `sensors/channel.py` contra `MYOblue_GUI.py`
original. Se encontraron y corrigieron 3 discrepancias reales:

1. **Notch incorrecto**: se usaba `scipy.signal.iirnotch` (un filtro
   angosto de 2do orden). El original usa `butter(4, ..., btype='bandstop')`
   con una banda de 4 Hz de ancho alrededor de cada armónico. Corregido
   en `NotchFilter`.
2. **Faltaba el filtro de respaldo `HP_filter`**: el original aplica un
   pasa-altas de 1 Hz antes de rectificar cuando el bandpass está
   desactivado (para no rectificar sobre DC crudo). Se agregó como
   `HighpassFilter` y se integró en `MyoBlueChannel.process_block()`.
3. **Frecuencias de banda por defecto incorrectas**: se usaba 20-450 Hz
   de memoria; el `config.ini` real especifica `BandPassFilterLF=2` y
   `BandPassFilterHF=499`. Corregido en `MyoBlueChannel` y `MyoBlueService`
   (este segundo tenía sus propios defaults duplicados que sobreescribían
   los del primero — también corregido).

También se corrigió `AppState` para que el notch venga **desactivado por
defecto**, igual que `config.ini` (`BandStopFilter = False`) — antes se
activaba a fuerzas en la GUI, lo cual no correspondía al comportamiento
de referencia.

Dos diferencias de diseño se mantienen **a propósito** (no son bugs,
están documentadas en el docstring de `filters.py`):

- Filtrado streaming con estado persistente entre bloques, en vez de
  re-filtrar todo el buffer visible desde cero cada refresco (que es lo
  que hace el original, y por eso necesita "apagar" los primeros 1.5s
  de cada refresco para esconder el transitorio de arranque).
- RMS por `sqrt(mean(x^2))` en una ventana circular, en vez de la fórmula
  recursiva trapezoidal del original (evita acumulación de error de
  punto flotante en sesiones largas).

Los 29 tests de `tests/` (incluye 8 nuevos de esta auditoría) verifican
ambos filtros corregidos con señales sintéticas.
