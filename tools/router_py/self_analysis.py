from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import sys
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
    todos: list[str] = field(default_factory=list)
    source: str = ""
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

        analysis = FileAnalysis(
            path=relative_path,
            metrics=metrics,
            lint_diagnostics=diagnostics,
            hotspots=hotspots,
            todos=todos,
            source=source,
        )
        analysis.prompt_context = self._build_context(analysis)
        return analysis

    async def suggest_improvements(self, relative_path: str, model: str | None = None) -> str:
        """Generate staged code-review suggestions for the given file."""
        analysis = self.analyze_file(relative_path)
        local_analysis = self._local_analysis_summary(analysis)

        # Stage 1: code map + broad audit + coverage ledger
        stage1_prompt = self._build_staged_review_prompt(analysis)
        stage1_result = await self._run_llm(
            stage1_prompt,
            route_mode="SELF_REVIEW",
            model=model,
        )

        # Stage 2: deep investigation only if warranted
        if self._should_run_deep_dive(stage1_result):
            stage2_prompt = self._build_deep_dive_prompt(analysis, stage1_result)
            stage2_result = await self._run_llm(
                stage2_prompt,
                route_mode="SELF_REVIEW",
                model=model,
            )
            return f"LOCAL analysis:\n{local_analysis}\n\nAUGMENTED suggestions:\n{stage1_result}\n\nDEEP INVESTIGATION:\n{stage2_result}"

        return f"LOCAL analysis:\n{local_analysis}\n\nAUGMENTED suggestions:\n{stage1_result}"

    async def _run_llm(
        self,
        prompt: str,
        route_mode: str = "SELF_REVIEW",
        model: str | None = None,
    ) -> str:
        """Call LocalAnswer and return raw text."""
        try:
            from router_py.local_answer import LocalAnswer, LocalAnswerConfig

            config = LocalAnswerConfig.from_env()
            if model:
                config.model = model
            answer = LocalAnswer(config)
            result = await answer.generate_answer(
                query=prompt,
                route_mode=route_mode,
                output_mode="CHAT",
            )
            await answer.close()
            return result.text
        except ImportError:
            return "AUGMENTED suggestions: unavailable (LocalAnswer not importable)"

    def _should_run_deep_dive(self, stage1_result: str) -> bool:
        """Run deep dive if the first stage reported candidate findings."""
        text = stage1_result.lower()
        # Simple heuristic: presence of confirmed or moderate+ confidence findings.
        confidence_markers = [
            "confidence: confirmed",
            "confidence: high confidence",
            "confidence: moderate confidence",
        ]
        return any(marker in text for marker in confidence_markers)

    def _build_deep_dive_prompt(self, analysis: FileAnalysis, stage1_result: str) -> str:
        context = self._build_context(analysis)
        return f"""You previously reviewed the following code and produced a coverage ledger with candidate findings. Now perform deep investigation and fix planning.

This remains READ-ONLY. Do not edit files or run commands.

## Stage D: Deep investigation

For each candidate finding in the previous report:
- Trace the finding through the relevant call path.
- Identify supporting evidence.
- Distinguish confirmed defects from suspicions.
- Check whether another component already prevents the apparent defect.
- Consider interactions between findings.
- Reject false positives before recommending changes.

## Stage E: Fix planning

For validated findings:
- Rank by severity and likelihood.
- Explain the smallest safe correction.
- Identify possible regressions.
- Recommend targeted tests.
- Do not modify code unless explicitly asked.

{context}

Previous findings:
{stage1_result}

Begin deep investigation and fix planning.
"""

    def _local_analysis_summary(self, analysis: FileAnalysis) -> str:
        parts = [
            f"File: {analysis.path}",
            f"Lines: {analysis.metrics.get('lines', 0)}",
            f"Functions: {analysis.metrics.get('functions', 0)}",
            f"Classes: {analysis.metrics.get('classes', 0)}",
        ]
        if analysis.hotspots:
            parts.append("Hotspots: " + ", ".join(analysis.hotspots))
        if analysis.todos:
            parts.append("TODOs: " + ", ".join(analysis.todos))
        return "\n".join(parts)

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
        ruff_exe = self._resolve_ruff_executable()
        if ruff_exe is None:
            logger.warning("ruff not found; skipping lint diagnostics")
            return []
        try:
            result = subprocess.run(
                [str(ruff_exe), "check", "--output-format=json", str(file_path)],
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
        except Exception as exc:
            logger.warning(f"ruff check failed: {exc}")
            return []

    def _resolve_ruff_executable(self) -> Path | None:
        """Find the ruff executable.

        Search order:
        1. Project venv: ``<project_root>/ui-v10/.venv/bin/ruff``
        2. Running Python's environment: ``<sys.executable parent>/ruff``
        3. PATH via ``shutil.which("ruff")``
        """
        candidates: list[Path] = []
        # Project venv (where Local Lucy installs its dev tools).
        candidates.append(self.project_root / "ui-v10" / ".venv" / "bin" / "ruff")
        # The Python interpreter currently running this code.
        candidates.append(Path(sys.executable).parent / "ruff")
        # Windows venv layout, in case this code is ever run there.
        candidates.append(self.project_root / "ui-v10" / ".venv" / "Scripts" / "ruff.exe")

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate

        from shutil import which

        ruff_on_path = which("ruff")
        if ruff_on_path:
            return Path(ruff_on_path)
        return None

    def _build_context(self, analysis: FileAnalysis) -> str:
        file_path = self._resolve_file(analysis.path)
        metrics = analysis.metrics
        hotspots = analysis.hotspots
        todos = analysis.todos
        diagnostics = analysis.lint_diagnostics
        source = analysis.source
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
            "Below are static metrics, lint results, hotspots, and the source code (possibly truncated). "
            "Your review must be broad and balanced: cover architecture, maintainability, "
            "readability, safety, and testability. Do not fixate on a single function, class, "
            "or issue. Survey the whole file and address the listed hotspots explicitly.\n\n"
            "Requirements:\n"
            "1. Start with the highest-impact structural issues (e.g., oversized classes/functions, "
            "mixed responsibilities, duplicated logic).\n"
            "2. Address each listed hotspot with a concrete, minimal improvement.\n"
            "3. Include at least one readability or maintainability observation.\n"
            "4. Include at least one safety, error-handling, or edge-case observation.\n"
            "5. If tests are present or missing, include one testing observation.\n"
            "6. For every finding, explain briefly why it matters and propose the smallest change "
            "that fixes it. Do not rewrite entire functions or classes.\n"
            "7. Do not spend more than one sentence describing what the code already does; focus on "
            "what should change and why.\n\n"
            f"{analysis.prompt_context}"
        )

    def _build_staged_review_prompt(self, analysis: FileAnalysis) -> str:
        """Build the first staged-review prompt: map + broad audit + coverage ledger."""
        context = analysis.prompt_context
        return f"""You are a careful code-review assistant. The user has supplied code for review.
This is a READ-ONLY review. Do not edit files, apply patches, run commands, install dependencies, delete files, commit, or push changes unless the user explicitly asks for implementation afterwards.

Follow the staged review below. Coverage must come before depth. Do not allow the first significant issue found to redefine the scope of the review. Complete the broad survey before performing deep analysis.

## Stage A: Code map

Identify the following WITHOUT proposing fixes:
- Major modules or sections
- Classes
- Important functions
- Entry points
- Data flow
- State ownership
- External dependencies
- Security boundaries
- Routing and fallback paths
- Error-handling paths

## Stage B: Broad audit

Inspect the complete supplied scope for:
- Functional correctness
- Logic errors
- Edge cases
- Error handling
- State consistency
- Concurrency or race conditions
- Routing and classifier behaviour
- Security and unsafe execution
- Resource management
- Performance
- Dead or duplicated logic
- Maintainability
- Logging and observability
- Test gaps

## Stage C: Coverage ledger

Produce a structured coverage record. For each major component, state:
- Component name
- Coverage status: complete, partial, or not reviewed
- Reason if partial or not reviewed
- Candidate concerns (or "No material issue identified")

Use conservative confidence labels only: confirmed, high confidence, moderate confidence, low confidence. Do not fabricate numerical confidence values.

## Output format

1. Scope received
2. Architecture summary
3. Coverage ledger
4. Confirmed findings
5. Probable findings requiring verification
6. Rejected or unconfirmed concerns
7. Severity and confidence
8. Recommended corrections
9. Required tests
10. Components not adequately reviewed

Every finding should include: location/component, description, evidence, consequence, triggering conditions, severity, confidence, recommended correction, validation test.

{context}

Begin the staged review.
"""
