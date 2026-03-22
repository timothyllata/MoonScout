"""
train.py — Generate synthetic training data and train the MoonScout XGBoost model.

Synthetic data is built from known Solana rug-pull patterns:
  - Rugs (label=0): high rug_score, unlocked LP, concentrated holders, active authorities
  - Good tokens (label=1): low rug_score, locked LP, spread holders, no authorities

Run:
    python -m moonscout.ml.train

Produces: moonscout/ml/model.bst
The DegenScorer automatically activates XGBoost mode when this file exists.
"""

import logging
from pathlib import Path

import numpy as np
import xgboost as xgb
from sklearn.model_selection import cross_val_score
from sklearn.metrics import classification_report

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / "model.bst"

# Feature order must match scorer.py FEATURE_NAMES
FEATURES = ["rug_score", "lp_locked", "top_holder_pct", "freeze_authority", "mint_authority"]

rng = np.random.default_rng(42)


def _generate_rugs(n: int) -> np.ndarray:
    """Generate synthetic rug-pull token feature rows (label=0)."""
    rug_score      = rng.uniform(60, 100, n)          # high risk score
    lp_locked      = rng.choice([0.0, 1.0], n, p=[0.85, 0.15])  # mostly unlocked
    top_holder_pct = rng.uniform(30, 95, n)           # concentrated ownership
    freeze_auth    = rng.choice([0.0, 1.0], n, p=[0.3, 0.7])    # often active
    mint_auth      = rng.choice([0.0, 1.0], n, p=[0.4, 0.6])    # often active
    return np.column_stack([rug_score, lp_locked, top_holder_pct, freeze_auth, mint_auth])


def _generate_good(n: int) -> np.ndarray:
    """Generate synthetic legitimate token feature rows (label=1)."""
    rug_score      = rng.uniform(0, 35, n)            # low risk score
    lp_locked      = rng.choice([0.0, 1.0], n, p=[0.2, 0.8])   # mostly locked
    top_holder_pct = rng.uniform(2, 30, n)            # spread distribution
    freeze_auth    = rng.choice([0.0, 1.0], n, p=[0.9, 0.1])   # rarely active
    mint_auth      = rng.choice([0.0, 1.0], n, p=[0.85, 0.15]) # rarely active
    return np.column_stack([rug_score, lp_locked, top_holder_pct, freeze_auth, mint_auth])


def _generate_borderline(n: int) -> np.ndarray:
    """Generate ambiguous tokens (mixed signals) — split evenly between labels."""
    rug_score      = rng.uniform(30, 65, n)
    lp_locked      = rng.choice([0.0, 1.0], n, p=[0.5, 0.5])
    top_holder_pct = rng.uniform(15, 55, n)
    freeze_auth    = rng.choice([0.0, 1.0], n, p=[0.6, 0.4])
    mint_auth      = rng.choice([0.0, 1.0], n, p=[0.65, 0.35])
    return np.column_stack([rug_score, lp_locked, top_holder_pct, freeze_auth, mint_auth])


def generate_dataset(n_rugs: int = 1200, n_good: int = 800, n_border: int = 500):
    """
    Build a synthetic dataset with realistic class imbalance.
    Solana tokens skew heavily toward rugs (~60-70% in the wild).
    """
    X_rugs   = _generate_rugs(n_rugs)
    X_good   = _generate_good(n_good)
    X_border = _generate_borderline(n_border)

    # Borderline: first half are rugs, second half are good
    half = n_border // 2
    y_rugs   = np.zeros(n_rugs)
    y_good   = np.ones(n_good)
    y_border = np.concatenate([np.zeros(half), np.ones(n_border - half)])

    X = np.vstack([X_rugs, X_good, X_border]).astype(np.float32)
    y = np.concatenate([y_rugs, y_good, y_border]).astype(np.float32)

    # Shuffle
    idx = rng.permutation(len(X))
    return X[idx], y[idx]


def train():
    logger.info("Generating synthetic training data...")
    X, y = generate_dataset()
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    logger.info("Dataset: %d total (%d rugs / %d good)", len(X), n_neg, n_pos)

    # Class imbalance correction — upweight the minority class (good tokens)
    scale_pos_weight = n_neg / n_pos
    logger.info("scale_pos_weight: %.2f", scale_pos_weight)

    # --- Train/test split (80/20) -----------------------------------------
    split = int(0.8 * len(X))
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURES)
    dtest  = xgb.DMatrix(X_test,  label=y_test,  feature_names=FEATURES)

    params = {
        "objective":        "binary:logistic",
        "eval_metric":      ["logloss", "auc"],
        "max_depth":        4,
        "learning_rate":    0.1,
        "n_estimators":     200,
        "min_child_weight": 5,
        "subsample":        0.8,
        "colsample_bytree": 0.8,
        "scale_pos_weight": scale_pos_weight,
        "seed":             42,
    }

    logger.info("Training XGBoost model...")
    evals_result: dict = {}
    model = xgb.train(
        params,
        dtrain,
        num_boost_round=200,
        evals=[(dtrain, "train"), (dtest, "test")],
        evals_result=evals_result,
        verbose_eval=50,
    )

    # --- Evaluation -------------------------------------------------------
    preds_prob = model.predict(dtest)
    preds_bin  = (preds_prob >= 0.5).astype(int)

    final_auc = evals_result["test"]["auc"][-1]
    logger.info("\nTest AUC: %.4f", final_auc)
    logger.info("\nClassification Report:\n%s",
                classification_report(y_test, preds_bin, target_names=["rug", "good"]))

    # --- Feature importance -----------------------------------------------
    importance = model.get_score(importance_type="gain")
    logger.info("Feature importance (gain):")
    for feat, score in sorted(importance.items(), key=lambda x: -x[1]):
        logger.info("  %-20s %.2f", feat, score)

    # --- Save model -------------------------------------------------------
    model.save_model(str(MODEL_PATH))
    logger.info("\nModel saved to %s", MODEL_PATH)
    logger.info("DegenScorer will automatically use XGBoost mode on next startup.")


if __name__ == "__main__":
    train()
