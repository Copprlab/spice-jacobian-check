# spice-jacobian-check

**Check that ngspice's AC response agrees with the slope of its DC solution.**

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-00897B)](LICENSE)

An independent check for simulator and device-model engineers. Select your
ngspice executable, an input source and an output probe; get a JSON result
comparing low-frequency AC with two central DC differences. Python's standard
library is sufficient at runtime. No reference simulator is required.

[Quickstart](#quickstart) · [Read the result](#read-the-result) ·
[How it works](#how-it-works) · [Switch suite](#the-97-case-switch-suite) ·
[Limitations](#limitations) · [Tests](#tests)

## Quickstart

You need **Python 3.10+** and a working **ngspice** executable. The example below
uses only standard circuit elements; XSPICE is needed for the switch suite.
Run these commands in a terminal with `ngspice` on `PATH`:

```bash
git clone https://github.com/Copprlab/spice-jacobian-check.git
cd spice-jacobian-check
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .

spice-jacobian-check check examples/divider.cir \
  --source VDR --probe 'v(out)' --bias 0.1 --step 1e-5
```

The [bundled divider](examples/divider.cir) has two equal resistors. Its DC
slope and AC gain should both be approximately **0.5 V/V**. The JSON result
should report `"executed": 1`, `"passed": 1` and `"status": "pass"`; the command
exits with status **0**.

To select a particular ngspice build, add `--ngspice /path/to/ngspice`:

```bash
spice-jacobian-check check examples/divider.cir \
  --ngspice /path/to/ngspice \
  --source VDR --probe 'v(out)' --bias 0.1 --step 1e-5 \
  --output results.json
```

`--ngspice` accepts either an executable path or a command on `PATH`. From a
source checkout, `python -m spice_jacobian_check` runs the same CLI without
installation. Use `spice-jacobian-check check --help` to list the options.

## Read the result

Results go to stdout unless you supply `--output`. The top-level JSON contains
`executed`, `passed` and a `checks` list. Each completed numerical check includes:

| Field | Meaning | Divider expectation |
| --- | --- | --- |
| `dc_slope_h` | Central DC difference using perturbation `h` | About 0.5 |
| `dc_slope_h_over_2` | Same calculation with `h/2` | About 0.5 |
| `ac_real`, `ac_imag` | Complex AC transfer at the requested frequency | About 0.5, 0 |
| `dc_step_agreement_abs` | Difference between the two DC slopes | Near zero |
| `ac_vs_dc_abs` | Largest complex AC/DC disagreement across three frequencies | Near zero |
| `dc_return_error_abs` | Output change after returning to the nominal DC input | Near zero |
| `status` | Verdict for this source/probe pair | `pass` |

A failed simulation or timeout may have no numerical fields.

| Status | Interpretation |
| --- | --- |
| `pass` | The local AC/DC and DC-return checks meet their tolerances. |
| `fail` | The DC steps disagree or AC differs from the DC derivative. |
| `invalid_operating_point` | Transient-OP fallback was used, or the DC solution changed on return. |
| `simulation_error` | The simulator failed or required finite results were missing. |
| `timeout` | The simulator exceeded the time limit. |

The process exits **0** only if every requested check passes, **1** for a
nonpassing check, or **2** for a command/input error. An empty list cannot pass.
A mismatch is a diagnostic to investigate, not proof of a device bug.

## How it works

At a smooth DC equilibrium, the circuit equations are `F(x,u)=0`, where `u` is
an independent source and `x` contains node voltages and branch currents.
Differentiating gives `J dx/du + dF/du = 0`. Small-signal AC analysis approaches
the same linearized equations as frequency tends to zero, provided the
steady-state solution and that limit are well defined.

For perturbation `h`, the checker computes:

```text
D(h)   = [y(u+h)   - y(u-h)]   / (2h)
D(h/2) = [y(u+h/2) - y(u-h/2)] / h

step disagreement = abs(D(h/2) - D(h))
AC disagreement   = max(abs(AC(f') - D(h/2)))
                    for f' = 0.99f, f, 1.01f
```

Both disagreements must be at most `atol + rtol*abs(D(h/2))`. Defaults are
`atol=1e-8`, `rtol=1e-4` and `frequency=1e-5 Hz`. The comparison uses the full
complex AC transfer, including its imaginary part. The two-step comparison
is an observed convergence check, not a rigorous error bound.

After the perturbations, the nominal DC point is solved again. Branch drift
or transient-operating-point fallback makes the result
`invalid_operating_point`, even when the numerical slopes happen to agree.

## Check your own circuit

Start with a materialized circuit deck, a smooth operating point and an
independent voltage or current source. `--bias` is the nominal source value;
`--step` is the DC perturbation in the source's units. `--frequency` is in Hz.

```bash
spice-jacobian-check check my-circuit.cir \
  --ngspice /path/to/ngspice \
  --source VIN --probe 'v(out)' --bias 3.3 --step 1e-4 \
  --frequency 1e-5 --rtol 1e-4 --atol 1e-8
```

Current probes such as `'i(vdr)'` are supported. Units follow the source and
probe: voltage gain is V/V, transimpedance is V/A, and transconductance is A/V.
Repeat `--probe` for multiple outputs at the same input and bias:

```bash
spice-jacobian-check check examples/divider.cir \
  --source VDR --probe 'v(out)' --probe 'i(vdr)' \
  --bias 0.1 --step 1e-5
```

For different source/bias pairs, put a JSON list in `pairs.json`:

```json
[
  {"source": "VDR", "probe": "v(out)", "bias": 0.1, "step": 1e-5},
  {"source": "VDR", "probe": "i(vdr)", "bias": 0.2, "step": 1e-5}
]
```

```bash
spice-jacobian-check check examples/divider.cir --pairs pairs.json
```

`--pairs` replaces `--source`, `--probe`, `--bias` and `--step`. Add `--mode ps`
when included files need ngspice's PSpice compatibility mode.

For code models, the ngspice installation's startup file must load the required
libraries. An uninstalled build may need `SPICE_SCRIPTS` set to its startup
directory. Model availability depends on the build you select.

## The 97-case switch suite

```bash
spice-jacobian-check run-suite examples/switches/suite.json \
  --ngspice /path/to/ngspice --output switch-results.json
```

The suite uses independently written `pswitch`/`aswitch` circuits, PSpice
`VSWITCH` dividers and a three-switch amplifier. It requires XSPICE code models.
Coverage includes both control directions, signal/control excitation,
off/transition/on regions, log/linear interpolation, finite control loading,
resistance limits and coincident threshold expansion.

| Archived measurement | Passed | Failed | Evidence |
| --- | ---: | ---: | --- |
| Unmodified ngspice master | 11 | 86 | [Before](examples/switches/before.json) |
| With the switch current-Jacobian patch | 97 | 0 | [After](examples/switches/after.json) |

These measurements used master `a80f6e3e95d51534905b1f23410a951802666656`
and the patch submitted on [ngspice bug #883](https://sourceforge.net/p/ngspice/bugs/883/).
[Provenance](examples/switches/provenance.json) distinguishes the archived
measurements from rerunning this standalone checker, which additionally
checks return to the nominal DC point. The files contain measurements rather
than raw logs. They are evidence for those builds, not expected results for
every future implementation.

## Add a suite or simulator adapter

A suite is a JSON object with optional checker `defaults` and a nonempty
`cases` list. Deck paths are relative to the suite file. Each case has `id`,
`deck`, `source`, `probe`, `bias` and `step`; it can override `frequency`,
`rtol`, `atol`, `mode` and `timeout`. Put annotations in `metadata`.

For example, save this as `examples/divider-suite.json`:

```json
{
  "defaults": {"frequency": 1e-5, "rtol": 1e-4, "atol": 1e-8},
  "cases": [
    {"id": "divider", "deck": "divider.cir", "source": "VDR",
     "probe": "v(out)", "bias": 0.1, "step": 1e-5}
  ]
}
```

Run it with `spice-jacobian-check run-suite examples/divider-suite.json`.

Simulator subprocess invocation lives in
[ngspice.py](spice_jacobian_check/ngspice.py). The checker accepts an adapter
with `run(generated_deck, original_directory)`; another simulator would also
need the appropriate deck and scalar-output translation. No alternate
simulator is bundled.

## Limitations

- **Prepare a static deck.** Existing analyses, save lists and `.control`
  blocks are replaced. Turn control-block circuit alterations into circuit
  cards first. Device parameters and topology stay the same for DC and AC.
- **Isolate the excitation.** Other top-level independent-source AC magnitudes
  are zeroed. Sources inside includes and subcircuits must already have zero
  AC excitation. Relative includes resolve from the original deck directory.
- **Resolve the perturbation.** Choose a smooth point where `h` and `h/2`
  agree. Small steps can suffer cancellation; large ones can cross operating
  regions. An ideal switching corner may have no unique derivative, and
  hysteresis may select another DC branch. Simulator convergence tolerances
  must resolve the perturbation; the checker does not silently change them.
- **Choose a low enough frequency.** Real dynamics can produce a legitimate
  imaginary component. Lower the frequency and inspect the trend. Integrators,
  oscillators and stateful initial conditions may have no valid DC limit.
- **Check the physics separately.** A pass establishes local consistency under
  these assumptions. It does not prove that the physical branch was selected
  or that the device equations are correct. An incorrect DC constraint and
  an incorrect AC stamp can agree; use an independent constitutive-law check
  where needed.

Generated decks and logs are temporary by default. For diagnosis,
`--keep-work /path/to/work` retains them and reports the directory without
embedding their contents in the result JSON. Check any applicable deck/model
licence before sharing those files.

## Tests

```bash
NGSPICE_BINARY=/path/to/ngspice python -m unittest discover -s tests -v
```

Unit tests run without ngspice. Integration tests are skipped unless
`NGSPICE_BINARY` is set; supply it for a complete run. Coverage includes source
isolation, continuation cards, step convergence, frequency selection, missing
and nonfinite results, invalid operating points, temporary cleanup, multiple
pairs and CLI exit codes.

## License

[BSD-3-Clause](LICENSE) · Copyright Copprlab.
