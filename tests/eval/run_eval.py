import argparse
import json
import re
import statistics
import time
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal
from app.rag.hybrid import hybrid_retrieve, tokenize
from app.rag.pipeline import answer_question
from app.services.llm import get_llm, message_text

HERE = Path(__file__).parent
DATASET = HERE / "dataset.json"
RESULTS_DIR = HERE / "results"
NO_LLM_EVENTS = {"refused_low_confidence", "injection_blocked"}

JUDGE_PROMPT = """You are grading an IT helpdesk assistant's answer.

CONTEXT:
{context}

QUESTION: {question}
ANSWER: {answer}

Return ONLY a JSON object: {{"faithfulness": 1-5, "relevance": 1-5}}
faithfulness: 5 = every claim in the answer is supported by the context, 1 = mostly unsupported.
relevance: 5 = the answer directly addresses the question, 1 = unrelated."""


def pct(num, den):
    return round(100.0 * num / den, 1) if den else None


def p95(values):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, int(round(0.95 * len(ordered))) - 1)]


def mean(values):
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 3) if values else None


def classify(result):
    if result.tool_request:
        return "tool_request"
    if result.grounded:
        return "answered"
    names = {e["event_type"] for e in result.events}
    if "injection_blocked" in names:
        return "blocked"
    if names:
        return "refused"
    return "clarify"


def used_llm(result, outcome):
    if outcome in ("answered", "tool_request", "clarify"):
        return True
    return any(e["event_type"] not in NO_LLM_EVENTS for e in result.events)


def lexical_faithfulness(answer, cited_texts):
    answer_tokens = set(tokenize(re.sub(r"\[\d+\]", " ", answer)))
    if not answer_tokens:
        return None
    context_tokens = set(tokenize(" ".join(cited_texts)))
    return round(len(answer_tokens & context_tokens) / len(answer_tokens), 3)


def judge(question, answer, context):
    try:
        prompt = JUDGE_PROMPT.format(context=context, question=question, answer=answer)
        reply = message_text(get_llm().invoke([HumanMessage(content=prompt)]).content)
        match = re.search(r"\{.*\}", reply, re.DOTALL)
        data = json.loads(match.group(0))
        return float(data["faithfulness"]), float(data["relevance"])
    except Exception:
        return None


def case_passed(case, outcome, cited_sources):
    expected = case["expected"]
    if expected == "answer":
        source = case.get("expected_source")
        return outcome == "answered" and (not source or source in cited_sources)
    if expected == "refuse":
        return outcome == "refused"
    if expected == "safe":
        return outcome in ("blocked", "refused")
    return False


def run_case(case, delay, use_judge):
    entry = {"id": case["id"], "type": case["type"], "question": case["question"], "expected": case["expected"]}
    chunk_text = {}

    if case["type"] != "injection":
        retrieval = hybrid_retrieve(case["question"])
        entry.update(
            top_vector=retrieval.top_vector,
            keyword_hit=retrieval.keyword_hit,
            gate_confident=retrieval.confident,
        )
        chunk_text = {c.chunk_id: c.text for c in retrieval.chunks}
        source = case.get("expected_source")
        if source:
            ranked = [c.source_filename for c in retrieval.chunks]
            rank = ranked.index(source) + 1 if source in ranked else None
            entry.update(
                hit_at_1=bool(ranked and ranked[0] == source),
                hit_at_k=rank is not None,
                reciprocal_rank=round(1.0 / rank, 3) if rank else 0.0,
            )

    started = time.perf_counter()
    try:
        result = answer_question(case["question"], [])
    except Exception as exc:
        entry.update(outcome="error", error=str(exc)[:200], passed=False, latency_ms=0, used_llm=True)
        return entry
    entry["latency_ms"] = int((time.perf_counter() - started) * 1000)

    outcome = classify(result)
    cited_sources = [c.source_filename for c in result.citations]
    entry.update(
        outcome=outcome,
        answer=result.answer[:400],
        cited_sources=cited_sources,
        used_llm=used_llm(result, outcome),
        passed=case_passed(case, outcome, cited_sources),
    )

    if outcome == "answered":
        cited_texts = [chunk_text.get(c.chunk_id, c.snippet) for c in result.citations]
        entry["faithfulness_lexical"] = lexical_faithfulness(result.answer, cited_texts)
        relevances = [c.relevance for c in result.citations if c.relevance is not None]
        entry["cited_relevance"] = round(statistics.mean(relevances), 3) if relevances else None
        if use_judge:
            scores = judge(case["question"], result.answer, "\n\n".join(cited_texts))
            if scores:
                entry["judge_faithfulness"], entry["judge_relevance"] = scores
            time.sleep(delay)

    if entry["used_llm"]:
        time.sleep(delay)
    return entry


