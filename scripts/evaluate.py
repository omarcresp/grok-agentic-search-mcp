"""Repeatable Grok-only evaluations. Human rubrics are never treated as automated truth."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from grok_search_mcp.jobs import ResearchJobs
from grok_search_mcp.models import MODEL, SearchOptions
from grok_search_mcp.prompts import VERSION
from grok_search_mcp.research import valid_evidence

ROOT = Path(__file__).resolve().parents[1]


def measurements(output, full_sources) -> dict:
    evidence = [e for c in output.claims if c.status != "unverified" for e in c.evidence]
    matches = valid_evidence(evidence, full_sources)
    return {
        "citation_array": isinstance(output.citations, list),
        "citation_count_consistent": len(output.citations) == output.source_count,
        "matched_quotes": len(matches),
        "total_reviewed_quotes": len(evidence),
        "quote_match_rate": len(matches) / len(evidence) if evidence else None,
        "latency_seconds": output.elapsed_seconds,
        "reported_cost_usd": output.usage.reported_cost_usd,
        "cost_complete": output.usage.cost_complete,
        "quality_counters": output.quality.model_dump(),
        # Citation existence and model judgments do not measure real factual accuracy.
        "human_rubric_score": None,
    }


async def evaluate(args, cases):
    directory = args.output or ROOT / ".research-data" / "evaluations" / datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True, exist_ok=True)
    jobs = ResearchJobs()
    summary = {
        "model": MODEL,
        "prompt_version": VERSION,
        "package_version": version("grok-search-mcp"),
        "run_at": datetime.now(timezone.utc).isoformat(),
        "runs": [],
    }
    try:
        for case in cases:
            for mode in ["standard", "deep"] if args.mode == "both" else [args.mode]:
                label = f"{case['id']}-{mode}"
                print(f"Starting {label}", flush=True)
                options = SearchOptions(
                    query=case["query"],
                    depth=mode,
                    source_urls=case.get("source_urls", []),
                    allowed_domains=case.get("allowed_domains", []),
                    include_x=False,
                    max_cost_usd=args.max_cost_usd,
                    timeout_seconds=args.timeout,
                    max_rounds=args.rounds,
                )
                output = await jobs.search(options)
                record = jobs.get_record(output.research_id)
                metrics = measurements(output, record.output.sources)
                artifact = {
                    "case": case,
                    "result": output.model_dump(
                        mode="json", exclude={"sources": {"__all__": {"text"}}}
                    ),
                    "measurements": metrics,
                }
                (directory / f"{label}.json").write_text(
                    json.dumps(artifact, indent=2, ensure_ascii=False)
                )
                summary["runs"].append(
                    {
                        "case": case["id"],
                        "depth": mode,
                        "status": output.status,
                        "stop_reason": output.stop_reason,
                        **metrics,
                    }
                )
                (directory / "summary.json").write_text(json.dumps(summary, indent=2))
                print(
                    f"{label}: {output.status}, ${output.usage.reported_cost_usd:.4f}, "
                    f"{output.elapsed_seconds:.1f}s",
                    flush=True,
                )
    finally:
        await jobs.close()
    print(f"Artifacts: {directory}")
    return 1 if any(r["status"] == "failed" for r in summary["runs"]) else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Enable billable xAI requests")
    parser.add_argument("--cases", type=Path, default=ROOT / "evals" / "questions.json")
    parser.add_argument("--case-id", help="Run only this case ID")
    parser.add_argument("--limit", type=int, default=1, help="Number of cases (default 1)")
    parser.add_argument("--mode", choices=["standard", "deep", "both"], default="both")
    parser.add_argument(
        "--max-cost-usd", type=float, default=1, help="Between-call threshold PER RUN"
    )
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    if args.case_id:
        cases = [c for c in cases if c["id"] == args.case_id]
    if not cases or args.limit < 1:
        parser.error("Select at least one case and a positive limit")
    cases = cases[: args.limit]
    if not args.live:
        print(json.dumps(cases, indent=2, ensure_ascii=False))
        print("Dry run. Pass --live and set XAI_API_KEY to execute these cases.")
        return 0
    return asyncio.run(evaluate(args, cases))


if __name__ == "__main__":
    raise SystemExit(main())
