"""npm-style task runner for the project, in plain Python (no install needed).

Usage:
    python3 run.py              list the tasks
    python3 run.py build        create .venv and install requirements (once)
    python3 run.py ui           start the Streamlit UI
    python3 run.py chat         start the command-line chat
    python3 run.py api          start the web API for the Lovable UI (http://localhost:8000/docs)
    python3 run.py test-gateway one test call to the LLM gateway

Add your own tasks to TASKS below, like "scripts" in package.json.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

# name: (description, command). "{py}" is replaced by the virtual environment's Python.
TASKS = {
    "build": ("Create .venv and install requirements", None),
    "ui": ("Start the Streamlit UI", "{py} -m streamlit run app.py"),
    "chat": ("Start the command-line chat", "{py} chat.py"),
    "api": ("Start the web API for the Lovable UI", "{py} -m uvicorn api:app --host 0.0.0.0 --port 8000"),
    "test-gateway": ("One test call to the LLM gateway", "{py} llm_client.py"),
}

NEEDS_ENV_FILE = {"ui", "chat", "api", "test-gateway"}


def build() -> int:
    print("Creating virtual environment in .venv ...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip", "-q"], check=True)
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "-r", "requirements.txt"], check=True)
    print("Done. Start the UI with: python3 run.py ui")
    return 0


def list_tasks() -> None:
    print("Tasks:  python3 run.py <task>\n")
    for name, (description, _) in TASKS.items():
        print(f"  {name:<14} {description}")


def main() -> int:
    os.chdir(ROOT)
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        if len(sys.argv) >= 2:
            print(f"Unknown task: {sys.argv[1]}\n")
        list_tasks()
        return 1

    task = sys.argv[1]
    if task == "build":
        return build()

    if not VENV_PY.exists():
        print("No virtual environment yet. Run first: python3 run.py build")
        return 1
    if task in NEEDS_ENV_FILE and not (ROOT / ".env").exists():
        print("No .env file found. Copy .env.example to .env and fill in CLIENT_ID and CLIENT_SECRET.")
        return 1

    command = TASKS[task][1].format(py=f'"{VENV_PY}"')
    extra = " ".join(sys.argv[2:])  # pass-through arguments, like npm run x -- --flag
    try:
        return subprocess.call(f"{command} {extra}".strip(), shell=True)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
