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

El catálogo es intencionalmente corto en cuanto a músculos: solo incluye
aquellos donde tiene sentido colocar dos sensores en dos porciones distintas,
con suficiente masa muscular para separar los electrodos 2 o 3 centímetros.

En cuanto a ejercicios, en cambio, se queda corto para lo que hace falta.
Trae 25 ejercicios repartidos en 9 músculos, o sea 2 o 3 por músculo, y la
batería del paso 5 sirve para ordenar ejercicios entre sí: con tres, el orden
no descarta gran cosa. Para que el tamizaje valga la pena conviene subirlo a
5 o 6 por músculo, que es trabajo de catálogo y se hace editando
`seed_data.py`, sin tocar código.

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

- **Vista general**: gráfica de evaluaciones por semana de los últimos dos
  meses, cifras del mes, accesos directos a lo que se usa a diario, estado de
  los sensores, las últimas evaluaciones y una lista de clientes a los que
  toca dar seguimiento (sin evaluar, o con más de tres semanas desde la
  última).
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

Las pantallas que se abren desde otra (el perfil de un cliente, el reporte de
una evaluación) traen su propio botón de volver, y ese botón regresa a donde
se venía: el reporte se abre desde tres lugares distintos y en cada uno
"volver" significa algo diferente.

### La ficha del cliente

El alta se reparte en tres pasos, porque un formulario de una sola pantalla
con doce campos se abandona a la mitad:

1. **Datos personales**: nombre, apellido, sexo y edad. El sexo y la edad no
   son burocracia, entran en las fórmulas del paso siguiente.
2. **Medidas corporales**: estatura y peso, de donde sale el índice de masa
   corporal, y el porcentaje de grasa.
3. **Objetivo y plan**: objetivo de entrenamiento, nivel de experiencia,
   días disponibles a la semana y notas.

Todos los datos físicos son opcionales para no bloquear un alta rápida, pero
son las variables con las que el generador de rutinas ajusta volumen e
intensidad, así que las fichas incompletas se marcan en la lista y en el
perfil para poder terminarlas después.

Los campos numéricos guardan "sin especificar" como ausencia de dato y no como
cero. Un cliente sin peso registrado no pesa cero kilos, y guardarlo así
arrastraría hacia abajo cualquier promedio que se calcule más adelante.

El alta y la edición usan exactamente el mismo formulario. Si el alta pidiera
un dato que la edición no ofrece, ese dato quedaría imposible de corregir.

### Composición corporal y por qué se guarda de dónde salió

Los sensores sEMG no pueden medir grasa corporal. La vía eléctrica para
estimarla es la bioimpedancia, que consiste en inyectar una corriente alterna
muy pequeña por el cuerpo (alrededor de los 50 kHz) y medir la caída de
voltaje. El MYOblue es un amplificador diferencial pasivo: solo lee el
biopotencial que el músculo genera por su cuenta, no tiene fuente de
corriente, y eso no es algo que se pueda agregar por software. Aunque la
tuviera, tampoco podría verla: se muestrea a 1000 Hz con un pasa-banda de 2 a
499 Hz, así que 50 kHz queda dos órdenes de magnitud fuera de lo observable.

Por eso el porcentaje de grasa entra a mano o se calcula. Hay tres formas, y
**no valen lo mismo como dato de entrada para un modelo de predicción**. La
app guarda cuál se usó, en `Client.body_fat_source`:

| Fuente | De dónde sale | ¿Sirve como variable del modelo? |
|---|---|---|
| `medido` | Báscula de bioimpedancia o plicómetro | Sí, es el mejor dato |
| `medidas` | Circunferencias, método de la Marina de EUA | Sí, es información independiente |
| `estimado` | Fórmula de Deurenberg | No, ver abajo |

La fórmula de Deurenberg es `%grasa = 1.20 x IMC + 0.23 x edad - 10.8 x sexo -
5.4`. Es decir, una combinación lineal de tres variables que el modelo ya
recibe por separado. Si se le entrega como cuarta variable, esa columna queda
determinada exactamente por las otras tres: es colinealidad perfecta, que
vuelve inestables los coeficientes de una regresión lineal y, en un modelo de
árboles, reparte la importancia entre columnas duplicadas y ensucia la
interpretación.

