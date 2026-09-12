"""
server.py — thin Flask wrapper around pipeline.Pipeline.

Endpoints:
    GET  /                  -> serves the UI
    POST /ask   {"question": "..."} -> Result.to_dict()
    GET  /sample_questions   -> a few example questions from test_set.jsonl (one per category)
"""

import json
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).parent / "src"))
from pipeline import Pipeline  # noqa: E402

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"

app = Flask(__name__, static_folder=str(APP_DIR / "static"))
pipeline = Pipeline()


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/ask", methods=["POST"])
def ask():
    body = request.get_json(force=True)
    question = (body or {}).get("question", "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    result = pipeline.ask(question)
    return jsonify(result.to_dict())


@app.route("/sample_questions")
def sample_questions():
    test_set = [json.loads(l) for l in (DATA_DIR / "test_set.jsonl").read_text().splitlines() if l.strip()]
    picks = []
    for cat in ("answerable", "hard_negative", "contradiction"):
        cat_qs = [q for q in test_set if q["category"] == cat]
        picks.extend(cat_qs[:2])
    return jsonify([{"question": q["question"], "category": q["category"]} for q in picks])


if __name__ == "__main__":
    if pipeline.use_mock:
        print("!! WARNING: no GEMINI_API_KEY or ANTHROPIC_API_KEY set — server will run but every")
        print("!! answer will be a meaningless mock response. Set the key before demoing.\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
