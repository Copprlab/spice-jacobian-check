"""Command-line interface. Copyright (c) 2026, Copprlab."""
import argparse
import json
from pathlib import Path

from .checker import check

FIELDS = {"source", "probe", "bias", "step", "mode", "frequency", "rtol", "atol", "timeout"}


def run_cases(cases, directory, defaults, binary, keep_work):
    results = []
    for index, case in enumerate(cases):
        unknown = set(case) - FIELDS - {"id", "deck", "metadata"}
        if unknown:
            raise ValueError(f"case {index}: unknown fields {sorted(unknown)}; put annotations in metadata")
        options = {**defaults, **{k: v for k, v in case.items() if k in FIELDS}}
        missing = {"source", "probe", "bias", "step"} - options.keys()
        if missing or "deck" not in case:
            raise ValueError(f"case {index}: send deck, source, probe, bias and step; missing {sorted(missing | ({'deck'} if 'deck' not in case else set()))}")
        result = check(directory / case["deck"], binary=binary, keep_work=keep_work, **options)
        result.update(id=case.get("id", str(index)))
        if "metadata" in case:
            result["metadata"] = case["metadata"]
        results.append(result)
    if not results:
        raise ValueError("no cases were supplied; zero checks cannot pass")
    return {"schema_version": 1, "checks": results, "executed": len(results),
            "passed": sum(row["status"] == "pass" for row in results)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare low-frequency AC transfer with two central DC derivatives")
    sub = parser.add_subparsers(dest="command", required=True)
    direct = sub.add_parser("check", help="check one deck and one or more source/probe pairs")
    direct.add_argument("deck", type=Path)
    direct.add_argument("--source")
    direct.add_argument("--probe", action="append")
    direct.add_argument("--bias", type=float)
    direct.add_argument("--step", type=float)
    direct.add_argument("--pairs", type=Path, help="JSON list of source/probe/bias/step objects")
    direct.add_argument("--mode", default="default")
    direct.add_argument("--frequency", type=float, default=1e-5)
    direct.add_argument("--rtol", type=float, default=1e-4)
    direct.add_argument("--atol", type=float, default=1e-8)
    suite = sub.add_parser("run-suite", help="check all cases in a JSON suite")
    suite.add_argument("suite", type=Path)
    for command in (direct, suite):
        command.add_argument("--ngspice", "--binary", dest="binary", default="ngspice")
        command.add_argument("--keep-work", type=Path, help="retain generated decks/logs in this directory")
        command.add_argument("--output", type=Path, help="write JSON here instead of stdout")
    args = parser.parse_args(argv)
    try:
        if args.command == "run-suite":
            document = json.loads(args.suite.read_text())
            defaults = document.get("defaults", {})
            if set(defaults) - FIELDS:
                raise ValueError("suite defaults may contain only checker arguments")
            result = run_cases(document["cases"], args.suite.resolve().parent, defaults, args.binary, args.keep_work)
        else:
            if args.pairs:
                if any(v is not None for v in (args.source, args.probe, args.bias, args.step)):
                    raise ValueError("send --pairs or --source/--probe/--bias/--step, not both")
                pairs = json.loads(args.pairs.read_text())
            else:
                if not args.source or not args.probe or args.bias is None or args.step is None:
                    raise ValueError("send --source, --probe, --bias and --step (or --pairs)")
                pairs = [dict(source=args.source, probe=probe, bias=args.bias, step=args.step) for probe in args.probe]
            cases = [dict(pair, deck=args.deck.name) for pair in pairs]
            defaults = {key: getattr(args, key) for key in ("mode", "frequency", "rtol", "atol")}
            result = run_cases(cases, args.deck.resolve().parent, defaults, args.binary, args.keep_work)
        payload = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.resolve().write_text(payload)
        else:
            print(payload, end="")
        return 0 if result["passed"] == result["executed"] else 1
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"spice-jacobian-check: {error}\n")
