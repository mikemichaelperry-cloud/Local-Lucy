"""Resolve the effective Ollama model for Code Review / SELF_REVIEW mode."""

import json
import logging
import urllib.request
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CodeReviewModelResolver:
    """Pick a code-review model from the configured fallback chain."""

    config: object  # LocalAnswerConfig-compatible
    ollama_url: str = "http://127.0.0.1:11434/api/tags"

    def resolve(self) -> tuple[str, Optional[str]]:
        """Return (model_name, fallback_reason).

        Fallback chain:
        1. Configured specialist model if enabled and installed.
        2. Existing stock Gemma 4 12B model (gemma4:12b-it-qat).
        3. Normally configured local model.
        4. RuntimeError if nothing is available.
        """
        installed = self._list_installed_models()
        specialist = self.config.code_review_model
        default = self.config.model
        # Prefer the persona-tuned Gemma 4 model; fall back to the raw base tag
        # so code review still works if only the base model has been pulled.
        stock_candidates = ["local-lucy-gemma4", "gemma4:12b-it-qat"]

        if self.config.code_review_specialist_enabled:
            if specialist and specialist in installed:
                logger.info(f"Code-review model selected: {specialist}")
                return specialist, None
            if specialist:
                logger.warning(
                    f"Code-review specialist model {specialist} not installed; "
                    "falling back to stock Gemma 4"
                )

            stock = next((m for m in stock_candidates if m in installed), None)
            if stock:
                return stock, "specialist_model_not_installed"

            if default and default in installed:
                return default, "stock_gemma4_not_installed"
        else:
            stock = next((m for m in stock_candidates if m in installed), None)
            if stock:
                return stock, "specialist_disabled"
            if default and default in installed:
                return default, "specialist_disabled"

        logger.error(
            "No code-review model available. Tried: %s",
            ", ".join(
                filter(
                    None,
                    [
                        specialist if self.config.code_review_specialist_enabled else None,
                        *stock_candidates,
                        default,
                    ],
                )
            ),
        )
        raise RuntimeError(
            "No code-review model available. Install one of: "
            f"{specialist or ''}, {', '.join(stock_candidates)}, {default or ''}"
        )

    def _list_installed_models(self) -> list[str]:
        """Return installed Ollama model names."""
        try:
            req = urllib.request.Request(self.ollama_url, method="GET")
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            # Ollama sometimes returns the name without tag; include both forms.
            expanded = set(models)
            for name in models:
                if ":" in name:
                    expanded.add(name.split(":")[0])
                else:
                    expanded.add(name + ":latest")
            return sorted(expanded)
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
            return []
