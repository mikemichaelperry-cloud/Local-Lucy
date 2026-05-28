"""Local answer module - wrapper to single source of truth.

⚠️  WARNING: This file is a RE-EXPORT WRAPPER ONLY.
Do NOT add logic here. The real implementation lives in:
    tools/router_py/local_answer.py

If you need to change local answer generation, prompt assembly, or
logging behaviour, edit tools/router_py/local_answer.py and let
this wrapper pick it up automatically via backend/__init__.py.
"""
from backend import LocalAnswer, LocalAnswerConfig
__all__ = ['LocalAnswer', 'LocalAnswerConfig']