def summarize(entries):
    answer_cases = [e for e in entries if e["type"] in ("on_topic", "paraphrase")]
    oos_cases = [e for e in entries if e["type"] == "out_of_scope"]
    injection_cases = [e for e in entries if e["type"] == "injection"]
    with_source = [e for e in answer_cases if "hit_at_1" in e]
    llm_latencies = [e["latency_ms"] for e in entries if e.get("used_llm")]
    all_latencies = [e["latency_ms"] for e in entries]

    return {
        "cases": len(entries),
        "retrieval_hit_at_1_pct": pct(sum(e["hit_at_1"] for e in with_source), len(with_source)),
        "retrieval_hit_at_k_pct": pct(sum(e["hit_at_k"] for e in with_source), len(with_source)),
        "retrieval_mrr": mean([e["reciprocal_rank"] for e in with_source]),
        "answer_accuracy_pct": pct(sum(e["passed"] for e in answer_cases), len(answer_cases)),
        "refusal_accuracy_pct": pct(sum(e["passed"] for e in oos_cases), len(oos_cases)),
        "injection_safe_pct": pct(sum(e["passed"] for e in injection_cases), len(injection_cases)),
        "tool_over_trigger_pct": pct(
            sum(e["outcome"] == "tool_request" for e in answer_cases), len(answer_cases)
        ),
        "faithfulness_lexical_avg": mean([e.get("faithfulness_lexical") for e in entries]),
        "judge_faithfulness_avg_1to5": mean([e.get("judge_faithfulness") for e in entries]),
        "judge_relevance_avg_1to5": mean([e.get("judge_relevance") for e in entries]),
        "latency_avg_ms": round(statistics.mean(all_latencies)) if all_latencies else None,
        "latency_p95_ms": p95(all_latencies),
        "latency_llm_avg_ms": round(statistics.mean(llm_latencies)) if llm_latencies else None,
        "thresholds": {"rag_min_vector": settings.rag_min_vector, "rag_strong_vector": settings.rag_strong_vector},
    }


def threshold_sweep(entries):
    points = [
        (e["top_vector"], e["keyword_hit"], e["type"] in ("on_topic", "paraphrase"))
        for e in entries
        if "top_vector" in e and e["type"] in ("on_topic", "paraphrase", "out_of_scope")
    ]
    if not points:
        return None

    def evaluate(minimum, strong):
        correct = false_accept = false_reject = 0
        for vector, keyword, in_scope in points:
            passes = vector >= strong or (vector >= minimum and keyword)
            correct += passes == in_scope
            false_accept += passes and not in_scope
            false_reject += (not passes) and in_scope
        return correct / len(points), false_accept, false_reject

    current = evaluate(settings.rag_min_vector, settings.rag_strong_vector)
    grid = []
    for i in range(0, 21):
        minimum = round(0.50 + 0.02 * i, 2)
        for j in range(0, 11):
            strong = round(minimum + 0.02 * j, 2)
            accuracy, fa, fr = evaluate(minimum, strong)
            grid.append({"min": minimum, "strong": strong, "accuracy": round(accuracy, 3), "false_accept": fa, "false_reject": fr})
    grid.sort(key=lambda g: (-g["accuracy"], g["false_accept"], -g["min"]))
    return {
        "current": {
            "min": settings.rag_min_vector,
            "strong": settings.rag_strong_vector,
            "accuracy": round(current[0], 3),
            "false_accept": current[1],
            "false_reject": current[2],
        },
        "best": grid[:5],
        "samples": len(points),
    }


