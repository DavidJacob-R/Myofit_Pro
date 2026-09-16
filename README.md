# MyoFit Pro

Aplicación de escritorio para que entrenadores y fisioterapeutas midan la
activación muscular de sus clientes usando electromiografía de superficie
(sEMG, sensores que se pegan sobre la piel y leen la actividad eléctrica del
músculo).

La idea es responder preguntas que a simple vista no se pueden contestar
durante un entrenamiento: qué tanto se está activando realmente un músculo,
si las dos porciones de ese músculo trabajan parejo o una compensa a la otra,
y si hay fatiga acumulándose a lo largo de la serie.

El flujo de trabajo es el siguiente: el entrenador registra a su cliente,
conecta los sensores, hace una calibración de máxima contracción voluntaria
(MVC, el esfuerzo máximo del cliente que sirve como referencia del 100%), y a
partir de ahí cada evaluación se mide como porcentaje de esa referencia. Todo
queda guardado para poder comparar sesiones en el tiempo.

---

## 1. Hardware necesario

El proyecto está construido alrededor de los sensores **MYOblue v1.2** de
[elemyo](https://elemyo.com/) (el fabricante). Son sensores inalámbricos que
no se conectan por Bluetooth directo a la computadora, sino que transmiten a
un receptor USB (dongle) que se conecta a la PC y se ve como un puerto serial.

Detalles de la comunicación, por si alguien necesita depurar el enlace:

| Parámetro | Valor |
|---|---|
| Velocidad del puerto serial | 1,000,000 baudios |
| Frecuencia de muestreo | 1000 Hz por canal |
| Muestras por paquete | 119 |
| Sensores usados por la app | 2 (Sensor A y Sensor B) |

La app usa **dos sensores sobre el mismo músculo**, colocados en dos porciones
distintas (por ejemplo la porción larga y la corta del bíceps). Esto es lo que
permite detectar desbalances de activación dentro de un mismo músculo, que es
la función principal del producto. No está pensada para medir dos músculos
diferentes al mismo tiempo.

---

## 2. Stack técnico

| Área | Tecnología |
|---|---|
| Interfaz gráfica | PySide6 (Qt para Python) con PySide6-Fluent-Widgets y PyQtGraph |
| Comunicación con hardware | pyserial para el receptor USB, bleak reservado para un futuro sensor Bluetooth |
| Procesamiento de señal | numpy y scipy.signal |
| Machine Learning | pandas, scikit-learn, xgboost, lightgbm |
| Base de datos relacional | SQLite con SQLAlchemy 2.0 |
| Base de datos de señales | DuckDB |
| Seguridad de contraseñas | bcrypt |
| Entorno y dependencias | uv |
| Empaquetado a ejecutable | Nuitka o PyInstaller |
| Pruebas | pytest |

Todo el proyecto es Python. Existió una versión anterior escrita en C# con
WPF, pero está descontinuada y no se le da mantenimiento. En la sección 15
está el contexto histórico, por si interesa saber qué cambió y por qué.

---

## 3. Instalación

El proyecto usa [uv](https://docs.astral.sh/uv/) para manejar el entorno
virtual y las dependencias. Si no está instalado:

```bash
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Ya con uv disponible, dentro de la carpeta del proyecto:

```bash
uv sync
```

Ese comando lee `pyproject.toml`, crea un entorno virtual local en `.venv` e
instala todas las dependencias, incluidas las de desarrollo (pytest, nuitka,
pyinstaller). Las versiones quedan fijadas en `uv.lock`, así que una
instalación nueva reproduce exactamente las mismas versiones.

---

## 4. Primer arranque

### 4.1 Cargar el catálogo de músculos

En una instalación nueva la base de datos está vacía, y sin músculos cargados
el asistente de evaluación no tiene nada que ofrecer. Hay que correr una sola
vez el script de datos semilla:

```bash
uv run python -m myofit_pro.seed_data
```

Esto carga los grupos musculares, los músculos y un catálogo básico de
ejercicios, junto con la guía de colocación de electrodos de cada músculo. El
script es idempotente, es decir que se puede correr varias veces sin duplicar
información porque revisa por nombre antes de insertar.

El catálogo es intencionalmente corto: solo incluye músculos donde tiene
sentido colocar dos sensores en dos porciones distintas, con suficiente masa
muscular para separar los electrodos 2 o 3 centímetros.

### 4.2 Ejecutar la aplicación

```bash
uv run myofit-pro
```

También funciona de forma equivalente:

```bash
uv run python -m myofit_pro.main
```

La primera pantalla es el login. Como todavía no existe ninguna cuenta, hay
que usar el botón "Crear cuenta nueva" para registrar al primer entrenador.
Las contraseñas se guardan con hash bcrypt, nunca en texto plano.

### 4.3 Dónde se guardan los datos

Todo se guarda localmente en la carpeta del usuario, no hay servidor ni nube:

| Archivo | Contenido |
|---|---|
| `~/.myofit_pro/myofit_pro.db` | SQLite: entrenadores, clientes, evaluaciones, calibraciones, rutinas |
| `~/.myofit_pro/emg_bursts.duckdb` | DuckDB: las señales EMG crudas y procesadas de cada evaluación |

---

## 5. Cómo se usa la aplicación

La navegación principal está en la barra lateral y tiene estas secciones:

- **Vista general**: resumen de actividad del entrenador, estado de los
  sensores y últimas evaluaciones.
- **Mis clientes**: alta, edición y baja de clientes, y el perfil individual
  de cada uno con su historial.
- **Nueva evaluación**: el asistente de 6 pasos, que es el flujo central.
- **Historial sEMG**: todas las evaluaciones hechas, con una miniatura de la
  señal real de cada una.
- **Sensores sEMG**: conexión del receptor USB, nivel de batería y una
  ventana de prueba para verificar que los sensores están leyendo.
- **Reporte muscular**: el detalle de una evaluación específica.
- **Rutina generada**: propuesta de rutina a partir de los músculos que el
  cliente ya tiene evaluados.
- **Alertas**: avisos de batería baja y de calibraciones vencidas.

### El asistente de evaluación (6 pasos)

1. **Músculo a evaluar**: se elige el grupo muscular y luego el músculo
   específico. En este punto ya se crea la sesión en la base de datos, de modo
   que si el entrenador abandona el proceso a la mitad la evaluación queda
   registrada como "en curso" y se puede retomar después.
2. **Colocación de electrodos**: muestra la guía específica del músculo
   elegido, indicando dónde va el Sensor A y dónde el Sensor B.
3. **Verificación de conexión**: no deja avanzar hasta que el receptor esté
   conectado y los dos sensores estén transmitiendo señal viva.
4. **Calibración MVC**: se pide la contracción máxima del cliente y se guarda
   como referencia del 100% para ese músculo.
5. **Evaluación en vivo**: se graba la serie de repeticiones y se calcula la
   activación de cada canal respecto al MVC.
6. **Reporte**: resultado de la evaluación recién terminada, con el score
   general y el balance entre canales.

Si queda una evaluación sin terminar, la barra lateral muestra un contador
junto a "Nueva evaluación", y al entrar a esa sección la app ofrece retomarla
o descartarla, para que no se quede colgada indefinidamente.

---

## 6. Arquitectura del código

```
src/myofit_pro/
├── main.py                 Punto de entrada. Login y registro, y de ahí a la ventana principal
│
├── sensors/                Todo lo que toca el hardware
│   ├── protocol.py         Lectura del protocolo binario del receptor USB
│   ├── filters.py          Filtros digitales (bandpass, notch, pasa-altas, envolvente, RMS)
│   ├── channel.py          Un canal de sensor: aplica el pipeline de filtros a los bloques que llegan
│   └── service.py          Lectura del puerto serial en un hilo aparte y emisión de señales Qt
│
├── database/               Persistencia
│   ├── models.py           Tablas del ORM (SQLAlchemy)
│   ├── engine.py           Conexión a SQLite, creación de tablas y migraciones ligeras
│   ├── repositories.py     Consultas, agrupadas por entidad
│   └── duckdb_store.py     Guardado y lectura de las señales EMG completas
│
├── ml/                     Análisis de la señal
│   ├── features.py         Extracción de características de una ráfaga de señal
│   ├── activation_classifier.py  Clasificación del patrón de activación
│   └── fatigue_predictor.py      Detección de fatiga y alertas de compensación
│
└── gui/                    Interfaz
    ├── theme.py            Sistema de diseño: colores, tipografía y componentes reutilizables
    ├── app_state.py        Estado compartido de la sesión (usuario, repositorios, servicio de sensores)
    ├── main_window.py      Ventana principal y navegación lateral
    ├── login_view.py / register_view.py
    ├── dashboard_view.py
    ├── clients_container.py / clients_view.py / client_profile_view.py
    ├── evaluation_wizard_container.py   Contenedor de los 6 pasos
    ├── evaluation_wizard.py             Pasos 0 y 1
    ├── evaluation_step2_view.py … step6_view.py
    ├── sensors_view.py / sensor_test_window.py
    ├── history_view.py / report_view.py / routine_view.py / alerts_view.py
    └── trainer_profile_view.py
```

Dos decisiones de estructura que conviene conocer antes de tocar la GUI:

- **El hilo de lectura serial nunca toca la interfaz.** `MyoBlueService` lee el
  puerto en un hilo aparte y comunica los datos mediante señales de Qt, que
  Qt entrega automáticamente en el hilo de la interfaz. No hace falta ningún
  mecanismo manual de sincronización.
- **Hay secciones con navegación interna.** "Mis clientes" y "Nueva
  evaluación" son contenedores con varias pantallas adentro, y solo aparecen
  como un elemento en la barra lateral. Esto evita que pasos intermedios del
  asistente se muestren sueltos en el menú.

---

## 7. Procesamiento de la señal

La señal cruda de un sensor sEMG no sirve tal cual: trae componente continua,
ruido eléctrico de la red y una forma de onda que oscila en positivo y
negativo alrededor de cero. El pipeline que aplica la app a cada bloque de
muestras es este:

1. **Conversión a microvolts** de las muestras crudas del convertidor
   analógico-digital.
2. **Filtro notch (rechaza-banda) opcional**, que elimina la interferencia de
   la red eléctrica y sus armónicos. Viene desactivado por defecto, igual que
   en la configuración de referencia del fabricante. Está puesto en 60 Hz, que
   es la frecuencia de México y Estados Unidos ; para Europa hay que cambiarlo
   a 50 Hz en `app_state.py`.
3. **Filtro pasa-banda Butterworth de 4to orden**, de 2 a 499 Hz por defecto.
   Quita la componente continua y el ruido fuera de la banda útil. El
   resultado de este paso es la señal que se grafica.
4. **Envolvente**: rectifica la señal (toma el valor absoluto, porque para
   medir esfuerzo importa la magnitud de la activación y no su signo) y la
   suaviza con tres promedios móviles exponenciales en cascada. Es lo que hace
   legible el esfuerzo a lo largo del tiempo.
5. **RMS** (valor cuadrático medio) sobre una ventana móvil de la envolvente,
   con ventana de medio segundo por defecto. Esta es la medida que se usa para
   cuantificar la intensidad de la contracción y para contar repeticiones por
   umbral.

Si el pasa-banda se desactiva, la señal pasa antes por un pasa-altas de 1 Hz,
porque rectificar directamente una señal con componente continua daría un
resultado sin sentido.

Los filtros mantienen su estado entre bloques (filtrado en streaming), en vez
de volver a filtrar todo el buffer visible en cada refresco de pantalla. Esto
evita el transitorio de arranque que aparecería en cada actualización.

---

## 8. Por qué hay dos bases de datos

Son dos tipos de información con necesidades muy distintas:

- **SQLite** guarda los datos estructurados del negocio: quién es el
  entrenador, quiénes son sus clientes, qué evaluaciones se hicieron, con qué
  resultados. Son registros pequeños que se consultan y se relacionan entre
  sí, que es exactamente para lo que sirve una base relacional.
- **DuckDB** guarda las señales completas: para cada evaluación se almacenan
  los arreglos de tiempo, microvolts, señal filtrada, envolvente y RMS. Son
  miles de valores por evaluación, y meterlos en SQLite haría la base pesada y
  lenta. DuckDB está pensado para consultas analíticas sobre columnas de
  muchos datos, que es justo lo que se necesita para alimentar después al
  módulo de Machine Learning.

La tabla `EmgReading` de SQLite guarda un campo `burst_id` que apunta al
registro correspondiente en DuckDB. No es una llave foránea real porque son
dos motores distintos, es un enlace lógico que la aplicación mantiene.

---

## 9. Módulo de Machine Learning

Conviene ser claro con el estado real de este módulo, porque el nombre puede
generar expectativas equivocadas.

**Lo que funciona hoy** son heurísticas basadas en reglas, que no necesitan
entrenamiento y dan resultado desde la primera evaluación:

- `rule_based_label()` clasifica el patrón de activación comparando el RMS de
  los dos canales.
- `fatigue_trend_from_reps()` detecta fatiga siguiendo cómo baja la frecuencia
  mediana de la señal repetición tras repetición, que es el indicador clásico
  de fatiga muscular en sEMG.
- `execution_balance_alert()` avisa cuando un canal está compensando al otro.

**Lo que está listo pero sin usar** son los modelos entrenables
(`ActivationPatternClassifier` y `FatigueGradientBooster`). Tienen sus métodos
`fit()`, `predict()`, `save()` y `load()` implementados, pero no vienen
preentrenados porque todavía no existe un conjunto de datos etiquetados. En
cuanto se acumulen evaluaciones reales en DuckDB, esos modelos se pueden
entrenar con ellas sin cambiar la arquitectura.

---

## 10. Sistema de diseño de la interfaz

Toda la apariencia de la aplicación sale de `gui/theme.py`. La regla es que
ninguna pantalla define colores por su cuenta: si hace falta un color que no
está en los tokens del tema, se agrega al tema y no a la pantalla.

**Paleta**: fondo casi negro con superficies elevadas y bordes delgados. El
color primario es violeta. El turquesa y el azul están reservados para el
Sensor A y el Sensor B respectivamente, y ese significado se respeta en toda
la aplicación, así que no conviene usarlos como decoración.

**Criterios que sigue la interfaz:**

- **No se usan tablas.** Las listas de datos se arman con el componente
  `ListRow`, que es una fila con forma de tarjeta (avatar, título, subtítulo,
  valor a color y flecha). Una tabla hace que la información se lea como hoja
  de cálculo en vez de como producto terminado.
- **Elegir algo se hace con tarjetas, no con listas de texto.** Donde el
  usuario selecciona un cliente o un músculo se usa `SelectableCard`, y el
  botón de continuar permanece deshabilitado mientras no haya selección.
- **El color comunica información, no adorna.** `score_color()` traduce un
  score de 0 a 100 a una escala de lima, turquesa, ámbar y rojo, y
  `goal_color()` asigna un color fijo a cada objetivo de entrenamiento para
  que un mismo objetivo se vea igual en todas las pantallas.
- **Los iconos son vectoriales**, no emoji de color, dentro de `IconBadge` y
  `StatCard`. Los emoji grandes se reservan para las pantallas vacías.
- **Las fechas se formatean con `format_date_es()`**, porque `strftime("%B")`
  depende de la configuración regional del sistema y devuelve los meses en
  inglés en una instalación por defecto.

**Componentes disponibles**: `Card`, `StatCard`, `ListRow`, `SelectableCard`,
`ClientCard`, `Pill`, `IconBadge`, `Avatar`, `PageHeader`, `SectionTitle`,
`EmptyState`, `Sparkline`, `ScoreRing`, `MeterBar` y `StepProgressBar`.

El tema se aplica llamando a `apply_app_theme()` al arrancar la aplicación,
antes de construir cualquier ventana. El orden importa: si se aplicara
únicamente dentro de la ventana principal, las pantallas de login y registro
se mostrarían con el tema claro.

---

## 11. Pruebas

```bash
uv run pytest tests/ -v
```

Actualmente hay **29 pruebas** que cubren las partes donde un error sería
difícil de detectar a simple vista:

- **Protocolo binario** (`test_protocol.py`): paquetes válidos, paquetes
  corruptos, resincronización del flujo y manejo de datos parciales.
- **Filtros y pipeline DSP** (`test_filters.py`, `test_channel.py`): que el
  pasa-banda atenúe lo que está fuera de la banda y deje pasar lo que está
  dentro, que el notch elimine la frecuencia objetivo sin afectar a las demás,
  que la envolvente suavice y nunca sea negativa, y que el RMS dé cero en
  silencio y el valor correcto en una señal conocida.

Las pruebas se hacen con señales sintéticas generadas dentro del propio test,
verificando el resultado numérico y no solamente que el código corra.

La interfaz gráfica no tiene pruebas automatizadas todavía.

Una nota para quien quiera automatizar capturas de pantalla: la librería
qfluentwidgets no funciona con la plataforma `offscreen` de Qt
(`QT_QPA_PLATFORM=offscreen` provoca un fallo de segmentación al construir la
ventana), porque usa funciones nativas de ventana. Las capturas hay que
hacerlas con el backend gráfico normal del sistema.

---

## 12. Empaquetado a ejecutable

### Opción A: Nuitka

Compila a código nativo, por lo que el ejecutable arranca y corre más rápido.

```bash
uv run python -m nuitka \
  --standalone \
  --enable-plugin=pyside6 \
  --include-package=myofit_pro \
  --output-dir=dist \
  src/myofit_pro/main.py
```

En Windows conviene agregar `--windows-console-mode=disable` para que no se
abra una ventana de consola detrás de la aplicación. En macOS,
`--macos-create-app-bundle` genera un `.app`.

### Opción B: PyInstaller

Más simple de configurar, aunque el resultado es más lento al arrancar.

```bash
uv run pyinstaller \
  --name MyoFitPro \
  --windowed \
  --collect-all PySide6 \
  --collect-all qfluentwidgets \
  --collect-all duckdb \
  src/myofit_pro/main.py
```

Las opciones `--collect-all` son necesarias porque esas librerías incluyen
archivos que no son código Python (plugins de Qt, binarios nativos) y
PyInstaller no los detecta analizando los imports.

Si el ejecutable falla al importar xgboost o lightgbm, hay que agregar
también `--collect-all xgboost --collect-all lightgbm`, ya que ambos traen
binarios nativos que tampoco se detectan automáticamente.

---

## 13. Diagnóstico del hardware

Si la aplicación no recibe datos, conviene descartar primero que el problema
sea del hardware, del cable o del driver, antes de buscarlo en el código.

Con [Serial Studio](https://serial-studio.github.io/) se puede abrir el puerto
del receptor a 1,000,000 baudios. Si el hardware está transmitiendo
correctamente debe verse actividad binaria constante. Si ahí no llega nada, el
problema no está en la aplicación.

---

## 14. Estado del proyecto

| Módulo | Estado |
|---|---|
| Protocolo, filtros DSP y servicio de sensores | Completo, cubierto por pruebas automatizadas |
| Base de datos relacional (SQLite) | Completo |
| Almacenamiento de señales (DuckDB) | Completo |
| Login y registro | Completo, con hash bcrypt |
| Gestión de clientes | Completo |
| Pantalla de sensores y ventana de prueba | Completo |
| Asistente de evaluación, los 6 pasos | Completo, validado con señales simuladas |
| Historial, reporte, rutina, alertas y perfiles | Completo |
| Análisis por heurísticas (activación y fatiga) | Funcionando |
| Modelos de ML entrenables | Implementados, sin entrenar por falta de datos |
| Conexión Bluetooth directa (`connect_ble`) | Sin implementar a propósito, ver abajo |

Sobre `connect_ble()`: el método existe y lanza `NotImplementedError` de
forma deliberada. El MYOblue v1.2 se comunica por un receptor USB y no por
Bluetooth directo, así que no hay nada que conectar. El método queda como
punto de extensión por si más adelante se soporta un sensor que sí hable
Bluetooth nativo, lo cual requeriría conocer los identificadores de servicio
y característica del fabricante.

**Pendientes conocidos:**

- El flujo completo con hardware real conectado todavía no se ha validado de
  principio a fin. Las pruebas se han hecho con señales simuladas.
- No hay pruebas automatizadas de la interfaz gráfica.
- No existe una pantalla de configuración para ajustar parámetros de los
  filtros (frecuencia del notch, límites de la banda), que hoy se cambian en
  el código.

---

## 15. Anexo: origen del proyecto

Esta aplicación es la reescritura en Python de un proyecto anterior llamado
EMGTrainer, hecho en C# con WPF. Esa versión está descontinuada. Se dejan
documentadas aquí las diferencias importantes, porque explican por qué algunas
cosas están hechas como están.

**DSP exacto en vez de aproximado.** La versión anterior en C# usaba filtros
biquad RBJ de segundo orden por simplicidad del proyecto, que no tenía
dependencias matemáticas pesadas en .NET. Ahora, con scipy disponible, se usa
un Butterworth de cuarto orden, que es el mismo algoritmo del `MYOblue_GUI.py`
original de elemyo (el fabricante de los sensores).

**Señales de Qt en vez de eventos de .NET.** En WPF había que usar
`Dispatcher.Invoke(...)` para llevar los datos del hilo de lectura al hilo de
la interfaz. PySide6 hace esa entrega automáticamente cuando se conectan
señales entre hilos, así que ese código desapareció.

**Almacenamiento de la señal cruda.** La versión en C# guardaba únicamente los
metadatos de cada lectura, sin la señal. Guardar la señal completa en DuckDB
es lo que hace posible el módulo de Machine Learning, que no existía antes.

### Auditoría contra la implementación de referencia

Al ser ahora todo Python, se pudo comparar directamente el código de
`sensors/filters.py` y `sensors/channel.py` contra el `MYOblue_GUI.py`
original del fabricante. De esa comparación salieron tres correcciones:

1. **El filtro notch estaba mal implementado.** Se usaba
   `scipy.signal.iirnotch`, que es un filtro angosto de segundo orden. La
   referencia usa un `butter(4, ..., btype='bandstop')` con una banda de 4 Hz
   de ancho alrededor de cada armónico.
2. **Faltaba el pasa-altas de respaldo.** La referencia aplica un pasa-altas
   de 1 Hz antes de rectificar cuando el pasa-banda está desactivado, para no
   rectificar sobre una señal con componente continua.
3. **Las frecuencias de banda por defecto eran incorrectas.** Se estaban
   usando 20 a 450 Hz, cuando el archivo de configuración real del fabricante
   indica 2 a 499 Hz. Además el servicio tenía sus propios valores por defecto
   duplicados que sobrescribían a los del canal, lo cual también se corrigió.

También se ajustó el estado inicial para que el notch venga desactivado por
defecto, igual que en la configuración de referencia. Antes se activaba desde
la interfaz, lo cual no correspondía al comportamiento del fabricante.

Dos diferencias se mantienen a propósito y están documentadas en el docstring
de `filters.py`:

- **Filtrado en streaming** con estado persistente entre bloques, en lugar de
  refiltrar todo el buffer visible en cada refresco. La referencia hace lo
  segundo, y por eso necesita descartar el primer segundo y medio de cada
  actualización para esconder el transitorio.
- **RMS calculado como `sqrt(mean(x^2))`** sobre una ventana circular, en vez
  de la fórmula recursiva trapezoidal de la referencia. Esto evita que se
  acumule error de punto flotante en sesiones largas.
