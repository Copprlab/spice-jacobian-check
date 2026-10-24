"""The ngspice subprocess adapter. Copyright (c) 2026, Copprlab."""
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess


@dataclass
class Simulation:
    exit_code: int | None
    log: str
    timed_out: bool = False


class Ngspice:
    """All simulator process invocation lives here; the checker consumes scalars."""

    def __init__(self, binary="ngspice", mode="default", timeout=30):
        candidate = shutil.which(str(binary))
        if not candidate:
            candidate = str(Path(binary).expanduser().resolve())
        if not Path(candidate).is_file():
            raise ValueError(f"ngspice executable does not exist: {binary}")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.binary, self.mode, self.timeout = candidate, mode, timeout

    def run(self, generated_deck, original_directory):
        command = [self.binary, "-n"]
        if self.mode != "default":
            command += ["-D", "ngbehavior=" + self.mode]
        command += ["-b", str(generated_deck)]
        env = {k: v for k, v in os.environ.items() if not any(
            name in k.upper() for name in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))}
        env.update(CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1")

        def affinity():
            if hasattr(os, "sched_getaffinity"):
                os.sched_setaffinity(0, [min(os.sched_getaffinity(0))])

        try:
            result = subprocess.run(command, cwd=original_directory, env=env,
                                    capture_output=True, text=True, errors="replace",
                                    timeout=self.timeout,
                                    preexec_fn=affinity if os.name == "posix" else None)
            return Simulation(result.returncode, result.stdout + result.stderr)
        except subprocess.TimeoutExpired:
            return Simulation(None, "", timed_out=True)
