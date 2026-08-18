"""Glossary — every metric, term and conversion the interface displays.

Written so that a reader who has not seen the code can tell, for any number on
screen, what it means, how it was produced and what it does not mean.
"""

from __future__ import annotations

from typing import Any

# --- where machine learning is actually doing the work -------------------
# The honest map of the application. If a feature is arithmetic or a lookup,
# it says so. Only entries marked ML involve a trained model.

ML_MAP: list[dict[str, Any]] = [
    {
        "feature": "Market estimate — price per sq.ft",
        "tab": "Market estimate",
        "method": "ML",
        "detail": (
            "A trained regression model predicts price per sq.ft from property "
            "and GIS features. This is the core machine-learning output of the "
            "project."
        ),
    },
    {
        "feature": "Prediction interval",
        "tab": "Market estimate",
        "method": "ML",
        "detail": (
            "Split conformal prediction calibrated on a held-out set. The width "
            "is learned from the model's own residuals, not assumed."
        ),
    },
    {
        "feature": "Overpricing verdict",
        "tab": "Investment Score",
        "method": "ML",
        "detail": (
            "Compares an observed asking price against the model's prediction "
            "interval. Inherits the model, so it is an ML output."
        ),
    },
    {
        "feature": "Similar property recommendations",
        "tab": "Investment Score",
        "method": "ML",
        "detail": (
            "Unsupervised k-nearest neighbours fitted over the cleaned dataset "
            "in a standardised feature space."
        ),
    },
    {
        "feature": "Feature importance / SHAP",
        "tab": "ML Performance",
        "method": "ML",
        "detail": (
            "Permutation importance and SHAP values computed from the trained "
            "model on the held-out test split."
        ),
    },
    {
        "feature": "GIS distance features",
        "tab": "(feeds the model)",
        "method": "GIS",
        "detail": (
            "Distances to metro, hospital, school, government office and the "
            "amenity count within 1 km. Computed geometrically, then used as "
            "MODEL INPUTS — this is where GIS feeds machine learning."
        ),
    },
    {
        "feature": "Jurisdiction — corporation, ward, zone",
        "tab": "Jurisdiction",
        "method": "GIS",
        "detail": (
            "Point-in-polygon lookup against official ward boundaries. "
            "Deterministic geometry, no model involved."
        ),
    },
    {
        "feature": "Nearby facilities and distances",
        "tab": "Nearby & connectivity",
        "method": "GIS",
        "detail": "Nearest-neighbour search over OpenStreetMap features.",
    },
    {
        "feature": "Connectivity / healthcare / education scores",
        "tab": "Nearby & connectivity",
        "method": "SCORE",
        "detail": (
            "Weighted index over the distances above. A formula with stated "
            "weights — NOT machine learning."
        ),
    },
    {
        "feature": "Demand band",
        "tab": "Investment Score",
        "method": "SCORE",
        "detail": (
            "Weighted index. Neither dataset contains an observed demand label, "
            "so no supervised model can be trained or validated for it."
        ),
    },
    {
        "feature": "Risk band",
        "tab": "Investment Score",
        "method": "SCORE",
        "detail": (
            "Weighted index over proximity factors. No labelled risk outcome "
            "exists to train against."
        ),
    },
    {
        "feature": "Investment Score",
        "tab": "Investment Score",
        "method": "COMPOSITE",
        "detail": (
            "Combines one ML component (the value gap from the price model) "
            "with three data-driven scores. Part model, part formula."
        ),
    },
    {
        "feature": "BUILDER MODE financials",
        "tab": "BUILDER MODE",
        "method": "RULE",
        "detail": (
            "Deterministic arithmetic — cost, revenue, ROI, break-even. The "
            "only ML input is the expected selling price, taken from the price "
            "model."
        ),
    },
    {
        "feature": "Development feasibility",
        "tab": "Development feasibility",
        "method": "RULE",
        "detail": (
            "A cited rules engine over zoning regulations. Deliberately not ML: "
            "statutory limits are looked up, never predicted."
        ),
    },
]

METHOD_LEGEND = {
    "ML": "Trained machine-learning model",
    "GIS": "Geometric computation over spatial data",
    "SCORE": "Transparent weighted index (a formula, not a model)",
    "COMPOSITE": "Mix of ML output and weighted scores",
    "RULE": "Deterministic rules or arithmetic",
}


# --- terms ---------------------------------------------------------------

