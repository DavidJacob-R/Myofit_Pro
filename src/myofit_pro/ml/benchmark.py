"""
Banco de pruebas de algoritmos sobre los datos sintéticos.

Compara varios modelos en las dos cosas que los sensores SÍ permiten
aprender, y deja los resultados en CSV para analizarlos aparte.

LOS DOS OBJETIVOS QUE SE PRUEBAN
================================

1. `fatigue_slope_hz_per_rep`
   Qué tan rápido se fatiga el cliente, medido como la caída de la
   frecuencia mediana repetición a repetición. Es el mejor objetivo para
   empezar porque la etiqueta sale sola de la señal: no hay que pedirle
   a nadie que clasifique nada a mano.

2. `mean_activation_pct`
   Cuánta activación produce un ejercicio concreto en un cliente
   concreto. Es el objetivo más valioso del producto: permite ordenar
   ejercicios por persona, que es justo lo que una tabla de rutinas no
   puede hacer.

LO QUE NO SE PRUEBA AQUÍ, A PROPÓSITO
=====================================

Series y repeticiones. No es un problema de predicción: no hay etiqueta
que aprender (habría que copiar lo que ya decidió un entrenador), y la
respuesta ya está establecida en la literatura de entrenamiento como
rangos por objetivo. Una tabla de reglas acierta desde el primer día, se
puede explicar al cliente y no necesita datos. Ver la nota al final de
la salida del programa.

LA TRAMPA METODOLÓGICA QUE ESTE ARCHIVO DEMUESTRA
=================================================

Un mismo cliente aporta varias evaluaciones, y esas evaluaciones se
parecen entre sí. Si se parte el conjunto al azar, el mismo cliente cae
en entrenamiento y en prueba: el modelo lo memoriza y reporta un
resultado excelente que se desploma con un cliente nuevo, que es el caso
que de verdad importa.

La partición correcta agrupa por `client_id` (GroupKFold). El programa
corre las dos y muestra la diferencia, porque es un error que se ve
bonito en un reporte y no sirve para nada.

USO
===

    uv run python -m myofit_pro.ml.synthetic --clientes 60 --salida datos/
    uv run python -m myofit_pro.ml.benchmark datos/
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

# Variables del cliente. Son las que la app ya captura.
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

TARGETS = {
    "fatigue_slope_hz_per_rep": "Fatigabilidad (Hz por repetición)",
    "mean_activation_pct": "Activación media (% del MVC)",
}


def _models() -> dict[str, object]:
    """
    Los candidatos, del más simple al más complejo.

    El orden importa. `Promedio` es el modelo que siempre predice la
    media: si un algoritmo no le gana, no está aprendiendo nada, y esa
    comparación es la que más se olvida.

    No hay redes neuronales en la lista. Con unos cientos de filas y
    ocho variables no tienen nada que aportar frente a un modelo lineal
    regularizado, y sí traen sobreajuste y una caja negra imposible de
    explicarle a un entrenador.
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
    error = y_true - y_pred
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(error**2)))
    ss_res = float(np.sum(error**2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"MAE": mae, "RMSE": rmse, "R2": r2}


def _prepare(df: pd.DataFrame, target: str) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Arma X, y y los grupos (client_id) para la validación."""
    data = df.copy()
    data["sex_male"] = (data["sex"] == "Masculino").astype(float)

    features = list(CLIENT_FEATURES)

    # Para predecir la activación hace falta saber de qué ejercicio se
    # habla. Se codifica one-hot y no como número: los ejercicios no
    # tienen orden, y numerarlos le diría al modelo que el ejercicio 3
    # está "entre" el 2 y el 4.
    if target == "mean_activation_pct":
        dummies = pd.get_dummies(data["exercise"], prefix="ej", dtype=float)
        data = pd.concat([data, dummies], axis=1)
        features += list(dummies.columns)

    X = data[features]
    y = data[target].to_numpy(dtype=float)
    groups = data["client_id"].to_numpy()
    return X, y, groups


def run_target(df: pd.DataFrame, target: str, folds: int = 5) -> pd.DataFrame:
    """Compara todos los modelos en un objetivo, con las dos particiones."""
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
    """
    Cómo mejora el mejor modelo conforme hay más clientes.

    Responde la pregunta que de verdad importa antes de invertir en
    esto: cuántos clientes hay que acumular antes de que el modelo valga
    más que predecir el promedio.
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
    """
    Coeficientes de Ridge, para compararlos con `verdad_base.json`.

    Si el modelo no recupera una relación que sabemos que está en los
    datos, tampoco va a encontrar la que esté en los datos reales.
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
    """
    Cuánta de la variación del objetivo está ENTRE clientes y cuánta
    DENTRO de cada cliente.

    Es el diagnóstico más útil antes de entrenar nada, y casi nadie lo
    hace. Las variables de la ficha (edad, peso, grasa, experiencia) son
    constantes dentro de un cliente, así que solo pueden explicar la
    parte que varía ENTRE clientes. Lo que varía de una evaluación a otra
    del mismo cliente es, por construcción, invisible para esas
    variables.

    Si el 70% de la variación es interna, el techo de cualquier modelo
    basado en la ficha es un R2 de 0.30, por bueno que sea el algoritmo.
    Saberlo evita perseguir un 0.8 que no existe.
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
    """
    Compara dos conjuntos de variables para mostrar el efecto de meter
    columnas que se derivan unas de otras.

    El IMC es peso entre estatura al cuadrado, así que dar las tres al
    mismo tiempo es dar la misma información dos veces. El resultado
    típico son coeficientes grandes con signos alternados que se cancelan
    entre sí: el modelo predice parecido, pero los pesos ya no dicen
    nada sobre qué influye en qué.
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
    print(df.to_string(index=False))


def main() -> None:
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
