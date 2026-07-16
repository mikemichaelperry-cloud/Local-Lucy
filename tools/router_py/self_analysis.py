from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024


@dataclass
class FileAnalysis:
    path: str
    metrics: dict[str, int] = field(default_factory=dict)
    lint_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    hotspots: list[str] = field(default_factory=list)
    prompt_context: str = ""


class SelfAnalysisEngine:
    def __init__(
        self,
        project_root: Path | None = None,
        self_review_context_chars: int | None = None,
    ) -> None:
        if project_root is None:
            project_root = Path(os.environ.get("LUCY_ROOT", Path.home() / "lucy-v10"))
        self.project_root = Path(project_root).expanduser().resolve()
        if self_review_context_chars is None:
            try:
                from router_py.local_answer import LocalAnswerConfig

                self_review_context_chars = LocalAnswerConfig.from_env().self_review_context_chars
            except (ImportError, AttributeError):
                logger.warning(
                    "LocalAnswerConfig not available; falling back to "
                    "LUCY_SELF_REVIEW_CONTEXT_CHARS for context limit."
                )
                self_review_context_chars = int(
                    os.environ.get("LUCY_SELF_REVIEW_CONTEXT_CHARS", "200000")
                )
        if self_review_context_chars <= 0:
            raise ValueError(
                f"self_review_context_chars must be positive, got {self_review_context_chars}"
            )
        self._self_review_context_chars = self_review_context_chars

    def analyze_file(self, relative_path: str) -> FileAnalysis:
        file_path = self._resolve_file(relative_path)
        source = self._read_source(file_path, relative_path)
        tree = ast.parse(source)

        metrics = self._extract_metrics(tree, source)
        hotspots = self._find_hotspots(tree, source)
        todos = self._find_todos(source)
        diagnostics = self._run_ruff(file_path)
        prompt_context = self._build_context(
            file_path, metrics, hotspots, todos, diagnostics, source
        )

        return FileAnalysis(
            path=relative_path,
            metrics=metrics,
            lint_diagnostics=diagnostics,
            hotspots=hotspots,
            prompt_context=prompt_context,
        )

    async def suggest_improvements(self, relative_path: str, model: str | None = None) -> str:
        """Return improvement suggestions for ``relative_path``.

        This method is async because it awaits ``LocalAnswer.generate_answer``.
        It returns a coroutine that resolves to a formatted ``str``.
        """
        analysis = self.analyze_file(relative_path)
        prompt = self._build_llm_prompt(analysis)

        try:
            from router_py.local_answer import LocalAnswer, LocalAnswerConfig
        except ImportError:
            return f"LOCAL analysis:\n{analysis.prompt_context}\n\nAUGMENTED suggestions: unavailable (LocalAnswer not importable)."

        config = LocalAnswerConfig.from_env()
        if model:
            config.model = model
        answer = LocalAnswer(config)
        try:
            result = await answer.generate_answer(query=prompt, route_mode="SELF_REVIEW")
            return f"LOCAL analysis:\n{analysis.prompt_context}\n\nAUGMENTED suggestions:\n{result.text}"
        except Exception as exc:
            logger.warning(f"Self-analysis LLM call failed: {exc}")
            return f"LOCAL analysis:\n{analysis.prompt_context}\n\nAUGMENTED suggestions: unavailable ({exc})."
        finally:
            await answer.close()

    def _resolve_file(self, relative_path: str) -> Path:
        candidate = self.project_root / relative_path
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError(f"Path escapes project root: {relative_path}") from exc
        if not candidate.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        if not candidate.is_file():
            raise ValueError(f"Not a regular file: {relative_path}")
        if candidate.suffix != ".py":
            raise ValueError(f"Not a Python file: {relative_path}")
        return candidate

    def _read_source(self, file_path: Path, relative_path: str) -> str:
        """Read ``file_path`` with a hard byte cap and tolerant decoding."""
        with file_path.open("rb") as f:
            data = f.read(_MAX_FILE_SIZE_BYTES + 1)
        if len(data) > _MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"File too large for self-analysis ({len(data)} bytes): {relative_path}"
            )
        return data.decode("utf-8", errors="replace")

    def _extract_metrics(self, tree: ast.AST, source: str) -> dict[str, int]:
        lines = source.splitlines()
        functions = [
            n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        return {
            "lines": len(lines),
            "functions": len(functions),
            "classes": len(classes),
            "imports": len(imports),
        }

    def _find_hotspots(self, tree: ast.AST, source: str) -> list[str]:
        hotspots = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = node.lineno
                end = getattr(node, "end_lineno", start)
                length = end - start + 1 if end else 1
                if length > 100:
                    name = node.name
                    kind = (
                        "function"
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        else "class"
                    )
                    hotspots.append(f"{kind} '{name}' at lines {start}-{end} ({length} lines)")
        return hotspots

    def _find_todos(self, source: str) -> list[str]:
        todos = []
        todo_pattern = re.compile(r"#\s*(TODO|FIXME|XXX|HACK)(?:[:\s]+|$)(.*)", re.IGNORECASE)
        for lineno, line in enumerate(source.splitlines(), start=1):
            match = todo_pattern.search(line)
            if match:
                marker = match.group(1).upper()
                text = match.group(2).strip()
                todos.append(
                    f"{marker} on line {lineno}: {text}" if text else f"{marker} on line {lineno}"
                )
        return todos

    def _run_ruff(self, file_path: Path) -> list[dict[str, Any]]:
        try:
            result = subprocess.run(
                ["ruff", "check", "--output-format=json", str(file_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode not in (0, 1):
                logger.warning(
                    f"ruff check unexpected exit: {result.returncode} "
                    f"stderr: {result.stderr.strip()}"
                )
                return []
            return json.loads(result.stdout or "[]")
        except FileNotFoundError:
            logger.warning("ruff not found; skipping lint diagnostics")
            return []
        except Exception as exc:
            logger.warning(f"ruff check failed: {exc}")
            return []

    def _build_context(
        self,
        file_path: Path,
        metrics: dict[str, int],
        hotspots: list[str],
        todos: list[str],
        diagnostics: list[dict[str, Any]],
        source: str,
    ) -> str:
        lines = [
            f"File: {file_path.relative_to(self.project_root)}",
            f"Lines: {metrics['lines']}",
            f"Functions: {metrics['functions']}",
            f"Classes: {metrics['classes']}",
            f"Imports: {metrics['imports']}",
            f"Ruff diagnostics: {len(diagnostics)}",
        ]
        if hotspots:
            lines.append("Hotspots:")
            lines.extend(f"  - {h}" for h in hotspots)
        if todos:
            lines.append("TODOs / FIXMEs:")
            lines.extend(f"  - {t}" for t in todos[:10])
        if diagnostics:
            lines.append("Top diagnostics:")
            for d in diagnostics[:5]:
                lines.append(
                    f"  - {d.get('code', 'lint')}: line {d.get('location', {}).get('row', '?')} — {d.get('message', '')}"
                )
        lines.append("Source code:")
        lines.append("`````python")
        truncated_source = source
        if len(source) > self._self_review_context_chars:
            truncated_source = (
                source[: self._self_review_context_chars]
                + f"\n[truncated at {self._self_review_context_chars} characters; consider reviewing a smaller module]"
            )
        lines.append(truncated_source)
        lines.append("`````")
        return "\n".join(lines)

    def _build_llm_prompt(self, analysis: FileAnalysis) -> str:
        return (
            "You are reviewing Local Lucy's own Python source code. "
            "Below are static metrics, lint results, and the source code (possibly truncated). "
            "Suggest concrete, minimal improvements. Do not rewrite the file.\n\n"
            f"{analysis.prompt_context}"
        )