El problema práctico se ve con números. Tres hombres de 178 cm, 82.5 kg y 28
años, con cinturas de 80, 88 y 100 cm:

| Cintura | Deurenberg | Circunferencias |
|---|---|---|
| 80 cm | 21.5% | 12.4% |
| 88 cm | 21.5% | 18.7% |
| 100 cm | 21.5% | 26.7% |

Deurenberg les da el mismo número a los tres, porque no tiene forma de
distinguirlos: comparten IMC, edad y sexo. Las circunferencias los separan por
más de 14 puntos. Por eso el formulario pide cuello y cintura (y cadera en
mujeres) como opcional pero recomendado: es la diferencia entre un dato que
distingue clientes y una estimación que solo repite lo que ya se sabía.

`body_composition.features_for_model()` aplica esa regla: incluye el
porcentaje de grasa solo cuando es medido o de circunferencias, y en su lugar
deja `body_fat_is_real` en cero cuando es estimación. El objetivo se codifica
one-hot y no como 1, 2, 3, porque un número ordinal le diría al modelo que
definición está "entre" fuerza e hipertrofia, que no significa nada.

La estimación sí se muestra en pantalla, con una nota que aclara que es una
estimación. Sirve para darle una referencia al entrenador, que es distinto de
servir como variable de entrada.

### El asistente de evaluación (6 pasos)

1. **Músculo a evaluar**: se elige el grupo muscular y luego el músculo
   específico. En este punto ya se crea la sesión en la base de datos, de modo
   que si el entrenador abandona el proceso a la mitad la evaluación queda
   registrada como "en curso" y se puede retomar después.
2. **Colocación de electrodos**: muestra la guía específica del músculo
   elegido, indicando dónde va el Sensor A y dónde el Sensor B, junto con los
   pasos de preparación de la piel y el color que cada sensor va a tener en
   las gráficas de los pasos siguientes.
3. **Verificación de conexión**: muestra la señal en vivo de cada sensor con
   su batería, su RMS actual y su nivel de saturación. No deja avanzar hasta
   que se cumplan los tres requisitos (receptor conectado, ambos sensores
   transmitiendo y buen contacto con la piel), y los tres se muestran con su
   estado para que se vea cuál falta cuando el botón está bloqueado.
4. **Calibración MVC**: se pide la contracción máxima del cliente y se guarda
   como referencia del 100% para ese músculo.
5. **Batería de ejercicios**: se graba una serie por cada ejercicio del
   músculo, todas contra la MISMA calibración del paso 4, y cada una queda
   etiquetada con el ejercicio que se hizo. Se puede medir el mismo ejercicio
   varias veces: el promedio queda más confiable y la pantalla calcula el
   coeficiente de variación de la medición, que es el número con el que se
   decide si la diferencia entre dos ejercicios es real o es ruido.
6. **Reporte**: ranking de ejercicios ordenado por activación para ese
   cliente, más el score general y el balance entre canales.

Los dos botones de navegación viven juntos en un pie único, el mismo en todos
los pasos: volver a la izquierda y continuar ocupando el resto del ancho.
Antes cada paso dibujaba su propio botón de continuar al final de su contenido
y el de volver estaba arriba en el encabezado, así que las dos acciones
quedaban en extremos opuestos de la pantalla. El contenedor le pregunta al
paso actual qué dice su botón, si se puede presionar y qué hacer al
presionarlo, y el paso se queda solo con su contenido (ver
`gui/wizard_step.py`).

El encabezado dice el nombre del paso, qué se espera del entrenador y el
progreso. Nada más. Antes indicaba el paso tres veces (un círculo con el
número, el texto "Paso 2 de 6" y la barra de progreso marcando el 2) y además
repetía en cada pantalla el cliente y el músculo ya elegidos. Quedó solo la
barra de progreso, que es la única de las tres que además dice cuánto falta.

El asistente lleva la pila de pasos visitados, así que el botón de volver
regresa a donde el entrenador estaba de verdad, incluso cuando se retoma una
evaluación a la mitad y se entra directo al paso 5. Retroceder del
paso 2 al 1 descarta la sesión que se había creado al elegir el músculo: si no
lo hiciera, cada ida y vuelta dejaría una evaluación vacía marcada como "en
curso" y el contador de la barra lateral subiría solo. Desde el reporte ya no
se puede retroceder, porque llevaría a repetir una medición que ya se guardó.

