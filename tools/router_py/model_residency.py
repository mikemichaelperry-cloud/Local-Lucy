import subprocess
from typing import List

LOCAL_LUCY_MODEL_PREFIXES = ("local-lucy-",)


def list_loaded_ollama_models() -> List[str]:
    try:
        out = subprocess.run(
            ["ollama", "ps"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        lines = out.stdout.strip().splitlines()
        return [line.split()[0] for line in lines[1:] if line.strip()]
    except Exception:
        return []


def get_local_lucy_loaded_models() -> List[str]:
    return [
        m
        for m in list_loaded_ollama_models()
        if any(m.startswith(p) for p in LOCAL_LUCY_MODEL_PREFIXES)
    ]


def assert_single_local_lucy_model(label: str = "") -> None:
    loaded = get_local_lucy_loaded_models()
    if len(loaded) > 1:
        raise RuntimeError(f"{label}: more than one Local Lucy model loaded: {loaded}")
