"""Banco de pruebas de algoritmos sobre los datos sintéticos.

Posición en el flujo
--------------------
Fuera del flujo de la aplicación. Consume el conjunto de datos que produce
`myofit_pro.ml.synthetic` y escribe sus resultados en CSV. Su función es
decidir, antes de acumular historial real, qué familia de algoritmos tiene
sentido y cuántos clientes hacen falta para que aporte algo.

Objetivos evaluados
-------------------
``fatigue_slope_hz_per_rep``
    Velocidad de fatiga del cliente, medida como la caída de la frecuencia
    mediana repetición a repetición. Es el objetivo por el que conviene
    empezar porque la etiqueta se obtiene de la propia señal, sin
    anotación manual.

``mean_activation_pct``
    Activación que un ejercicio concreto produce en un cliente concreto.
    Es el objetivo de mayor valor para el producto: permite ordenar
    ejercicios por persona, que es justamente lo que una tabla de rutinas
    no puede hacer.

Fuera de alcance por decisión de diseño
---------------------------------------
Series y repeticiones no se tratan como un problema de predicción. No hay
etiqueta que aprender —habría que reproducir lo que ya decidió un
entrenador— y los rangos por objetivo están establecidos en la literatura
de entrenamiento. Una tabla de reglas acierta desde el primer día, se
puede explicar al cliente y no necesita datos. Esa tabla es
`myofit_pro.routine_engine.GOAL_SCHEMES`.

Sesgo metodológico que este módulo demuestra
--------------------------------------------
Un mismo cliente aporta varias evaluaciones, y esas evaluaciones se
parecen entre sí. Si el conjunto se particiona al azar, el mismo cliente
aparece en entrenamiento y en prueba: el modelo memoriza su nivel
individual y produce una métrica excelente que se desploma ante un cliente
nuevo, que es el caso de uso real.

La partición correcta agrupa por ``client_id``
(`sklearn.model_selection.GroupKFold`). Este módulo ejecuta ambas y
cuantifica la diferencia, porque la partición incorrecta produce cifras
atractivas y sin valor.

Uso
---
::

    uv run python -m myofit_pro.ml.synthetic --clientes 60 --salida datos/
    uv run python -m myofit_pro.ml.benchmark datos/

See Also
--------
myofit_pro.ml.synthetic : Generador del conjunto de datos.
myofit_pro.ml.within_subject : Análisis del diseño intra-sujeto.

References
----------
.. [1] Varoquaux, G. et al. (2017). "Assessing and tuning brain decoders:
       cross-validation, caveats, and guidelines". *NeuroImage*, 145,
       166-179.
.. [2] Roberts, D. R. et al. (2017). "Cross-validation strategies for
       data with temporal, spatial, hierarchical, or phylogenetic
       structure". *Ecography*, 40(8), 913-929.
.. [3] Pedregosa, F. et al. (2011). "Scikit-learn: Machine Learning in
       Python". *Journal of Machine Learning Research*, 12, 2825-2830.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.model_selection import GroupKFold, KFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

#: Predictores procedentes de la ficha del cliente. Son constantes dentro
#: de un cliente, lo que limita su capacidad explicativa a la varianza
#: entre clientes (ver `variance_split`).
CLIENT_FEATURES = [
    "age_years",
    "height_cm",
    "weight_kg",
    "bmi",
    "body_fat_pct",
    "experience_num",
    "days_per_week",
    "sex_male",
]

#: Variables objetivo evaluadas, con su descripción para los informes.
TARGETS = {
    "fatigue_slope_hz_per_rep": "Fatigabilidad (Hz por repetición)",
    "mean_activation_pct": "Activación media (% del MVC)",
}


def _models() -> dict[str, object]:
    """Construye los modelos candidatos, del más simple al más complejo.

    Returns
    -------
    dict of str to object
        Estimadores compatibles con scikit-learn, indexados por nombre.

    Notes
    -----
    El primer candidato es `sklearn.dummy.DummyRegressor`, que predice
    siempre la media. Es la línea base obligada: un algoritmo que no la
    supere no está aprendiendo nada, por buenas que parezcan sus
    métricas en términos absolutos.

    No se incluyen redes neuronales. Con unos cientos de observaciones y
    ocho predictores no aportan nada frente a un modelo lineal
    regularizado, y sí añaden sobreajuste y falta de interpretabilidad,
    que en este producto importa: el entrenador debe poder entender por
    qué se le propone un ejercicio.
    """
    return {
        "Promedio (línea base)": DummyRegressor(strategy="mean"),
        "Ridge": Pipeline(
            [("escala", StandardScaler()), ("modelo", Ridge(alpha=1.0))]
        ),
        "ElasticNet": Pipeline(
            [("escala", StandardScaler()), ("modelo", ElasticNet(alpha=0.05, l1_ratio=0.5))]
        ),
        "Random Forest": RandomForestRegressor(
            n_estimators=300, min_samples_leaf=4, random_state=42, n_jobs=-1
        ),
        "Gradient Boosting": GradientBoostingRegressor(
            n_estimators=200, max_depth=3, learning_rate=0.05, random_state=42
        ),
    }


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Calcula error absoluto medio, error cuadrático medio y R²."""
    error = y_true - y_pred
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(error**2)))
    ss_res = float(np.sum(error**2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"MAE": mae, "RMSE": rmse, "R2": r2}


def _prepare(df: pd.DataFrame, target: str) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Construye la matriz de diseño, el objetivo y los grupos.

    Parameters
    ----------
    df : pandas.DataFrame
        Tabla unida de clientes y evaluaciones.
    target : str
        Nombre de la columna objetivo, una clave de `TARGETS`.

    Returns
    -------
    X : pandas.DataFrame
        Matriz de diseño.
    y : numpy.ndarray
        Vector objetivo.
    groups : numpy.ndarray
        Identificador de cliente de cada fila, para
        `sklearn.model_selection.GroupKFold`.

    Notes
    -----
    Para el objetivo de activación se añade el ejercicio codificado como
    variables indicadoras. La codificación disyuntiva es obligada: los
    ejercicios carecen de orden, y numerarlos informaría al modelo de
    que el ejercicio 3 se sitúa entre el 2 y el 4.
    """
    data = df.copy()
    data["sex_male"] = (data["sex"] == "Masculino").astype(float)

    features = list(CLIENT_FEATURES)

    if target == "mean_activation_pct":
        dummies = pd.get_dummies(data["exercise"], prefix="ej", dtype=float)
        data = pd.concat([data, dummies], axis=1)
        features += list(dummies.columns)

    X = data[features]
    y = data[target].to_numpy(dtype=float)
    groups = data["client_id"].to_numpy()
    return X, y, groups


def run_target(df: pd.DataFrame, target: str, folds: int = 5) -> pd.DataFrame:
    """Compara todos los modelos en un objetivo, con ambas particiones.

    Parameters
    ----------
    df : pandas.DataFrame
        Tabla unida de clientes y evaluaciones.
    target : str
        Columna objetivo.
    folds : int, default=5
        Particiones de la validación cruzada.

    Returns
    -------
    pandas.DataFrame
        Una fila por modelo, con el error absoluto medio y el R² bajo
        partición por cliente, el R² bajo partición aleatoria y la
        diferencia entre ambos, que cuantifica la fuga de información.
    """
    X, y, groups = _prepare(df, target)
    rows = []

    grouped = GroupKFold(n_splits=folds)
    naive = KFold(n_splits=folds, shuffle=True, random_state=42)

    for name, model in _models().items():
        correcto = cross_val_predict(model, X, y, cv=grouped.split(X, y, groups))
        con_fuga = cross_val_predict(model, X, y, cv=naive)

        m_ok = _metrics(y, correcto)
        m_leak = _metrics(y, con_fuga)

        rows.append(
            {
                "objetivo": target,
                "modelo": name,
                "MAE": round(m_ok["MAE"], 3),
                "RMSE": round(m_ok["RMSE"], 3),
                "R2_por_cliente": round(m_ok["R2"], 3),
                "R2_particion_ingenua": round(m_leak["R2"], 3),
                "inflado_por_fuga": round(m_leak["R2"] - m_ok["R2"], 3),
            }
        )

    return pd.DataFrame(rows)


def learning_curve(df: pd.DataFrame, target: str, folds: int = 5) -> pd.DataFrame:
    """Calcula la curva de aprendizaje frente al número de clientes.

    Parameters
    ----------
    df : pandas.DataFrame
        Tabla unida de clientes y evaluaciones.
    target : str
        Columna objetivo.
    folds : int, default=5
        Particiones de la validación cruzada.

    Returns
    -------
    pandas.DataFrame
        Una fila por combinación de tamaño de muestra y modelo, con su
        error absoluto medio y su R².

    Notes
    -----
    Responde a la pregunta operativa previa a cualquier inversión en
    modelado: cuántos clientes hay que acumular para que un modelo
    supere a la predicción por la media. Los subconjuntos son anidados,
    tomando siempre los primeros clientes por identificador, de modo que
    cada tamaño incluya al anterior.
    """
    all_clients = np.array(sorted(df["client_id"].unique()))
    rows = []

    for n in (10, 20, 30, 45, 60, 80, 100):
        if n > len(all_clients):
            continue
        subset = df[df["client_id"].isin(all_clients[:n])]
        X, y, groups = _prepare(subset, target)

        if len(np.unique(groups)) < folds:
            continue

        splitter = GroupKFold(n_splits=folds)
        for name in ("Promedio (línea base)", "Ridge", "Gradient Boosting"):
            model = _models()[name]
            pred = cross_val_predict(model, X, y, cv=splitter.split(X, y, groups))
            m = _metrics(y, pred)
            rows.append(
                {
                    "objetivo": target,
                    "clientes": n,
                    "evaluaciones": len(subset),
                    "modelo": name,
                    "MAE": round(m["MAE"], 3),
                    "R2": round(m["R2"], 3),
                }
            )

    return pd.DataFrame(rows)


def coefficients(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Ajusta una regresión de Ridge y devuelve sus coeficientes.

    Parameters
    ----------
    df : pandas.DataFrame
        Tabla unida de clientes y evaluaciones.
    target : str
        Columna objetivo.

    Returns
    -------
    pandas.DataFrame
        Coeficientes estandarizados, ordenados por magnitud
        descendente.

    Notes
    -----
    Los coeficientes se comparan con los de ``verdad_base.json``, que
    contiene los valores empleados en la generación. Un modelo incapaz
    de recuperar una relación presente por construcción tampoco
    encontrará las que pueda haber en los datos reales.

    Los predictores se estandarizan previamente, de modo que los
    coeficientes sean comparables entre sí pese a estar medidos en
    unidades distintas.
    """
    X, y, _ = _prepare(df, target)
    model = Pipeline([("escala", StandardScaler()), ("modelo", Ridge(alpha=1.0))])
    model.fit(X, y)

    coefs = model.named_steps["modelo"].coef_
    return (
        pd.DataFrame({"variable": X.columns, "coeficiente_estandarizado": coefs.round(3)})
        .assign(magnitud=lambda d: d["coeficiente_estandarizado"].abs())
        .sort_values("magnitud", ascending=False)
        .drop(columns="magnitud")
        .reset_index(drop=True)
    )


def variance_split(df: pd.DataFrame, target: str) -> dict[str, float]:
    """Descompone la varianza del objetivo en sus componentes entre y dentro.

    Parameters
    ----------
    df : pandas.DataFrame
        Tabla unida de clientes y evaluaciones.
    target : str
        Columna objetivo.

    Returns
    -------
    dict of str to float
        Proporción de varianza entre clientes, proporción dentro de cada
        cliente, y el techo teórico de R² para un modelo basado en la
        ficha, que coincide con la primera.

    Notes
    -----
    Es el diagnóstico que conviene ejecutar antes de entrenar nada. Los
    predictores de la ficha —edad, peso, grasa, experiencia— son
    constantes dentro de un cliente, por lo que solo pueden explicar la
    componente entre clientes. Lo que varía de una evaluación a otra del
    mismo cliente les resulta invisible por construcción.

    Si el 70 % de la varianza es intra-cliente, el techo de cualquier
    modelo basado en la ficha es un R² de 0,30, con independencia del
    algoritmo. Conocer ese techo evita perseguir una métrica inalcanzable
    y orienta hacia el diseño intra-sujeto que analiza
    `myofit_pro.ml.within_subject`.
    """
    overall = df[target].mean()
    between = 0.0
    within = 0.0

    for _, group in df.groupby("client_id"):
        values = group[target].to_numpy(dtype=float)
        between += len(values) * (values.mean() - overall) ** 2
        within += float(np.sum((values - values.mean()) ** 2))

    total = between + within
    if total == 0:
        return {"entre_clientes": 0.0, "dentro_del_cliente": 0.0, "techo_r2": 0.0}

    share = between / total
    return {
        "entre_clientes": share,
        "dentro_del_cliente": 1.0 - share,
        "techo_r2": share,
    }


def collinearity_check(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Cuantifica el efecto de incluir predictores colineales.

    Parameters
    ----------
    df : pandas.DataFrame
        Tabla unida de clientes y evaluaciones.
    target : str
        Columna objetivo.

    Returns
    -------
    pandas.DataFrame
        Una fila por conjunto de predictores, con su error, su R² y dos
        indicadores de inestabilidad: el coeficiente de mayor magnitud y
        la suma de magnitudes.

    Notes
    -----
    El índice de masa corporal es el peso dividido por el cuadrado de la
    estatura, de modo que incluir las tres variables aporta la misma
    información dos veces. El efecto característico son coeficientes de
    gran magnitud y signos alternos que se compensan entre sí: la
    capacidad predictiva apenas varía, pero los coeficientes dejan de ser
    interpretables como contribución de cada variable.
    """
    rows = []
    sets = {
        "estatura + peso + IMC + grasa": [
            "height_cm", "weight_kg", "bmi", "body_fat_pct",
            "age_years", "experience_num", "days_per_week", "sex_male",
        ],
        "IMC + grasa (sin duplicar)": [
            "bmi", "body_fat_pct",
            "age_years", "experience_num", "days_per_week", "sex_male",
        ],
    }

    data = df.copy()
    data["sex_male"] = (data["sex"] == "Masculino").astype(float)
    y = data[target].to_numpy(dtype=float)
    groups = data["client_id"].to_numpy()

    for name, features in sets.items():
        X = data[features]
        model = Pipeline([("escala", StandardScaler()), ("modelo", Ridge(alpha=1.0))])
        pred = cross_val_predict(model, X, y, cv=GroupKFold(n_splits=5).split(X, y, groups))
        metrics = _metrics(y, pred)

        model.fit(X, y)
        coefs = model.named_steps["modelo"].coef_
        rows.append(
            {
                "conjunto": name,
                "variables": len(features),
                "MAE": round(metrics["MAE"], 3),
                "R2_por_cliente": round(metrics["R2"], 3),
                "coef_mas_grande": round(float(np.max(np.abs(coefs))), 2),
                "suma_abs_coefs": round(float(np.sum(np.abs(coefs))), 2),
            }
        )

    return pd.DataFrame(rows)


def _print_table(df: pd.DataFrame) -> None:
    """Imprime una tabla sin la columna de índice."""
    print(df.to_string(index=False))


def main() -> None:
    """Ejecuta el banco de pruebas completo e imprime y guarda sus tablas."""
    parser = argparse.ArgumentParser(
        description="Compara algoritmos de predicción sobre los datos sintéticos."
    )
    parser.add_argument("datos", type=Path, help="carpeta generada por myofit_pro.ml.synthetic")
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()

    dataset_path = args.datos / "dataset.csv"
    if not dataset_path.exists():
        raise SystemExit(
            f"No encontré {dataset_path}.\n"
            "Genera los datos primero:\n"
            "  uv run python -m myofit_pro.ml.synthetic --salida " + str(args.datos)
        )

    df = pd.read_csv(dataset_path)
    print(f"Dataset: {len(df)} evaluaciones de {df['client_id'].nunique()} clientes\n")

    comparisons = []
    curves = []

    for target, label in TARGETS.items():
        print("=" * 78)
        print(f"OBJETIVO: {label}")
        print(f"          columna `{target}`")
        print("=" * 78)

        split = variance_split(df, target)
        print(
            f"\n  Dónde está la variación:\n"
            f"    entre clientes distintos   {split['entre_clientes'] * 100:5.1f}%\n"
            f"    entre evaluaciones del      \n"
            f"    mismo cliente              {split['dentro_del_cliente'] * 100:5.1f}%\n"
            f"\n  Techo teórico usando solo datos de la ficha: R2 = {split['techo_r2']:.2f}\n"
            f"  (la ficha es constante dentro de un cliente, así que no puede\n"
            f"   explicar lo que cambia de una evaluación suya a otra)\n"
        )

        result = run_target(df, target, args.folds)
        comparisons.append(result)
        _print_table(result)

        baseline = result.loc[result["modelo"] == "Promedio (línea base)", "MAE"].iloc[0]
        best = result.loc[result["MAE"].idxmin()]
        mejora = (1 - best["MAE"] / baseline) * 100
        print(
            f"\n  Mejor: {best['modelo']}  "
            f"(MAE {best['MAE']} contra {baseline} del promedio, "
            f"{mejora:.0f}% mejor)"
        )

        inflado = result["inflado_por_fuga"].max()
        print(
            f"  Fuga por cliente: la partición ingenua infla el R2 hasta "
            f"{inflado:+.3f} puntos. Por eso se valida agrupando por cliente."
        )

        print("\n  Peso de cada variable según Ridge (estandarizado):")
        coefs = coefficients(df, target)
        _print_table(coefs.head(8))

        print("\n  Qué pasa al meter variables derivadas unas de otras:")
        _print_table(collinearity_check(df, target))

        curve = learning_curve(df, target, args.folds)
        curves.append(curve)
        print("\n  Cuántos clientes hacen falta:")
        pivot = curve.pivot_table(
            index=["clientes", "evaluaciones"], columns="modelo", values="MAE"
        )
        _print_table(pivot.reset_index())
        print()

    out = args.datos / "resultados"
    out.mkdir(exist_ok=True)
    pd.concat(comparisons).to_csv(out / "comparacion_modelos.csv", index=False)
    pd.concat(curves).to_csv(out / "curva_aprendizaje.csv", index=False)
    for target in TARGETS:
        coefficients(df, target).to_csv(out / f"coeficientes_{target}.csv", index=False)

    truth_path = args.datos / "verdad_base.json"
    if truth_path.exists():
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        print("Coeficientes con los que se generaron los datos (verdad_base.json):")
        for key, value in truth.items():
            if isinstance(value, (int, float)):
                print(f"  {key:<34} {value}")
        print()

    print("=" * 78)
    print("QUÉ SIGNIFICAN ESTOS NÚMEROS Y QUÉ NO")
    print("=" * 78)
    print(
        "Estos datos salieron de fórmulas que escribimos nosotros. Que un modelo\n"
        "las recupere demuestra que la tubería y la validación están bien, no que\n"
        "la edad y la grasa corporal expliquen la fatiga en personas reales. Eso\n"
        "solo se sabe con los clientes del gimnasio.\n"
    )
    print(
        "Series y repeticiones no se predicen aquí a propósito: no hay etiqueta\n"
        "que aprender y los rangos por objetivo ya están establecidos. Una tabla\n"
        "acierta desde el primer día y se le puede explicar al cliente.\n"
    )
    print(f"Resultados en {out}/")


if __name__ == "__main__":
    main()
