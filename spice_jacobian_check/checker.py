"""Finite-difference/AC oracle. Copyright (c) 2026, Copprlab."""
import hashlib
import math
from pathlib import Path
import re
import tempfile

from .ngspice import Ngspice

ANALYSES = re.compile(r"\s*\.(?:end|op|dc|ac|tran|noise|pz|tf|sens|meas(?:ure)?|print|plot|save)\b", re.I)


def circuit(text):
    """Retain circuit cards; discard analyses/control blocks and their continuations."""
    lines, control, omit = [], False, False
    for line in text.splitlines():
        if re.match(r"\s*\.control\b", line, re.I):
            control, omit = True, False
            continue
        if re.match(r"\s*\.endc\b", line, re.I):
            control = False
            continue
        if control:
            continue
        continuation = bool(re.match(r"\s*\+", line))
        comment = not line.strip() or line.lstrip().startswith("*")
        if not continuation and not comment:
            omit = bool(ANALYSES.match(line))
        if not omit or comment:
            lines.append(line)
    return "\n".join(lines)


def independent_sources(text):
    depth = 0
    for line in text.splitlines()[1:]:
        if re.match(r"\s*\.subckt\b", line, re.I):
            depth += 1
        elif re.match(r"\s*\.ends\b", line, re.I):
            depth = max(0, depth - 1)
        elif not depth:
            match = re.match(r"\s*([VI]\S*)\s+\S+\s+\S+", line, re.I)
            if match:
                yield match[1]


def validate(source, probe, bias, step, frequency, rtol, atol):
    if not re.fullmatch(r"[VI][\w.$:+-]+", source, re.I):
        raise ValueError("source must name one independent V or I source")
    if not probe.strip() or any(x in probe for x in "\n\r;"):
        raise ValueError("probe must be a single-line ngspice scalar expression")
    if not all(math.isfinite(x) for x in (bias, step, frequency, rtol, atol)):
        raise ValueError("bias, step, frequency and tolerances must be finite")
    if step <= 0 or frequency <= 0 or min(rtol, atol) < 0 or rtol + atol == 0:
        raise ValueError("step/frequency must be positive; tolerances nonnegative with a positive sum")
    perturbations = [bias + step, bias - step, bias + step / 2, bias - step / 2]
    if len(set([bias, *perturbations])) != 5 or not all(math.isfinite(x) for x in perturbations):
        raise ValueError("DC perturbations are not distinct finite floating-point values; choose another step")


def commands(source, probe, bias, step, frequency, materialized):
    rows = [".control", "set numdgt=17", "set noaskquit"]
    rows += [f"alter @{name}[acmag] = 0" for name in independent_sources(materialized)]
    rows += [f"alter @{source}[acmag] = 1"]
    for label, delta in [("zero", 0), ("plus", step), ("minus", -step),
                         ("half_plus", step / 2), ("half_minus", -step / 2), ("return", 0)]:
        rows += [f"alter {source} = {bias + delta:.17g}", "op",
                 f"let sjc_{label} = {probe}", f"print sjc_{label}"]
    rows += [f"ac lin 3 {frequency * .99:.17g} {frequency * 1.01:.17g}",
             f"let sjc_signal = {probe}", "let sjc_real = real(sjc_signal)",
             "let sjc_imag = imag(sjc_signal)"]
    for index in range(3):
        rows += [f"let sjc_re{index} = sjc_real[{index}]", f"let sjc_im{index} = sjc_imag[{index}]",
                 f"print sjc_re{index} sjc_im{index}"]
    return rows + ["quit", ".endc", ".end"]


def assess(log, exit_code, step, frequency, rtol, atol):
    values = {}
    for match in re.finditer(r"(?im)^sjc_(\w+)\s*=\s*(\S+)", log):
        try:
            values[match[1]] = float(match[2])
        except ValueError:
            continue
    needed = ["zero", "plus", "minus", "half_plus", "half_minus", "return"]
    needed += [axis + str(i) for i in range(3) for axis in ("re", "im")]
    invalid = [k for k in needed if k not in values or not math.isfinite(values[k])]
    if exit_code or invalid:
        return {"status": "simulation_error", "exit_code": exit_code,
                "missing_or_nonfinite": invalid}
    coarse = (values["plus"] - values["minus"]) / (2 * step)
    fine = (values["half_plus"] - values["half_minus"]) / step
    ac = [[values[f"re{i}"], values[f"im{i}"]] for i in range(3)]
    agreement = abs(fine - coarse)
    error = max(math.hypot(re_ - fine, im) for re_, im in ac)
    tolerance = atol + rtol * abs(fine)
    fallback = "transient op started" in log.lower()
    returned = abs(values["return"] - values["zero"])
    branch_tolerance = rtol * max(abs(values["zero"]), abs(values["return"])) + atol * step
    status = "pass" if agreement <= tolerance and error <= tolerance else "fail"
    if fallback or returned > branch_tolerance:
        status = "invalid_operating_point"
    return {"status": status, "dc_output": values["zero"],
            "dc_slope_h": coarse, "dc_slope_h_over_2": fine,
            "dc_step_agreement_abs": agreement, "dc_return_error_abs": returned,
            "dc_return_tolerance_abs": branch_tolerance,
            "ac_three_points": ac, "ac_real": ac[1][0], "ac_imag": ac[1][1],
            "ac_vs_dc_abs": error, "ac_vs_dc_relative": error / max(abs(fine), atol, 1e-300),
            "tolerance_abs": tolerance, "rtol": rtol, "atol": atol,
            "step": step, "frequency_hz": frequency,
            "transient_operating_point_fallback": fallback}


def check(deck, source, probe, bias, step, *, binary="ngspice", mode="default",
          frequency=1e-5, rtol=1e-4, atol=1e-8, timeout=30, keep_work=None, adapter=None):
    """Check one source/probe pair. No generated deck or log is retained by default."""
    validate(source, probe, bias, step, frequency, rtol, atol)
    deck = Path(deck).expanduser().resolve()
    text = deck.read_text()
    materialized = circuit(text)
    simulator = adapter or Ngspice(binary, mode, timeout)
    body = materialized + "\n.save all\n" + "\n".join(commands(source, probe, bias, step, frequency, materialized)) + "\n"
    if keep_work:
        parent = Path(keep_work).expanduser().resolve()
        parent.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix="jacobian-", dir=parent))
        result = _simulate(simulator, directory, deck.parent, body, step, frequency, rtol, atol, True)
        result["work_directory"] = str(directory)
    else:
        with tempfile.TemporaryDirectory(prefix="jacobian-") as folder:
            result = _simulate(simulator, Path(folder), deck.parent, body, step, frequency, rtol, atol, False)
    result.update(source=source, probe=probe, bias=bias, mode=mode,
                  deck_sha256=hashlib.sha256(text.encode()).hexdigest())
    return result


def _simulate(simulator, directory, original_directory, body, step, frequency, rtol, atol, keep):
    generated = directory / "check.cir"
    generated.write_text(body)
    run = simulator.run(generated, original_directory)
    if keep:
        (directory / "simulator.log").write_text(run.log)
    if run.timed_out:
        return {"status": "timeout"}
    return assess(run.log, run.exit_code, step, frequency, rtol, atol)