Si queda una evaluación sin terminar, la barra lateral muestra un contador
junto a "Nueva evaluación", y al entrar a esa sección la app ofrece retomarla
o descartarla, para que no se quede colgada indefinidamente.

### Eliminar evaluaciones

Tanto el historial de un cliente como la sección "Historial sEMG" permiten
eliminar una evaluación. El borrado se lleva la sesión, sus resultados, sus
lecturas y la señal cruda que le corresponde en DuckDB.

Se hace recorriendo los hijos a mano y no con un borrado en cascada porque
SQLite no aplica las llaves foráneas a menos que se active `PRAGMA
foreign_keys` en cada conexión. Sin eso quedarían resultados y lecturas
apuntando a una sesión que ya no existe, y arrays de señal ocupando espacio en
DuckDB sin que nada los referencie.

Lo mismo aplica al borrar un cliente: se van sus evaluaciones y sus
calibraciones. Las rutinas que se hayan generado a partir de una evaluación
borrada se conservan y solo pierden la referencia, porque son un entregable
que el cliente pudo haberse llevado.

---

## 6. Arquitectura del código

```
src/myofit_pro/
├── main.py                 Punto de entrada. Login y registro, y de ahí a la ventana principal
├── body_composition.py     IMC, grasa corporal y las variables del cliente para el modelo
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
│   ├── fatigue_predictor.py      Detección de fatiga y alertas de compensación
│   ├── synthetic.py        Generador de datos sintéticos para probar algoritmos
│   ├── benchmark.py        Comparación de algoritmos con validación por cliente
│   └── within_subject.py   Simulación del diseño de cada cliente contra sí mismo
│
└── gui/                    Interfaz
    ├── theme.py            Sistema de diseño: colores, tipografía y componentes reutilizables
    ├── app_state.py        Estado compartido de la sesión (usuario, repositorios, servicio de sensores)
    ├── main_window.py      Ventana principal y navegación lateral
    ├── login_view.py / register_view.py
    ├── dashboard_view.py
    ├── clients_container.py / clients_view.py / client_profile_view.py
    ├── client_form.py       Alta y edición de cliente, en tres pasos
    ├── wizard_step.py       Contrato que cumplen los pasos del asistente
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

**Las variables del cliente** salen de `body_composition.features_for_model()`,
que vive fuera de `ml/` porque también la usa la pantalla de alta. Devuelve
IMC, edad, estatura, peso, sexo, nivel de experiencia, días por semana, el
objetivo codificado one-hot y el porcentaje de grasa cuando es un dato real.
Devuelve `None` si falta algo imprescindible, para que quien la llame descarte
la fila en vez de rellenarla con ceros.

### Qué algoritmos tienen sentido y cuáles no

"Predecir la rutina" no es un problema, son varios, y no todos se
resuelven con aprendizaje automático.

**Series y repeticiones no se predicen con un modelo.** No hay etiqueta que
aprender: habría que copiar lo que ya decidió un entrenador, con lo cual el
modelo solo aprendería a imitarlo, errores incluidos. Además la respuesta ya
está establecida en la literatura de entrenamiento como rangos por objetivo,
así que una tabla de reglas acierta desde el primer día, se puede explicar al
cliente y no necesita acumular datos. Meter un modelo ahí es cambiar algo
correcto y explicable por algo aproximado y opaco.

**Lo que sí se aprende de los datos** son dos cosas, y las dos tienen la
etiqueta incluida en la señal, sin que nadie tenga que clasificar nada a mano:

1. **Fatigabilidad**: qué tan rápido cae la frecuencia mediana del cliente.
2. **Activación por ejercicio**: cuánto activa un ejercicio concreto a una
   persona concreta. Es lo que ninguna tabla puede saber y los sensores sí.

Para el tamaño de datos que este proyecto va a tener (cientos de filas, no
millones) los modelos lineales regularizados son la opción correcta. Las redes
neuronales no tienen nada que aportar con ocho variables y sí traen sobreajuste
y una caja negra imposible de justificar frente a un entrenador.

### Probar los algoritmos antes de tener datos reales

Hay un generador de datos sintéticos y un banco de pruebas:

```bash
uv run python -m myofit_pro.ml.synthetic --clientes 100 --salida datos/
uv run python -m myofit_pro.ml.benchmark datos/
```

El primero deja `clientes.csv`, `evaluaciones.csv`, `dataset.csv` y
`verdad_base.json` con los coeficientes que se usaron para generarlos, para
poder comprobar si un algoritmo los recupera. El segundo compara varios
modelos y deja los resultados en `datos/resultados/` para analizarlos aparte.

**Para qué sirve esto y para qué no.** Los datos salen de fórmulas que
escribimos nosotros. Que un modelo las recupere demuestra que la tubería y la
validación están bien, no que la edad y la grasa corporal expliquen la fatiga
en personas reales. Eso solo se sabe con los clientes del gimnasio. Sirve para
validar el código, medir cuántos clientes hacen falta y comparar algoritmos en
igualdad de condiciones.

**La trampa que el banco demuestra.** Un cliente aporta varias evaluaciones y
esas evaluaciones se parecen entre sí. Si el conjunto se parte al azar, el
mismo cliente cae en entrenamiento y en prueba, el modelo lo memoriza y
reporta un resultado excelente que se desploma con un cliente nuevo, que es el
caso que importa. La partición correcta agrupa por `client_id` (GroupKFold).
Sobre los datos sintéticos, Random Forest pasa de un R2 de 0.22 con la
partición correcta a 0.77 con la partición al azar: más de medio punto de
diferencia que es puro espejismo.

**El techo de predicción.** Antes de entrenar nada conviene ver cuánta
variación del objetivo está entre clientes y cuánta dentro del mismo cliente.
Los datos de la ficha son constantes dentro de una persona, así que solo
pueden explicar la parte que varía entre personas. Si el 50% de la variación
es interna, el techo de cualquier modelo basado en la ficha es un R2 de 0.50,
por bueno que sea el algoritmo. El banco lo calcula y lo imprime.

**No dar variables derivadas unas de otras.** El IMC es peso entre estatura al
cuadrado, así que pasar estatura, peso e IMC juntos es dar la misma
información dos veces. En el banco, hacerlo dispara los coeficientes de Ridge
de una suma absoluta de 9.1 a 48.8, con signos alternados que se cancelan: el
modelo predice casi igual pero sus pesos dejan de decir nada sobre qué influye
en qué. Es el mismo problema que con la fórmula de Deurenberg, explicado en la
sección 5.

### Comparar a cada cliente consigo mismo

El diseño que persigue el proyecto no es comparar clientes entre sí, sino
comparar a cada cliente consigo mismo: se le hace una batería con todos los
ejercicios posibles de un músculo, se ordenan de mejor a peor para esa
persona, y con eso se arma su rutina. Semanas después se vuelve a medir.

Esto es estadísticamente más fuerte que comparar entre personas. Cada quien
tiene un nivel propio de amplitud que depende de su grasa subcutánea, su masa
muscular y su anatomía; al comparar entre personas ese nivel es ruido que se
come casi toda la capacidad de predicción, y al comparar a alguien consigo
mismo se cancela, porque está igual en todas sus mediciones. El problema pasa
de "predecir un número" a "ordenar una lista".

Todo depende entonces de una sola pregunta: si un ejercicio mide 72% y otro
68%, ¿esos 4 puntos son reales o son ruido de medición? `within_subject.py`
la responde por simulación:

```bash
uv run python -m myofit_pro.ml.within_subject
uv run python -m myofit_pro.ml.within_subject --cv 0.12 --ejercicios 8
```

Tres resultados que cambian el diseño del producto:

**Recomendar tres ejercicios, no uno.** Con una repetibilidad del 10% y una
medición por ejercicio, el que queda primero es de verdad el mejor solo el 66%
de las veces, pero el mejor real está entre los tres primeros el 95% de las
veces. Decir "estos son tus tres mejores" es una afirmación que la medición
sostiene; decir "este es el mejor" no.

**La batería tiene un límite práctico.** Medir cada ejercicio tres veces sube
la certeza, pero con ocho ejercicios son 24 series en una sesión, y la fatiga
acumulada contamina justo lo que se está midiendo. La tensión entre cuántos
ejercicios probar y cuántas veces medir cada uno es real y hay que resolverla
con números, no con intuición.

**El seguimiento no puede basarse en amplitudes absolutas entre sesiones.**
Al quitar y volver a poner los electrodos cambia la ganancia de todo lo que se
mida ese día. Con la repetibilidad que reporta la literatura para electrodos
re-colocados, el cambio mínimo detectable con una sola medición pasa de la
mitad del valor, y una mejora real del 10% se detecta menos de una de cada
cinco veces. Lo que sí aguanta son las comparaciones que son cocientes dentro
de la misma sesión, porque el factor de ganancia se cancela: el orden de los
ejercicios y el balance entre el Sensor A y el Sensor B.

**Una advertencia de fisiología**, porque afecta a qué se le llama progreso:
la amplitud del sEMG a una carga absoluta fija tiende a BAJAR con la
adaptación neural, porque el músculo necesita reclutar menos para mover lo
mismo. Interpretar "subió la activación" como progreso puede estar al revés.
Los indicadores defendibles de progreso son el peso que mueve (que no sale de
los sensores), la resistencia a la fatiga (la pendiente de la frecuencia
mediana aplanándose) y la corrección del desbalance A/B.

Los números de repetibilidad usados son de la literatura, no medidos con este
hardware. El módulo imprime el protocolo para medirlos con los MYOblue, que es
una tarde de trabajo y convierte todo lo anterior en números propios.

**Nota sobre XGBoost y LightGBM.** Los dos se importan dentro de
`FatigueGradientBooster.__init__()` y no arriba del módulo, a propósito. Traen
librerías nativas que pueden fallar al cargar aunque el paquete de Python esté
instalado: en macOS, LightGBM necesita `libomp.dylib`, que no viene con el
sistema. Con el import a nivel de módulo ese error se propagaba a
`ml/__init__.py` y de ahí a cualquiera que tocara el paquete `ml`, así que una
dependencia opcional y todavía sin entrenar tumbaba la aplicación entera. Con
el import tardío, el error aparece solo si alguien pide explícitamente uno de
esos modelos, y `fatigue_trend_from_reps()`, que es lo único que se usa hoy,
funciona con numpy y no necesita ninguno de los dos.

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
`ClientCard`, `ActionTile`, `DataChip`, `Pill`, `IconBadge`, `Avatar`,
`BackButton`, `PageHeader`, `SectionTitle`, `EmptyState`, `Sparkline`,
`ScoreRing`, `MeterBar`, `ActivityChart` y `StepProgressBar`.

**Una función que conviene conocer: `clear_layout()`.** Vaciar un layout con
`takeAt()` y `deleteLater()` no basta, porque `deleteLater()` solo agenda el
borrado para cuando el bucle de eventos vuelva a tener el control. Mientras
tanto el widget sigue siendo hijo de su contenedor y se sigue dibujando en la
última posición que tuvo, ya sin layout que lo acomode. Al reconstruir una
lista en el mismo turno, como el historial de un cliente al abrir su perfil,
eso hacía que las filas viejas quedaran encimadas sobre las nuevas.
`clear_layout()` le quita el padre al widget primero, que es lo que lo saca de
la pantalla en ese instante. Todas las pantallas que reconstruyen listas la
usan.

El tema se aplica llamando a `apply_app_theme()` al arrancar la aplicación,
antes de construir cualquier ventana. El orden importa: si se aplicara
únicamente dentro de la ventana principal, las pantallas de login y registro
se mostrarían con el tema claro.

---

## 11. Pruebas

```bash
uv run pytest tests/ -v
```

Actualmente hay **155 pruebas** que cubren las partes donde un error sería
difícil de detectar a simple vista:

- **Protocolo binario** (`test_protocol.py`): paquetes válidos, paquetes
  corruptos, resincronización del flujo y manejo de datos parciales.
- **Filtros y pipeline DSP** (`test_filters.py`, `test_channel.py`): que el
  pasa-banda atenúe lo que está fuera de la banda y deje pasar lo que está
  dentro, que el notch elimine la frecuencia objetivo sin afectar a las demás,
  que la envolvente suavice y nunca sea negativa, y que el RMS dé cero en
  silencio y el valor correcto en una señal conocida.
- **Validez de la señal** (`test_signal_quality.py`): detección de electrodo
  despegado y umbral de repeticiones relativo al MVC. Incluye tres pruebas de
  regresión contra señal real grabada del MYOblue, guardada en `tests/data/`:
  reposo con buen contacto, contracción máxima y electrodo despegado. De esas
  capturas salieron los umbrales, así que si alguien los mueve, estas pruebas
  lo detectan.
- **Datos del cliente y borrado** (`test_client_data.py`): cálculo del índice
  de masa corporal, distinción entre dato faltante y cero, migración de una
  base con el esquema anterior (incluido el corte del nombre completo en
  nombre y apellidos), y que borrar una evaluación o un cliente no deje
  registros huérfanos en SQLite ni señal huérfana en DuckDB.
- **Composición corporal** (`test_body_composition.py`): las fórmulas de
  Deurenberg y de la Marina, el orden de preferencia entre las tres fuentes de
  grasa corporal, y las clasificaciones por sexo. La clase `TestColinealidad`
  demuestra con números por qué la estimación de Deurenberg no puede tratarse
  como una variable más: comprueba que tres cuerpos distintos reciben la misma
  estimación y que el valor se puede reconstruir exactamente a partir de IMC,
  edad y sexo.
- **Datos sintéticos y banco de pruebas** (`test_synthetic.py`): que los datos
  generados sean reproducibles y fisiológicamente coherentes, y sobre todo que
  tengan la propiedad que justifica todo el experimento, que las evaluaciones
  del mismo cliente se parezcan entre sí. También comprueba que el banco
  detecte la fuga por cliente: si los modelos de árboles no se vieran mucho
  mejor con la partición al azar, el banco no estaría midiendo lo que dice.
- **Batería de ejercicios** (`test_battery.py`): el coeficiente de variación
  que la app le muestra al entrenador, que es con el que decide si dos
  ejercicios de verdad se diferencian. Incluye que use la desviación muestral
  y no la poblacional, porque con tres o cuatro mediciones dividir entre n en
  vez de entre n-1 subestima la dispersión y haría ver la medición más
  confiable de lo que es.
- **Diseño intra-sujeto** (`test_within_subject.py`): que la simulación se
  comporte como un experimento de medición repetida (más ruido empeora, más
  mediciones mejoran, el error baja con la raíz del número de mediciones), y
  deja fijados los dos hallazgos que cambian el producto: que el top 3 aguanta
  mucho mejor que el top 1, y que con electrodos re-colocados una mejora real
  del 10% casi no se detecta.

Salvo las tres de regresión contra hardware, las pruebas se hacen con señales
sintéticas generadas dentro del propio test, verificando el resultado numérico
y no solamente que el código corra.

La interfaz gráfica no tiene pruebas automatizadas todavía. Lo que sí se probó
a mano, contra la aplicación corriendo, fue la navegación hacia atrás del
asistente (que no acumule evaluaciones vacías) y el borrado en cascada.

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
| Gestión de clientes | Completo, con ficha física y edición de todos los campos |
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

**Validado con hardware real:** el enlace con el receptor, el parser del
protocolo y el pipeline DSP completo se probaron contra un MYOblue v1.2 con
sensores colocados sobre un músculo. Resultados: 0% de pérdida de paquetes,
frecuencia de muestreo real entre 982 y 1006 Hz frente a los 1000 Hz que
asume el código, y una separación de unas 400 veces entre el reposo (2.5 µV
RMS) y la contracción (más de 1000 µV RMS). Las señales de esa sesión quedaron
guardadas en `tests/data/` como pruebas de regresión.

**Pendientes conocidos:**

- El asistente de evaluación todavía no se ha recorrido completo contra
  hardware real desde la interfaz. Lo validado hasta ahora es la capa de
  sensores y el procesamiento de señal.
- No hay pruebas automatizadas de la interfaz gráfica.
- No existe una pantalla de configuración para ajustar parámetros de los
  filtros (frecuencia del notch, límites de la banda), que hoy se cambian en
  el código.
- La app llama a los sensores "A" y "B", y los sensores físicos no vienen
  marcados. El paso 3 del asistente ya ayuda a resolverlo de forma indirecta:
  como muestra la señal de cada uno en vivo, darle un golpecito a un sensor
  hace que se mueva su trazo y así se sabe cuál es. Sigue faltando algo más
  directo, por ejemplo un botón que resalte en pantalla el sensor que se está
  tocando, y poder ponerles una etiqueta que se guarde.

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
