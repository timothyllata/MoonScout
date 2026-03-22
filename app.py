from flask import Flask, jsonify, render_template
from pymongo import MongoClient, DESCENDING
from moonscout.config import settings
import logging

logger = logging.getLogger(__name__)
app = Flask(__name__)

_mongo_client = MongoClient(
    settings.mongodb_connection_uri,
    tls=True,
    tlsAllowInvalidCertificates=True,  # dev only — don't use in production
)

_db = _mongo_client["moonscout"]


def _serialize_doc(doc: dict) -> dict:
    rug = doc.get("rug_check", {})
    discovery = doc.get("discovery", {})
    return {
        "mint_address":     doc.get("mint_address", ""),
        "symbol":           doc.get("symbol", "UNKNOWN"),
        "name":             doc.get("name", "Unknown Token"),
        "degen_score":      float(doc.get("degen_score", 0.0)),
        "rug_score":        float(rug.get("rug_score", 0.0)),
        "is_rug":           bool(rug.get("is_rug", False)),
        "lp_locked":        bool(rug.get("lp_locked", False)),
        "freeze_authority": bool(rug.get("freeze_authority", True)),
        "mint_authority":   bool(rug.get("mint_authority", True)),
        "top_holder_pct":   float(rug.get("top_holder_pct", 0.0)),
        "decimals":         int(discovery.get("decimals", 0)),
        "creator_address":  discovery.get("creator_address", ""),
        "created_at":       discovery.get("created_at", ""),
        "source":           discovery.get("source", ""),
        "supply":           float(discovery.get("supply", 0.0)),
        "scorer_mode":      doc.get("scorer_mode", "heuristic"),
        "broadcast_sent":   bool(doc.get("broadcast_sent", False)),
        "_id":              str(doc.get("_id", "")),
        "scored_at":        doc.get("scored_at").isoformat()
                            if doc.get("scored_at") else "",
    }


def _fetch_latest(limit: int = 50) -> list[dict]:
    docs = list(
        _db["token_intelligence"]
        .find({}, sort=[("scored_at", DESCENDING)], limit=limit)
    )
    return [_serialize_doc(d) for d in reversed(docs)]


def _fetch_since(since_id: str, limit: int = 20) -> list[dict]:
    from bson import ObjectId
    try:
        oid = ObjectId(since_id)
    except Exception:
        return _fetch_latest(limit)
    docs = list(
        _db["token_intelligence"]
        .find({"_id": {"$gt": oid}}, sort=[("scored_at", DESCENDING)], limit=limit)
    )
    return [_serialize_doc(d) for d in reversed(docs)]


@app.route("/")
def index():
    try:
        initial_coins = _fetch_latest(limit=50)
    except Exception:
        logger.exception("Failed to fetch initial coins from Atlas")
        initial_coins = []
    return render_template("index.html", initial_coins=initial_coins)


@app.route("/api/intelligence")
def get_intelligence():
    try:
        coins = _fetch_latest(limit=50)
        return jsonify({"coins": coins, "count": len(coins)})
    except Exception as exc:
        logger.exception("Failed to fetch intelligence from Atlas")
        return jsonify({"error": str(exc), "coins": [], "count": 0}), 500


@app.route("/api/intelligence/since/<string:since_id>")
def get_intelligence_since(since_id: str):
    try:
        coins = _fetch_since(since_id, limit=20)
        return jsonify({"coins": coins, "count": len(coins)})
    except Exception as exc:
        logger.exception("Failed to fetch intelligence since %s", since_id)
        return jsonify({"error": str(exc), "coins": [], "count": 0}), 500


if __name__ == "__main__":
    app.run(debug=True)