from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Union
from .errors import ArduinoCliError

__all__ = [
    "CommandResult",
    "ENV_VAR",
    "INSTALL_URL",
    "compile_sketch",
    "find_arduino_cli",
    "list_ports",
    "run",
    "upload_sketch",
    "write_sketch",
]

ENV_VAR = "MICROPY_ARDUINO_CLI"
INSTALL_URL = "https://arduino.github.io/arduino-cli/latest/installation/"

INSTALL_HINT_LINES = [
    f"1. Install the Arduino CLI: {INSTALL_URL}",
    "2. Install the AVR core for the Uno: arduino-cli core install arduino:avr",
    "3. Or point micropy at an existing binary:",
    "     micropy compile main.py --arduino-cli /path/to/arduino-cli",
    f"     (or set the {ENV_VAR} environment variable)",
    "",
    "'micropy build' and 'micropy check' work without arduino-cli.",
]

@dataclass
class CommandResult:
    args: List[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

def find_arduino_cli(explicit: Optional[str] = None) -> str:
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return str(candidate)
        found = shutil.which(explicit)
        if found:
            return found
        raise ArduinoCliError(
            f"arduino-cli was not found at '{explicit}'.",
            hint="Check the path, or install the Arduino CLI:",
            hint_lines=INSTALL_HINT_LINES,
        )
    
    from_env = os.environ.get(ENV_VAR)
    if from_env:
        found = shutil.which(from_env)
        if found:
            return found
    
    found = shutil.which("arduino-cli")
    if found:
        return found
    raise ArduinoCliError(
        "arduino-cli was not found.",
        hint="micropy needs the Arduino CLI to compile and upload sketches:",
        hint_lines=INSTALL_HINT_LINES,
    )


def run(
    args: Sequence[str],
    *,
    executable: str,
    verbose: bool = False,
    cwd: Optional[Union[str, Path]] = None,
    ) -> CommandResult:

    command = [executable, *args]
    if verbose:
        print("$ " + " ".join(command))
    try:
        completed = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    except OSError as exc:
        raise ArduinoCliError(f"Could not run arduino-cli: {exc}") from None
    result = CommandResult(
        args=list(command),
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )

    if not result.ok:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise ArduinoCliError(
            f"arduino-cli {' '.join(args[:2])} failed (exit code {result.returncode}).",
            hint="arduino-cli reported:",
            hint_lines=lines[-12:] or ["(no output)"],
        )
    
    return result


def write_sketch(build_dir: Union[str, Path], name: str, cpp: str) -> Path:
    sketch_dir = Path(build_dir) / name
    sketch_dir.mkdir(parents=True, exist_ok=True)
    sketch_file = sketch_dir / f"{name}.ino"
    sketch_file.write_text(cpp, encoding="utf-8")

    return sketch_dir


def compile_sketch(
    sketch_dir: Union[str, Path],
    fqbn: str,
    *,
    arduino_cli: Optional[str] = None,
    verbose: bool = False,
    build_path: Optional[Union[str, Path]] = None,
) -> CommandResult:
    args = ["compile", "--fqbn", fqbn]
    if build_path:
        args += ["--build-path", str(build_path)]
    if verbose:
        args.append("--verbose")
    args.append(str(sketch_dir))

    return run(args, executable=find_arduino_cli(arduino_cli), verbose=verbose)


def upload_sketch(
    sketch_dir: Union[str, Path],
    fqbn: str,
    port: str,
    *,
    arduino_cli: Optional[str] = None,
    verbose: bool = False,
    build_path: Optional[Union[str, Path]] = None,
) -> CommandResult:
    args = ["upload", "--fqbn", fqbn, "--port", port]
    if build_path:
        args += ["--build-path", str(build_path)]
    if verbose:
        args.append("--verbose")
    args.append(str(sketch_dir))

    return run(args, executable=find_arduino_cli(arduino_cli), verbose=verbose)


def list_ports(*, arduino_cli: Optional[str] = None, verbose: bool = False) -> CommandResult:
    return run(["board", "list"], executable=find_arduino_cli(arduino_cli), verbose=verbose)