TERMS: list[dict[str, str]] = [
    # Evaluation metrics
    {"group": "Evaluation metric", "term": "MAE",
     "full": "Mean Absolute Error",
     "meaning": "Average size of the prediction error, in rupees per sq.ft.",
     "reading": "MAE of 1,357 means predictions are off by about ₹1,357/sq.ft on average.",
     "caution": "Treats a small and a large error alike."},

    {"group": "Evaluation metric", "term": "RMSE",
     "full": "Root Mean Squared Error",
     "meaning": "Like MAE but squares the errors first, so large misses count more.",
     "reading": "RMSE much larger than MAE means a few big errors dominate.",
     "caution": "Same unit as the target, but not an average error."},

    {"group": "Evaluation metric", "term": "R²",
     "full": "Coefficient of Determination",
     "meaning": "Share of the variation in price the model explains.",
     "reading": "0 = no better than always predicting the average. 1 = perfect.",
     "caution": "Can be NEGATIVE — worse than predicting the mean."},

    {"group": "Evaluation metric", "term": "MAPE",
     "full": "Mean Absolute Percentage Error",
     "meaning": "Average error as a percentage of the true value.",
     "reading": "MAPE 23% means predictions are typically 23% away from actual.",
     "caution": "Inflates when true values are small."},

    # Validation
    {"group": "Validation", "term": "Cross-validation",
     "full": "k-fold cross-validation",
     "meaning": "Split the data into k parts; train on k−1 and test on the held-out part, k times.",
     "reading": "The reported score is the average across folds.",
     "caution": "How you split matters enormously — see spatial-block CV."},

    {"group": "Validation", "term": "Random k-fold",
     "full": "Random cross-validation",
     "meaning": "Rows are shuffled and split at random.",
     "reading": "The score most projects report.",
     "caution": "On geographic data this puts a property and its neighbour on "
                "opposite sides of the split, inflating the score."},

    {"group": "Validation", "term": "Spatial-block CV",
     "full": "Grouped cross-validation by locality/ward",
     "meaning": "Whole localities are held out together, so the model must "
                "generalise to an area it has never seen.",
     "reading": "The honest score. Model selection in this project uses it.",
     "caution": "Always lower than random k-fold. That gap is the leakage."},

    {"group": "Validation", "term": "Data leakage",
     "full": "Information leaking from test into training",
     "meaning": "The model sees something at training time it would not have in reality.",
     "reading": "Measured here as random-CV R² minus spatial-CV R².",
     "caution": "Produces high scores that collapse on real, unseen areas."},

    {"group": "Validation", "term": "Target leakage",
     "full": "Using the target to predict itself",
     "meaning": "A feature computed from the target, e.g. total price when "
                "predicting price per sq.ft.",
     "reading": "The training pipeline fails outright if this is detected.",
     "caution": "Gives near-perfect scores that mean nothing."},

    {"group": "Validation", "term": "Train / Calibration / Test",
     "full": "Three-way data split",
     "meaning": "Train fits the model, calibration sets the interval width, "
                "test measures final performance.",
     "reading": "Test data is never used for fitting or tuning.",
     "caution": "A random test split shares any leakage the CV exposes."},

    # Prediction
    {"group": "Prediction", "term": "Conformal interval",
     "full": "Split conformal prediction",
     "meaning": "A prediction range built from the model's actual errors on "
                "held-out data.",
     "reading": "A 90% interval should contain the true value ~90% of the time — "
                "and the app reports the measured coverage.",
     "caution": "Distribution-free: it assumes no bell curve."},

    {"group": "Prediction", "term": "Single model",
     "full": "Single-model prediction",
     "meaning": "One algorithm — the best on spatial-block CV — makes the prediction.",
     "reading": "Fastest, and SHAP maps to exactly one model.",
     "caution": "No cross-check against other algorithms."},

    {"group": "Prediction", "term": "Dual model",
     "full": "Dual-model prediction",
     "meaning": "The top two algorithms predict; results are averaged.",
     "reading": "The gap between them is reported as model disagreement.",
     "caution": "Averaging two similar models adds little."},

    {"group": "Prediction", "term": "Multi model",
     "full": "Multi-model ensemble",
     "meaning": "All trained algorithms predict; the mean is taken.",
     "reading": "Usually the steadiest, because independent errors partly cancel.",
     "caution": "Not automatically the most accurate; harder to explain."},

    {"group": "Prediction", "term": "Model disagreement",
     "full": "Spread across ensemble members",
     "meaning": "The range between the highest and lowest member prediction.",
     "reading": "Small spread = the algorithms agree. Large = treat with caution.",
     "caution": "Agreement is not correctness — models can be wrong together."},

    # Explainability
    {"group": "Explainability", "term": "SHAP",
     "full": "SHapley Additive exPlanations",
     "meaning": "Assigns each feature a contribution to a prediction, based on "
                "cooperative game theory.",
     "reading": "Larger mean |SHAP| means the feature moves predictions more.",
     "caution": "Shows the model's behaviour, not real-world causation."},

    {"group": "Explainability", "term": "Permutation importance",
     "full": "Permutation feature importance",
     "meaning": "Shuffle one feature and see how much performance drops.",
     "reading": "A bigger drop means the model relies on it more.",
     "caution": "Correlated features can share and mask importance."},

    # Data
    {"group": "Data", "term": "Asking vs sale price",
     "full": "Listing price vs recorded transaction price",
     "meaning": "Bengaluru's data is asking prices; Chennai's is recorded sale prices.",
     "reading": "Asking prices sit above what properties actually sell for.",
     "caution": "The two cities' targets are NOT directly comparable."},

    {"group": "Data", "term": "Price per sq.ft",
     "full": "Normalised price target",
     "meaning": "Total price divided by built-up area.",
     "reading": "Lets a 600 sq.ft flat and a 3,000 sq.ft house be compared.",
     "caution": "Larger properties often have a lower rate per sq.ft."},

    {"group": "Data", "term": "Skewness",
     "full": "Distribution asymmetry",
     "meaning": "How lopsided a distribution is.",
     "reading": "Positive skew: a long tail of expensive properties.",
     "caution": "With high skew the median describes the data better than the mean."},

    {"group": "Data", "term": "IQR outlier rule",
     "full": "1.5 × interquartile range",
     "meaning": "Values beyond 1.5 × (Q3 − Q1) outside the quartiles.",
     "reading": "A convention for flagging extremes.",
     "caution": "An outlier is not automatically an error."},

    {"group": "Data", "term": "One-hot encoding",
     "full": "Categorical to numeric conversion",
     "meaning": "Each category becomes its own 0/1 column.",
     "reading": "Needed because models take numbers, not text.",
     "caution": "High-cardinality columns create very many columns."},

    {"group": "Data", "term": "Imputation",
     "full": "Filling missing values",
     "meaning": "Missing numbers replaced by the column median here.",
     "reading": "Keeps rows usable instead of discarding them.",
     "caution": "An imputed value is an assumption, not an observation."},

    {"group": "Data", "term": "Standardisation",
     "full": "Z-score scaling",
     "meaning": "Rescales each feature to mean 0, standard deviation 1.",
     "reading": "Stops large-valued features dominating by unit alone.",
     "caution": "Fitted on training data only, then applied to test data."},

    # Units
    {"group": "Unit conversion", "term": "Lakh / Crore",
     "full": "Indian numbering",
     "meaning": "1 lakh = 100,000. 1 crore = 100 lakh = 10,000,000.",
     "reading": "₹1.2 Cr = ₹1,20,00,000.",
     "caution": "The source dataset stores price in lakh; the app converts to rupees."},

    {"group": "Unit conversion", "term": "sq.ft / sq.m",
     "full": "Area units",
     "meaning": "1 sq.m = 10.764 sq.ft.",
     "reading": "Source areas appear in sq.ft, Perch, Cents, Guntha and Grounds; "
                "all are converted to sq.ft during cleaning.",
     "caution": "Unconverted units would silently corrupt the target."},

    {"group": "Unit conversion", "term": "Straight-line distance",
     "full": "Haversine (great-circle) distance",
     "meaning": "Shortest distance over the earth's surface, ignoring roads.",
     "reading": "All distances in the app are straight-line.",
     "caution": "Real travel distance is longer, sometimes much longer."},
]


def payload() -> dict[str, Any]:
    groups: dict[str, list[dict[str, str]]] = {}
    for t in TERMS:
        groups.setdefault(t["group"], []).append(t)
    return {
        "ml_map": ML_MAP,
        "method_legend": METHOD_LEGEND,
        "ml_feature_count": sum(1 for m in ML_MAP if m["method"] == "ML"),
        "terms": groups,
        "term_count": len(TERMS),
    }
