"""
scorer.py — Degen Score computation for NeuroScout.

Two-tier scoring strategy (user decision):

  Tier 1 — Weighted Heuristic (always available, zero cold-start)
    Runs immediately on any RugCheckResult with no model file needed.
    Used for demo/testing and as fallback when no trained model exists.

  Tier 2 — XGBoost Model (loads from ml/model.bst if present)
    Trained offline via ml/train.py on synthetic Solana token data.
    Returns a probability score mapped to 0–100.

DegenScorer.score() automatically uses Tier 2 when the model file exists,
otherwise falls back to Tier 1.  The caller never needs to know which tier
is active — the output is always a float in [0, 100].
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / "model.bst"

# Feature order must match the training script
FEATURE_NAMES = [
    "rug_score",
    "lp_locked",
    "top_holder_pct",
    "freeze_authority",
    "mint_authority",
]


# ---------------------------------------------------------------------------
# Tier 1 — Weighted Heuristic
# ---------------------------------------------------------------------------


def heuristic_score(
    rug_score: float,
    lp_locked: bool,
    top_holder_pct: float,
    freeze_authority: bool,
    mint_authority: bool,
    is_rug: bool,
) -> float:
    """
    Weighted heuristic producing a Degen Score (0–100).
    Higher = more degen-worthy (not a rug, locked LP, healthy distribution).

    Weights were chosen to reflect common Solana degen risk intuition:
      - rug_score contributes the most (RugCheck's own aggregate signal)
      - lp_locked is a strong positive signal
      - top_holder_pct penalises whale concentration
      - authority flags are red flags but not disqualifiers alone
    """
    score = 100.0

    # rug_score is 0–100 where 100 = definite rug; scale penalty accordingly
    score -= rug_score * 0.40          # max -40 points

    if not lp_locked:
        score -= 20.0                  # unlocked LP is a significant red flag

    if top_holder_pct > 50.0:
        score -= 20.0
    elif top_holder_pct > 30.0:
        score -= 10.0

    if freeze_authority:
        score -= 15.0

    if mint_authority:
        score -= 10.0

    if is_rug:
        score -= 30.0                  # hard penalty on confirmed rug call

    return max(0.0, min(100.0, score))


# ---------------------------------------------------------------------------
# Tier 2 — XGBoost wrapper
# ---------------------------------------------------------------------------


class DegenScorer:
    """
    Unified scorer: uses XGBoost model when available, heuristic otherwise.
    Instantiate once at agent startup and reuse — avoids repeated disk I/O.
    """

    def __init__(self) -> None:
        self._model = None
        self._using_model = False
        self._try_load_model()

    def _try_load_model(self) -> None:
        if not MODEL_PATH.exists():
            logger.info(
                "No model file at %s — using heuristic scorer. "
                "Run ml/train.py to generate a trained model.",
                MODEL_PATH,
            )
            return

        try:
            import xgboost as xgb  # lazy import — not needed for heuristic path

            model = xgb.Booster()
            model.load_model(str(MODEL_PATH))
            self._model = model
            self._using_model = True
            logger.info("XGBoost model loaded from %s", MODEL_PATH)
        except Exception:
            logger.exception("Failed to load XGBoost model — falling back to heuristic.")

    @property
    def mode(self) -> str:
        return "xgboost" if self._using_model else "heuristic"

    def score(
        self,
        rug_score: float,
        lp_locked: bool,
        top_holder_pct: float,
        freeze_authority: bool,
        mint_authority: bool,
        is_rug: bool,
    ) -> float:
        """Return Degen Score in [0, 100]. Higher = more degen-worthy."""
        if self._using_model:
            return self._score_xgboost(
                rug_score, lp_locked, top_holder_pct, freeze_authority, mint_authority
            )
        return heuristic_score(
            rug_score, lp_locked, top_holder_pct, freeze_authority, mint_authority, is_rug
        )

    def _score_xgboost(
        self,
        rug_score: float,
        lp_locked: bool,
        top_holder_pct: float,
        freeze_authority: bool,
        mint_authority: bool,
    ) -> float:
        try:
            import numpy as np
            import xgboost as xgb

            features = np.array([[
                rug_score,
                1.0 if lp_locked else 0.0,
                top_holder_pct,
                1.0 if freeze_authority else 0.0,
                1.0 if mint_authority else 0.0,
            ]], dtype=np.float32)

            # Omit feature_names from DMatrix in xgboost 3.x — pass it at
            # training time instead.  Setting it here can cause a hard error if
            # the booster was trained without feature names.
            dmatrix = xgb.DMatrix(features)
            raw = float(self._model.predict(dmatrix)[0])
            # Model outputs probability [0, 1] — map to [0, 100]
            return min(100.0, max(0.0, raw * 100.0))
        except Exception:
            logger.exception("XGBoost inference failed — falling back to heuristic.")
            return heuristic_score(
                rug_score, lp_locked, top_holder_pct, freeze_authority, mint_authority, False
            )
