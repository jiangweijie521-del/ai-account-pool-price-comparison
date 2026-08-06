import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "启动库存比价.bat"


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        probe = Path(temp_dir) / "py.cmd"
        probe.write_bytes(b"@echo off\r\necho PROBE_PY_ARGS=%*\r\nexit /b 0\r\n")
        environment = os.environ.copy()
        environment["PATH"] = f"{temp_dir};{os.environ['SystemRoot']}\\System32"
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "call", str(LAUNCHER)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input="\n",
            timeout=5,
            check=False,
        )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "PROBE_PY_ARGS=" in output, output
    assert "server.py" in output and "--open" in output, output
    assert "not recognized" not in output and "不是内部或外部命令" not in output, output

    raw = LAUNCHER.read_bytes()
    assert all(byte < 128 for byte in raw), "launcher must stay ASCII-only"
    assert raw.count(b"\n") == raw.count(b"\r\n"), "launcher must use CRLF line endings"
    print("LAUNCHER_TEST_OK: ASCII + CRLF + parsed arguments")


if __name__ == "__main__":
    main()
