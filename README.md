# spice-jacobian-check

Check an ngspice small-signal AC transfer against the derivative of its DC
operating point. The tool reports two central differences, three nearby AC
samples, their disagreement and a verdict. It uses Python 3.10+ and the standard
library; ngspice is a separate executable you supply. BSD-3-Clause, copyright
Copprlab.

## Why AC should equal a DC derivative

Write the equilibrium circuit equations as `F(x,u)=0`, where `u` is an
independent source and `x` contains node voltages and branch currents.
Differentiation gives `J dx/du + dF/du = 0`. Small-signal analysis solves the same
linearized equations as frequency tends to zero, provided the equilibrium is
well defined and the frequency is below relevant poles. Thus an AC transfer
with a unit input must approach the corresponding DC derivative. Another
simulator is not needed as a reference.

For perturbation `h`, the checker computes:

```
D(h)   = [y(u+h)   - y(u-h)]   / (2h)
D(h/2) = [y(u+h/2) - y(u-h/2)] / h
step disagreement = abs(D(h/2) - D(h))
AC disagreement = max(abs(AC(f') - D(h/2))) for f' = 0.99f, f, 1.01f
```

Both disagreements must be at most `atol + rtol*abs(D(h/2))`.
Defaults are `atol=1e-8`, `rtol=1e-4`, and `f=1e-5 Hz`. The full complex AC
transfer is checked, including its imaginary part. The step disagreement is an
observed convergence check, not a rigorous error bound. The nominal DC point is
also solved again after the perturbations: branch drift or transient-operating-
point fallback makes the result `invalid_operating_point`.

## Install and run

```bash
python -m pip install .
spice-jacobian-check check divider.cir \
  --ngspice /path/to/ngspice --source VDR --probe 'v(out)' \
  --bias 0.1 --step 1e-5 --frequency 1e-5
```

From a source checkout, `python -m spice_jacobian_check` provides the same CLI
without installation. `--ngspice` accepts an executable path or a command on
`PATH`, so different builds can be checked without changing the program. The
usual installed ngspice startup file must load any required code-model
libraries. For an uninstalled build, set `SPICE_SCRIPTS` to an appropriate
startup directory. Model availability depends on that build.

For example, `divider.cir` can contain:

```spice
Resistive divider
VDR IN 0 DC 0.1
R1 IN OUT 1k
R2 OUT 0 1k
.end
```

Its expected voltage derivative and low-frequency AC transfer are both 0.5.
A current probe such as `'i(vdr)'` is also supported. Independent current
sources are valid inputs; units follow the source and probe (for example V/A).
Repeat `--probe` to check several outputs at the same source and bias.

For distinct input/output pairs, pass `--pairs pairs.json` instead of the four
source/probe/bias/step arguments. The file is a JSON list:

```json
[
  {"source": "VDR", "probe": "v(out)", "bias": 0.1, "step": 1e-5},
  {"source": "VDR", "probe": "i(vdr)", "bias": 0.1, "step": 1e-5}
]
```

Use `--rtol`, `--atol`, `--frequency` and `--mode` to select check parameters.
`--mode ps` enables ngspice's PSpice compatibility mode for included files.
Output is JSON on stdout, or a file with `--output results.json`. Exit status
is 0 if every requested check passes, 1 for a disagreement/invalid simulation,
and 2 for a command or input error. An empty list cannot pass.

## The first suite: 97 switch checks

```bash
spice-jacobian-check run-suite examples/switches/suite.json \
  --ngspice /path/to/ngspice --output results.json
```

The suite contains independently written `pswitch`/`aswitch` circuits, PSpice
`VSWITCH` dividers, and a three-switch amplifier. It checks both control
directions, signal/control excitation, off/transition/on regions, log/linear
interpolation, finite control loading, resistance limits and coincident
threshold expansion. It requires XSPICE code models.

[Archived before results](examples/switches/before.json) contain 11 passes and
86 failures on ngspice master `a80f6e3e95d51534905b1f23410a951802666656`.
[Archived after results](examples/switches/after.json) contain 97 passes after
the switch current-Jacobian patch submitted on
[ngspice bug #883](https://sourceforge.net/p/ngspice/bugs/883/).
[Provenance](examples/switches/provenance.json) distinguishes those measured
results from rerunning this standalone tool, which additionally checks DC
return to the nominal point. These JSON files contain measurements, not raw
simulator logs. They are evidence for a particular build and patch, not golden
answers for every future implementation.

## Add a case or simulator

A suite is a JSON object with optional checker `defaults` and a nonempty
`cases` list. Paths are relative to the suite file. Each case has `id`, `deck`,
`source`, `probe`, `bias` and `step`; it can override `frequency`, `rtol`, `atol`,
`mode` and `timeout`. Put descriptive information in `metadata`.

```json
{
  "defaults": {"frequency": 1e-5, "rtol": 1e-4, "atol": 1e-8},
  "cases": [
    {"id": "divider", "deck": "divider.cir", "source": "VDR",
     "probe": "v(out)", "bias": 0.1, "step": 1e-5}
  ]
}
```

All ngspice subprocess invocation is in `spice_jacobian_check/ngspice.py`.
The checker accepts an adapter with `run(generated_deck, original_directory)`;
another simulator would also need the appropriate deck and scalar-output
translation. No alternate simulator is bundled.

## Limits and interpretation

The input must be a materialized static circuit. Existing analyses, save lists
and `.control` blocks are replaced; turn any control-block circuit alterations
into circuit cards first. Circuit topology and device parameters remain the
same for DC and AC. All vectors are saved. Other top-level independent source
AC magnitudes are zeroed; **sources inside includes/subcircuits must have zero
AC excitation**. Relative includes resolve from the original deck directory.

Choose a smooth operating point and verify that `h` and `h/2` agree. At an
ideal switch threshold or other non-differentiable corner there may be no unique
derivative. Hysteresis can change the DC branch. A small perturbation can be
lost to floating-point cancellation, and a large one can cross a region.
Simulator DC convergence tolerances must be tight enough to resolve the chosen
perturbation; the checker does not silently change them.

Real low-frequency dynamics can produce a legitimate imaginary component.
Reduce frequency and check the trend. Integrators, oscillators, stateful
initial conditions and circuits without a unique steady DC solution may not
have the required zero-frequency limit. A mismatch is a diagnostic, not proof
of a device bug. Verify equilibrium constraints specific to the circuit: even
a solver's accepted operating point can be inappropriate for the intended
measurement. Two agreeing differences do not prove that the physical branch
was selected.

A pass establishes local consistency under these assumptions, not correct
constitutive physics. A DC initial-condition constraint and an incorrect AC
stamp can share the same limit. Qualify such devices separately against their
constitutive equations or another independent physical reference.

By default generated decks and logs are temporary and removed. For diagnosis,
`--keep-work /path/to/work` retains them there and reports the directory; it
never embeds their contents in the JSON result. Device or deck licensing may
restrict sharing such work files.

## Tests

```bash
NGSPICE_BINARY=/path/to/ngspice python -m unittest discover -s tests -v
```

Unit tests run without ngspice. Integration tests are skipped unless
`NGSPICE_BINARY` is set; use it for a complete test run. Tests exercise source
isolation, continuation cards, step convergence, frequency selection, missing
and nonfinite results, invalid operating points, temporary cleanup, multiple
pairs and CLI exit codes.