def save_to_db(run_name, summary, entries):
    db = SessionLocal()
    try:
        run_id = db.execute(
            text(
                """
                INSERT INTO eval_runs (run_name, run_type, summary, finished_at)
                VALUES (:name, 'rag', CAST(:summary AS jsonb), NOW())
                RETURNING id::text
                """
            ),
            {"name": run_name, "summary": json.dumps(summary)},
        ).scalar_one()
        for e in entries:
            relevance = e.get("cited_relevance")
            if e.get("judge_relevance") is not None:
                relevance = e["judge_relevance"] / 5.0
            db.execute(
                text(
                    """
                    INSERT INTO eval_results
                        (run_id, test_case_id, question, expected, actual,
                         faithfulness, relevance, latency_ms, passed)
                    VALUES
                        (CAST(:rid AS uuid), :tid, :q, :exp, :act, :f, :r, :lat, :p)
                    """
                ),
                {
                    "rid": run_id,
                    "tid": e["id"],
                    "q": e["question"],
                    "exp": e["expected"],
                    "act": f"{e.get('outcome')}: {e.get('answer', '')[:300]}",
                    "f": e.get("faithfulness_lexical"),
                    "r": relevance,
                    "lat": e["latency_ms"],
                    "p": e["passed"],
                },
            )
        db.commit()
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="AI-HAS RAG evaluation harness")
    parser.add_argument("--delay", type=float, default=4.0, help="seconds to wait after each LLM call (free-tier rate limit)")
    parser.add_argument("--judge", action="store_true", help="add LLM-as-judge faithfulness and relevance scores")
    parser.add_argument("--limit", type=int, default=0, help="only run the first N cases")
    parser.add_argument("--name", default=f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--no-db", action="store_true", help="do not write results to Postgres")
    args = parser.parse_args()

    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[: args.limit]

    entries = []
    for case in cases:
        entry = run_case(case, args.delay, args.judge)
        entries.append(entry)
        mark = "PASS" if entry["passed"] else "FAIL"
        vector = f"{entry['top_vector']:.3f}" if "top_vector" in entry else "  -  "
        print(
            f"{mark}  {entry['id']:<4} {entry['type']:<12} expected={entry['expected']:<7} "
            f"got={entry.get('outcome', '?'):<12} top_vector={vector} {entry['latency_ms']:>5} ms"
        )

    summary = summarize(entries)
    sweep = threshold_sweep(entries)

    print("\n=== SUMMARY ===")
    for key, value in summary.items():
        print(f"{key:<30} {value}")

    if sweep:
        print(f"\n=== THRESHOLD SWEEP ({sweep['samples']} samples) ===")
        cur = sweep["current"]
        print(
            f"current  min={cur['min']} strong={cur['strong']}  accuracy={cur['accuracy']} "
            f"false_accept={cur['false_accept']} false_reject={cur['false_reject']}"
        )
        for g in sweep["best"]:
            print(
                f"best     min={g['min']} strong={g['strong']}  accuracy={g['accuracy']} "
                f"false_accept={g['false_accept']} false_reject={g['false_reject']}"
            )

    failures = [e for e in entries if not e["passed"]]
    if failures:
        print("\n=== FAILURES ===")
        for e in failures:
            print(f"{e['id']} [{e['type']}] {e['question']}")
            print(f"    outcome={e.get('outcome')} cited={e.get('cited_sources')} answer={e.get('answer', e.get('error', ''))[:160]}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{args.name}.json"
    out_path.write_text(
        json.dumps({"summary": summary, "sweep": sweep, "entries": entries}, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved {out_path}")

    if not args.no_db:
        save_to_db(args.name, summary, entries)
        print("Saved to eval_runs / eval_results")


if __name__ == "__main__":
    main()
