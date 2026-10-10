"""The nested entrypoint must work from an mFruit package's root directory."""

import os
from pathlib import Path
import shutil
import subprocess


def test_wrapper_uses_its_own_app_directory(tmp_path):
    package = tmp_path / "package with spaces"
    chatbot = package / "whisplay-ai-chatbot"
    (chatbot / "dist").mkdir(parents=True)
    script = chatbot / "run_chatbot.sh"
    source = Path(__file__).resolve().parents[2] / "run_chatbot.sh"
    shutil.copy(source, script)
    (chatbot / "dist/index.js").write_text("// fake build\n")
    (chatbot / ".env").write_text("CUSTOM_FONT_PATH=from-package.ttf\n")

    binaries = tmp_path / "bin"
    binaries.mkdir()
    # Avoid the real audio hardware, model services and Node application.
    (binaries / "uname").write_text("#!/bin/sh\necho TestOS\n")
    (binaries / "node").write_text(
        '#!/bin/sh\n[ "$1" = --version ] && exit 0\n'
        'printf "%s\\n%s\\n%s\\n" "$PWD" "$*" "$CUSTOM_FONT_PATH" > "$STARTUP_RESULT"\n')
    for binary in binaries.iterdir():
        binary.chmod(0o755)
    result_file = tmp_path / "result"
    env = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}",
           "NVM_DIR": str(tmp_path / "no-nvm"), "STARTUP_RESULT": str(result_file)}
    env.pop("SERVE_OLLAMA", None)
    result = subprocess.run(["bash", str(script)], cwd=package, env=env,
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result_file.read_text().splitlines() == [str(chatbot), "dist/index.js",
                                                  "from-package.ttf"]
