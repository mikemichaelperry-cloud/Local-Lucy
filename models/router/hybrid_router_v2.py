#!/usr/bin/env python3
"""Hybrid router: embedding-based intent classification with semantic disambiguation.

Key capabilities:
1. Semantic disambiguation — uses reference embeddings to resolve ambiguities
   (anatomy education vs medical symptoms, programming vs animal, etc.)
2. Per-route confidence calibration — thresholds tuned per route type
3. Multi-signal fusion — combines embedding, policy, and structural signals
4. Context-aware top-k analysis — examines neighbor semantics, not just votes
5. Intelligent ephemeral detection — embedding-primary with minimal keyword catch

Evidence/freshness/safety detection is delegated to policy.py — single source of truth.
STRICT guards remain for safety-critical cases; SOFT guards are replaced with
semantic disambiguation.
"""

import contextlib
import io
import json
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
from policy import requires_evidence_mode


# Reference texts for semantic disambiguation
# These are encoded once at init and used to resolve common ambiguities.
_DISAMBIGUATION_REFS = {
    "anatomy_education": [
        "How do lungs work?",
        "Explain the function of the heart",
        "What does the liver do?",
        "Describe the structure of the kidney",
        "How does the brain process information?",
        "Teach me about the respiratory system",
        "What is the purpose of the spleen?",
    ],
    "medical_symptoms": [
        "My chest hurts",
        "I have a fever and cough",
        "What are the symptoms of flu?",
        "My head is pounding",
        "I feel dizzy and nauseous",
        "Sharp pain in my stomach",
        "I have a rash and itching",
    ],
    "programming": [
        "How do I install Python?",
        "Write a JavaScript function",
        "What is a Python decorator?",
        "How to use numpy arrays",
        "Explain object-oriented programming",
        "Debug this code",
        "How do I set up a virtual environment?",
    ],
    "animal_pet": [
        "My dog is sick",
        "What do rabbits eat?",
        "How to care for a cat",
        "My parrot lost feathers",
        "Veterinary advice for horses",
        "Dog vaccination schedule",
        "Why is my hamster lethargic?",
    ],
    "historical_event": [
        "Who won the Battle of Waterloo?",
        "What caused World War 2?",
        "Tell me about the Roman Empire",
        "When did the Renaissance happen?",
        "History of the Cold War",
        "Ancient Egyptian civilization",
        "The fall of the Berlin Wall",
    ],
    "current_news": [
        "Latest news on Israel",
        "What is happening in Ukraine?",
        "Breaking news today",
        "Current political situation",
        "Today's headlines",
        "Recent developments in Gaza",
        "Live updates on the election",
    ],
    "cooking_recipe": [
        "How do I bake sourdough bread?",
        "Recipe for chocolate cake",
        "How to make pancakes",
        "Best way to cook pasta",
        "Ingredients for pizza dough",
        "How long to roast chicken?",
        "Vegetarian dinner ideas",
    ],
    "chemistry_science": [
        "What is photosynthesis?",
        "Explain chemical bonding",
        "How does fermentation work?",
        "Properties of carbon dioxide",
        "What is an enzyme?",
        "Nuclear fusion process",
        "Acid-base reactions",
    ],
}


class HybridRouterV2:
    """Superior hybrid router: semantic disambiguation + calibrated confidence + multi-signal fusion."""

    def __init__(
        self,
        embeddings_path: str | None = None,
        examples_path: str | None = None,
        base_model: str | None = None,
    ):
        # Auto-select CUDA if available; MiniLM-L6 is tiny (~80 MB) and leaves
        # plenty of headroom on a 12 GB RTX 3060 alongside the 8B q4 LLM.
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._initialized = False

        # Store params for lazy init
        if base_model is None:
            here = Path(__file__).parent.resolve()
            finetuned_path = here / "finetuned_minilm"
            if finetuned_path.exists():
                base_model = str(finetuned_path)
            else:
                base_model = "sentence-transformers/all-MiniLM-L6-v2"
        self._base_model = base_model

        here = Path(__file__).parent.resolve()
        self._examples_path = examples_path or str(here / "comprehensive_examples.json")
        self._embeddings_path = embeddings_path or str(here / "comprehensive_embeddings.npy")

        # Minimal keyword guards — cheap, set up immediately
        self.route_confidence_thresholds = {
            "LOCAL": 0.15,
            "AUGMENTED": 0.25,
            "EVIDENCE": 0.22,
            "NEWS": 0.15,
            "TIME": 0.15,
            "WEATHER": 0.15,
        }

        # Classifier head (optional): learned decision boundary over frozen embeddings.
        self.classifier_head: torch.nn.Module | None = None
        self.classifier_threshold = 0.70
        self.classifier_idx_to_route: dict[int, str] = {}
        self.classifier_route_to_idx: dict[str, int] = {}
        self.classifier_route_to_intent: dict[str, str] = {}

        # Low-confidence fallback: route factual lookups outward instead of LOCAL.
        self._fact_lookup_words_re = re.compile(
            r"^(who|what|when|where|why|how|is|are|was|were|did|does|do|can|could|would|should|will|shall|has|have|had)\b",
            re.IGNORECASE,
        )
        self._fact_lookup_exclusions = frozenset(
            {
                # Local capabilities
                "translate",
                "translation",
                "in arabic",
                "in french",
                "in spanish",
                "in german",
                "in chinese",
                "in japanese",
                "in russian",
                "in italian",
                "code",
                "function",
                "script",
                "program",
                "programming",
                "python",
                "javascript",
                "bash",
                "command",
                "install",
                "debug",
                "compile",
                "error",
                "library",
                "framework",
                "calculate",
                "solve",
                "equation",
                "plus",
                "minus",
                "times",
                "divided by",
                "square root",
                "sum of",
                "product of",
                "story",
                "poem",
                "joke",
                "song",
                "write",
                "creative",
                "opinion",
                "think",
                "should i",
                "best",
                "worst",
                "recommend",
                "my ",
                "your ",
                "our ",
                "you ",
                "yourself",
                "who are you",
                "what are you",
                "who am i",
                "what am i",
                # Covered by other gates
                "weather",
                "forecast",
                "temperature",
                "stock",
                "price",
                "news",
                "headlines",
                "breaking",
            }
        )

        self.time_keywords = [
            "time is it",
            "current time",
            "what day is it",
            "timezone",
            "what date",
            "how many days until",
            "time in ",
            "time now",
            "local time",
            "what is the time",
            "time right now",
        ]
        self.weather_keywords = [
            "weather",
            "forecast",
            "temperature",
            "rain",
            "raining",
            "snow",
            "snowing",
            "sunny",
            "cloudy",
            "windy",
            "storm",
            "humidity",
            "precipitation",
            "drizzle",
            "hail",
            "fog",
            "mist",
            "thunder",
            "lightning",
            "overcast",
            "barometer",
            "celsius",
            "fahrenheit",
            "uv index",
            "pollen count",
            "heat index",
            "wind chill",
            "current conditions",
        ]

    def _lazy_init(self) -> None:
        """Load model, examples, embeddings, and disambiguation refs on first use."""
        if self._initialized:
            return

        _debug = os.environ.get("LUCY_DEBUG_TRANSFORMERS", "").lower() in {"1", "true", "yes"}
        _tf_logger = logging.getLogger("transformers")
        _hf_logger = logging.getLogger("huggingface_hub")
        _orig_level = _tf_logger.level
        _orig_hf_level = _hf_logger.level
        if not _debug:
            _tf_logger.setLevel(logging.ERROR)
            _hf_logger.setLevel(logging.ERROR)

        try:
            with contextlib.redirect_stdout(io.StringIO() if not _debug else sys.stdout):
                try:
                    self.model = SentenceTransformer(self._base_model, device=self.device)
                except (torch.OutOfMemoryError, RuntimeError) as exc:
                    if self.device == "cuda" and "CUDA out of memory" in str(exc):
                        logger = logging.getLogger(__name__)
                        logger.warning(
                            "CUDA OOM loading router on %s; falling back to CPU. "
                            "This is safe but slightly slower.",
                            self.device,
                        )
                        torch.cuda.empty_cache()
                        self.device = "cpu"
                        self.model = SentenceTransformer(self._base_model, device="cpu")
                    else:
                        raise
        finally:
            _tf_logger.setLevel(_orig_level)
            _hf_logger.setLevel(_orig_hf_level)

        self.model.eval()

        logger = logging.getLogger(__name__)

        with open(self._examples_path) as f:
            raw_examples = json.load(f)

        self.examples = self._validate_examples(raw_examples)

        try:
            self.embeddings = np.load(self._embeddings_path)
        except FileNotFoundError:
            logger.warning(
                "Embeddings file not found (%s). Building from %d examples — "
                "this will take ~30-60s on first run.",
                self._embeddings_path,
                len(self.examples),
            )
            self.embeddings = self._build_embeddings_from_examples()
            np.save(self._embeddings_path, self.embeddings)
            logger.info(
                "Saved rebuilt embeddings to %s (%s)", self._embeddings_path, self.embeddings.shape
            )

        expected_dim = self.model.get_embedding_dimension()
        if self.embeddings.shape[1] != expected_dim:
            logger.warning(
                "Embeddings dimension mismatch: file has %s but model expects %d. "
                "Rebuilding from %d examples...",
                self.embeddings.shape,
                expected_dim,
                len(self.examples),
            )
            self.embeddings = self._build_embeddings_from_examples()
            np.save(self._embeddings_path, self.embeddings)
            logger.info(
                "Rebuilt and saved embeddings to %s (%s)",
                self._embeddings_path,
                self.embeddings.shape,
            )

        if self.embeddings.shape[0] != len(self.examples):
            logger.warning(
                "Embeddings count mismatch: file has %d rows but examples has %d. "
                "Rebuilding from %d examples...",
                self.embeddings.shape[0],
                len(self.examples),
                len(self.examples),
            )
            self.embeddings = self._build_embeddings_from_examples()
            np.save(self._embeddings_path, self.embeddings)
            logger.info(
                "Rebuilt and saved embeddings to %s (%s)",
                self._embeddings_path,
                self.embeddings.shape,
            )

        self.disambiguation_refs = {}
        for category, texts in _DISAMBIGUATION_REFS.items():
            embs = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            self.disambiguation_refs[category] = embs

        self._load_classifier_head()

        self._initialized = True

        self.creative_verbs = [
            "write",
            "compose",
            "craft",
            "tell",
            "create",
            "make up",
            "imagine",
            "describe",
            "depict",
            "portray",
            "paint",
            "draw",
        ]
        self.creative_nouns = [
            "story",
            "poem",
            "essay",
            "novel",
            "fiction",
            "script",
            "play",
            "song",
            "horror",
            "fantasy",
            "sci-fi",
            "romance",
            "thriller",
            "mystery",
            "character",
            "plot",
            "dialogue",
            "scene",
            "chapter",
            "haiku",
            "limerick",
            "sonnet",
        ]

    def _encode(self, text: str) -> np.ndarray:
        return np.asarray(
            self.model.encode(text, convert_to_numpy=True, show_progress_bar=False)
        ).reshape(1, -1)

    def _build_embeddings_from_examples(self) -> np.ndarray:
        texts = [ex["query"] for ex in self.examples]
        return np.asarray(
            self.model.encode(
                texts,
                convert_to_numpy=True,
                show_progress_bar=False,
                batch_size=64,
            )
        )

    def _validate_examples(self, examples: list[dict]) -> list[dict]:
        """Reject empty, blank, or structurally invalid training examples.

        Empty queries pollute the embedding space: a zero-length string
        encodes to the model's [CLS] token embedding, which can spuriously
        match unrelated queries with high similarity and misroute them.
        """
        logger = logging.getLogger(__name__)
        valid: list[dict] = []
        rejected = 0
        for i, ex in enumerate(examples):
            if not isinstance(ex, dict):
                logger.warning("[ROUTER_VALIDATE] Rejected example %d: not a dict", i)
                rejected += 1
                continue
            query = str(ex.get("query", "")).strip()
            if not query:
                logger.warning("[ROUTER_VALIDATE] Rejected example %d: empty/blank query", i)
                rejected += 1
                continue
            labels = ex.get("labels")
            if not isinstance(labels, dict):
                logger.warning("[ROUTER_VALIDATE] Rejected example %d: missing labels", i)
                rejected += 1
                continue
            if not labels.get("route"):
                logger.warning("[ROUTER_VALIDATE] Rejected example %d: missing route label", i)
                rejected += 1
                continue
            # Correct known mislabels that survive data-generation pipelines
            q_lower = query.lower()
            if q_lower == "what is python?" and labels.get("route") == "WEATHER":
                logger.warning(
                    "[ROUTER_VALIDATE] Corrected mislabeled example %d: '%s' WEATHER -> LOCAL",
                    i,
                    query,
                )
                labels["route"] = "LOCAL"
                labels["intent_family"] = "local_answer"
                labels["evidence_mode"] = "not_required"
            valid.append(ex)
        if rejected:
            logger.info(
                "[ROUTER_VALIDATE] Loaded %d valid examples, rejected %d invalid",
                len(valid),
                rejected,
            )
        return valid

    def fit(self, examples: list[dict], batch_size: int = 64):
        self._lazy_init()
        self.examples = examples
        texts = [ex["query"] for ex in examples]
        print(f"Encoding {len(texts)} examples...")
        # Batch encoding avoids GPU OOM when the model shares VRAM with the
        # local LLM / other runtime services.
        self.embeddings = self.model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=batch_size,
        )
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print(f"Embeddings shape: {self.embeddings.shape}")

    def _load_classifier_head(self) -> None:
        """Load a trained Linear/MLP classifier head over frozen embeddings.

        If the head files are missing or malformed, the router simply falls back
        to pure k-NN.  The head is tiny, so we keep it on the same device as the
        embedding model.
        """
        here = Path(self._examples_path).resolve().parent
        config_path = here / "classifier_head_config.json"
        model_path = here / "classifier_head.pt"
        if not config_path.exists() or not model_path.exists():
            return

        try:
            config = json.loads(config_path.read_text())
            routes = config.get("routes", [])
            self.classifier_idx_to_route = {i: route for i, route in enumerate(routes)}
            self.classifier_route_to_idx = {route: i for i, route in enumerate(routes)}
            self.classifier_threshold = config.get("threshold", self.classifier_threshold)

            # Build a route -> intent_family map from the loaded examples
            route_intent_counts: dict[str, dict[str, int]] = {}
            for ex in self.examples:
                route = ex["labels"]["route"]
                intent = ex["labels"].get("intent_family", "local_answer")
                route_intent_counts.setdefault(route, {}).setdefault(intent, 0)
                route_intent_counts[route][intent] += 1
            self.classifier_route_to_intent = {
                route: max(intents, key=lambda k: intents[k])
                for route, intents in route_intent_counts.items()
            }

            input_dim = config["input_dim"]
            num_classes = config["num_classes"]
            hidden_dim = config.get("hidden_dim")

            if hidden_dim:
                self.classifier_head = torch.nn.Sequential(
                    torch.nn.Linear(input_dim, hidden_dim),
                    torch.nn.ReLU(),
                    torch.nn.Dropout(0.1),
                    torch.nn.Linear(hidden_dim, num_classes),
                )
            else:
                self.classifier_head = torch.nn.Linear(input_dim, num_classes)

            state_dict = torch.load(model_path, map_location=self.device, weights_only=True)
            self.classifier_head.load_state_dict(state_dict)
            self.classifier_head.to(self.device)
            self.classifier_head.eval()
        except Exception as exc:
            logger = logging.getLogger(__name__)
            logger.warning("Failed to load classifier head: %s", exc)
            self.classifier_head = None

    def _classify(self, query_emb: np.ndarray) -> tuple[str, float, dict[str, float]]:
        """Run the classifier head on a single (L2-normalised) query embedding."""
        if self.classifier_head is None:
            raise RuntimeError("Classifier head not loaded")

        norm = np.linalg.norm(query_emb)
        x = torch.tensor(query_emb / (norm + 1e-12), dtype=torch.float32).to(self.device)
        with torch.no_grad():
            logits = self.classifier_head(x)
            probs = F.softmax(logits, dim=-1)[0]
            conf, idx = torch.max(probs, dim=-1)
            route = self.classifier_idx_to_route[int(idx)]
            probs_dict = {
                self.classifier_idx_to_route[i]: float(probs[i]) for i in range(len(probs))
            }
        return route, float(conf), probs_dict

    # -----------------------------------------------------------------------
    # Semantic disambiguation
    # -----------------------------------------------------------------------

    def _semantic_similarity(self, query_emb: np.ndarray, ref_key: str) -> float:
        """Return max cosine similarity between query and reference category."""
        if ref_key not in self.disambiguation_refs:
            return 0.0
        ref_embs = self.disambiguation_refs[ref_key]
        sims = cosine_similarity(query_emb, ref_embs)[0]
        return float(np.max(sims))

    def _disambiguate(self, query_emb: np.ndarray, category_a: str, category_b: str) -> str | None:
        """Return which category the query is semantically closer to, or None if uncertain."""
        sim_a = self._semantic_similarity(query_emb, category_a)
        sim_b = self._semantic_similarity(query_emb, category_b)
        margin = 0.15  # Need 0.15 margin to make a call
        if sim_a > sim_b + margin:
            return category_a
        if sim_b > sim_a + margin:
            return category_b
        return None

    # -----------------------------------------------------------------------
    # Guard helpers
    # -----------------------------------------------------------------------

    def _is_creative_writing(self, q_lower: str) -> bool:
        has_verb = any(v in q_lower for v in self.creative_verbs)
        has_noun = any(n in q_lower for n in self.creative_nouns)
        return has_verb and has_noun

    def _embedding_collapsed(self, top_k_sims: list[float]) -> bool:
        return all(s > 0.995 for s in top_k_sims) or (max(top_k_sims) - min(top_k_sims) < 0.001)

    def _is_time_query(self, q_lower: str) -> bool:
        return any(kw in q_lower for kw in self.time_keywords)

    def _is_weather_query(self, q_lower: str) -> bool:
        """Detect weather queries with contextual disambiguation.

        Core weather signals (rain, snow, storm, etc.) always trigger.
        Temperature words (hot, cold, freezing, etc.) require corroborating
        weather context to avoid false positives on astronomy, history,
        and metaphorical usage (e.g., "How hot is the sun?", "Cold War",
        "Hot new trends in AI").
        """
        import re

        # Core weather signals — unambiguous, always trigger
        core_weather = [
            "rain",
            "raining",
            "snow",
            "snowing",
            "sunny",
            "cloudy",
            "windy",
            "storm",
            "hail",
            "fog",
            "mist",
            "thunder",
            "lightning",
            "weather",
            "humidity",
            "precipitation",
            "drizzle",
            "overcast",
            "barometer",
            "uv index",
            "pollen count",
            "heat index",
            "wind chill",
            "current conditions",
        ]
        for kw in core_weather:
            if re.search(rf"\b{re.escape(kw)}\b", q_lower):
                return True

        # "forecast" is common in economics, sports, and planning — require a
        # corroborating weather signal before treating it as a weather query.
        if "forecast" in q_lower:
            if any(re.search(rf"\b{re.escape(kw)}\b", q_lower) for kw in core_weather):
                return True
            if any(
                ctx in q_lower
                for ctx in [
                    "weather",
                    "temperature",
                    "rain",
                    "snow",
                    "sunny",
                    "cloudy",
                    "storm",
                    "wind",
                    "humidity",
                    "precipitation",
                ]
            ):
                return True

        # Temperature words require corroborating weather context
        temperature_words = [
            "hot",
            "cold",
            "freezing",
            "warm",
            "chilly",
            "scorching",
            "sweltering",
            "frigid",
            "brisk",
            "cool",
            "mild",
            "temperate",
        ]
        has_temp = any(re.search(rf"\b{re.escape(kw)}\b", q_lower) for kw in temperature_words)
        if has_temp:
            weather_context = [
                "outside",
                "outdoor",
                "weather",
                "forecast",
                "today",
                "tomorrow",
                "tonight",
                "this week",
                "this weekend",
                "right now",
                "currently",
                "will it",
                "going to be",
                "feel like",
                "high of",
                "low of",
                "temperature",
                "degrees",
                "celsius",
                "fahrenheit",
            ]
            if any(ctx in q_lower for ctx in weather_context):
                return True

        return False

    def _is_factual_lookup_query(self, query: str) -> bool:
        """Detect factual who/what/when/where/why lookups that should not stay LOCAL.

        Returns True if the query starts with a factual question word and does
        not contain terms that are explicit local capabilities (translation,
        coding, math, creative, opinion/advice, personal/meta) or already
        handled by another gate (weather, finance, news).
        """
        if not self._fact_lookup_words_re.search(query):
            return False
        q_lower = query.lower()
        return not any(exc in q_lower for exc in self._fact_lookup_exclusions)

    def _is_educational_time_query(self, q_lower: str) -> bool:
        """Detect educational queries about time concepts (not current time).

        Requires BOTH a question phrase AND a time concept word to avoid
        false positives on generic questions like 'What is today's news?'.
        """
        question_phrases = [
            "how does",
            "how do",
            "explain",
            "history of",
            "how it works",
            "how they work",
            "purpose of",
            "function of",
            "structure of",
        ]
        time_concepts = [
            "daylight saving",
            "time zones",
            "time zone",
            "timezone",
            "leap year",
            "leap second",
            "calendar",
            "chronology",
            " Greenwich ",
            "coordinated universal time",
            "utc",
            "solar time",
            "lunar calendar",
            "gregorian calendar",
        ]
        has_question = any(p in q_lower for p in question_phrases)
        has_time_concept = any(t in q_lower for t in time_concepts)
        return has_question and has_time_concept

    def _is_climate_query(self, q_lower: str) -> bool:
        """Detect climate/climatology queries (not current weather)."""
        climate_phrases = [
            "climate",
            "climatology",
            "climate change",
            "global warming",
            "weather patterns",
            "weather pattern",
        ]
        return any(p in q_lower for p in climate_phrases)

    def _is_math_query(self, q_lower: str) -> bool:
        stripped = q_lower.strip().rstrip("?").strip()
        if len(stripped) <= 15 and all(
            c.isdigit() or c.isspace() or c in "+-*/=^." for c in stripped
        ):
            return True
        math_phrases = ["what is", "what's", "calculate", "compute", "solve"]
        return any(p in q_lower for p in math_phrases) and any(
            c in q_lower for c in "+-*/=1234567890"
        )

    # -----------------------------------------------------------------------
    # Conspiracy / fringe context filter
    # -----------------------------------------------------------------------

    @staticmethod
    def _is_conspiracy_or_fringe_query(q_lower: str) -> bool:
        """Detect conspiracy theory, fringe belief, or pseudoscience queries.

        These should route LOCAL and not trigger paid providers for
        source/evidence/financial lookups.
        """
        conspiracy_markers = [
            # Core conspiracy language
            "conspiracy",
            "conspirac",
            "hoax",
            "cover-up",
            "cover up",
            "secret plan",
            "hidden truth",
            "they don't want you to know",
            "false flag",
            "inside job",
            "mainstream media won't",
            # Specific theories
            "flat earth",
            "hollow earth",
            "moon landing fake",
            "moon hoax",
            "faked moon landing",
            "9/11 inside job",
            "9/11 conspiracy",
            "controlled demolition",
            "jfk assassination conspiracy",
            "chemtrails",
            "geoengineering",
            "reptilian",
            "lizard people",
            "shape-shifting",
            "shape shifting",
            "ancient aliens",
            "ancient astronaut",
            "ancient astronauts",
            "illuminati",
            "freemason",
            "bilderberg",
            "skull and bones",
            "new world order",
            "deep state",
            "shadow government",
            "mkultra",
            "mk-ultra",
            "montauk",
            "philadelphia experiment",
            "area 51",
            "area51",
            "dreamland",
            "s4 ",
            "roswell",
            "haarp",
            "blue beam",
            "project blue beam",
            "depopulation",
            "population control",
            "microchip",
            "microchips",
            "track everyone",
            "fema camps",
            "concentration camps",
            "gun confiscation",
            "take our guns",
            "pizzagate",
            "qanon",
            "q anon",
            "the storm",
            "the plan",
            # Fringe entities
            "bigfoot",
            "sasquatch",
            "nessie",
            "loch ness",
            "chupacabra",
            "mothman",
            "jersey devil",
            "crystal skull",
            "atlantis",
            "lemuria",
            "nibiru",
            "planet x",
            "wormwood",
            "pole shift",
            "magnetic reversal",
            # UFO / alien
            "ufo",
            "ufos",
            "unidentified flying",
            "flying saucer",
            "alien abduction",
            "abducted by aliens",
            "grey alien",
            "ancient aliens built",
            "aliens built the pyramids",
            "aliens among us",
            "aliens live among",
            "aliens walking among",
        ]
        if any(m in q_lower for m in conspiracy_markers):
            return True

        # Compound markers (both parts must be present)
        compound_markers = [
            ("federal reserve", "aliens"),
            ("federal reserve", "rothschild"),
            ("vaccines", "depopulation"),
            ("vaccines", "microchip"),
            ("vaccines", "autism"),
            ("vaccines", "sterilize"),
            ("fluoride", "mind control"),
            ("fluoride", "poison"),
            ("bill gates", "vaccine"),
            ("george soros", "control"),
            ("rockefeller", "plan"),
            ("rothschild", "bank"),
            ("5g", "radiation"),
            ("5g", "towers"),
        ]
        for a, b in compound_markers:
            if a in q_lower and b in q_lower:
                return True

        return False

    # -----------------------------------------------------------------------
    # Policy false-positive filters with semantic disambiguation
    # -----------------------------------------------------------------------

    def _filter_policy_false_positives(
        self, query: str, q_lower: str, requires_evidence: bool, reason: str, query_emb: np.ndarray
    ) -> tuple[bool, str]:
        """Filter known policy.py false positives using semantic disambiguation."""
        if not requires_evidence:
            return False, ""

        # Conspiracy/fringe queries: never trigger paid providers
        # (unless genuinely safety-critical medical/vet)
        if self._is_conspiracy_or_fringe_query(q_lower):
            # Veterinary context with conspiracy markers (lizard people, reptilians)
            # is a conspiracy theory, not a pet health query
            if reason == "veterinary_context" and any(
                c in q_lower for c in ["lizard people", "reptilian", "shape-shift", "shapeshift"]
            ):
                return False, ""
            if reason not in ("medical_context", "medical_body_symptom", "veterinary_context"):
                return False, ""
            # Even for medical: vaccine + depopulation is conspiracy, not medical advice
            if "vaccine" in q_lower and any(
                c in q_lower
                for c in ["depopulation", "microchip", "autism", "sterilize", "mind control"]
            ):
                return False, ""
            if "fluoride" in q_lower and any(c in q_lower for c in ["mind control", "poison"]):
                return False, ""

        # Veterinary: "python" matches snake, not programming language
        if reason == "veterinary_context":
            # Fast path: explicit pet health markers override semantic disambiguation
            pet_health_markers = [
                "won't eat",
                "not eating",
                "refusing food",
                "lethargic",
                "limp",
                "vomit",
                "vomiting",
                "diarrhea",
                "cough",
                "sneeze",
                "sneezing",
                "fever",
                "tired",
                "itch",
                "itchy",
                "scratch",
                "scratching",
                "hair loss",
                "losing hair",
                "weight loss",
                "swollen",
                "lump",
                "bump",
                "tumor",
                "infection",
                "infected",
                "parasite",
                "worm",
                "flea",
                "tick",
                "mite",
                "surgery",
                "operation",
                "treatment",
                "medication",
                "medicine",
                "drug",
                "vaccine",
                "vaccination",
                "shot",
                "deworm",
                "neuter",
                "spay",
                "castrate",
                "vet ",
                "veterinary",
                "veterinarian",
                "clinic",
                "hospital",
            ]
            has_pet_health = any(m in q_lower for m in pet_health_markers)
            # If there are explicit pet health markers, trust policy (it's a real vet query)
            if has_pet_health:
                return requires_evidence, reason  # Keep policy's decision

            winner = self._disambiguate(query_emb, "programming", "animal_pet")
            if winner == "programming":
                return False, ""
            # General pet knowledge without health context
            pet_knowledge = ["breed", "breeds", "origin", "history", "species", "domesticated"]
            health_indicators = [
                "sick",
                "ill",
                "hurt",
                "pain",
                "symptom",
                "treatment",
                "vet ",
                "veterinar",
            ]
            has_health = any(h in q_lower for h in health_indicators)
            has_knowledge = any(k in q_lower for k in pet_knowledge)
            if has_knowledge and not has_health:
                return False, ""

        # Medical: anatomy education vs health concern
        if reason in ("medical_context", "medical_body_symptom"):
            winner = self._disambiguate(query_emb, "anatomy_education", "medical_symptoms")
            if winner == "anatomy_education":
                return False, ""
            # Additional check: if query contains "work", "function", "structure"
            # and no symptom words, it's likely anatomy education
            education_words = [
                "how do",
                "how does",
                "explain",
                "what is",
                "what are",
                "describe",
                "how it works",
                "function of",
                "structure of",
                "purpose of",
                "anatomy of",
                "biology of",
            ]
            symptom_words = [
                "symptom",
                "symptoms",
                "side effect",
                "side effects",
                "treatment",
                "pain",
                "hurt",
                "hurts",
                "sick",
                "diagnosis",
                "medication",
                "doctor",
                "hospital",
                "prescription",
                "feel",
                "feeling",
                "not feeling",
                "feel well",
                "feel good",
                "my chest",
                "my head",
                "my stomach",
                "my back",
                "my throat",
                "i have",
                "i am",
                "i'm",
                "suffering",
                "experiencing",
                "aspirin",
                "ibuprofen",
                "amoxicillin",
                "metformin",
                "insulin",
                "warfarin",
                "lipitor",
                "omeprazole",
                "lisinopril",
                "amlodipine",
                "albuterol",
                "prednisone",
                "antibiotics",
                "antidepressant",
                "dosage",
                "dose",
                "contraindication",
                "overdose",
                "poisoning",
                "allergy",
                "allergic",
                "reaction",
                "adverse",
                # Drug interactions and medications
                "interaction",
                "interactions",
                "drug interaction",
                "tadalafil",
                "cialis",
                "viagra",
                "sildenafil",
                "grapefruit",
                "grapefruit juice",
                # Infectious diseases and pandemics
                "covid",
                "coronavirus",
                "flu",
                "influenza",
                "pandemic",
                "epidemic",
                "outbreak",
                "infection",
                "infectious",
                "virus",
                "viral",
                "bacteria",
                "bacterial",
                "malaria",
                "tuberculosis",
                "tb ",
                "hepatitis",
                "meningitis",
                "pneumonia",
                "bronchitis",
                "hiv",
                "aids",
                "std",
                "sti",
                # Public health
                "vaccine",
                "vaccination",
                "immunization",
                "booster",
                "quarantine",
                "isolation",
                "lockdown",
                "social distancing",
                "mask",
                "masks",
                "ppe",
                "sanitizer",
                "death toll",
                "mortality rate",
                "case fatality",
                "r-naught",
                "r0",
                "reproduction number",
                "herd immunity",
                "breakthrough infection",
                "long covid",
                "post-covid",
                "variant",
                "strain",
                "delta",
                "omicron",
                "alpha",
                "beta",
                "gamma",
            ]
            has_edu = any(w in q_lower for w in education_words)
            has_sym = any(w in q_lower for w in symptom_words)
            if has_edu and not has_sym:
                return False, ""

        # Conflict/news: "latest news" is too broad
        if reason == "conflict_live":
            winner = self._disambiguate(query_emb, "historical_event", "current_news")
            if winner == "historical_event":
                return False, ""
            conflict_specific = [
                "war",
                "conflict",
                "military",
                "invasion",
                "airstrike",
                "hostage",
                "evacuation",
                "sanctions",
                "ceasefire",
                "terrorist",
                "bombing",
                "shooting",
                "missile",
                "rocket",
                "troops",
                "army",
                "navy",
                "air force",
            ]
            if not any(c in q_lower for c in conflict_specific):
                return False, ""

        return requires_evidence, reason

    # -----------------------------------------------------------------------
    # Result builder
    # -----------------------------------------------------------------------

    @staticmethod
    def _result(
        *,
        route: str,
        intent_family: str,
        confidence: float,
        evidence_mode: str = "not_required",
        evidence_reason: str = "",
        embedding_route: str = "",
        embedding_intent: str = "",
        guards_fired: list[str] | None = None,
        ephemeral: bool = False,
        top_k_neighbours: list[dict] | None = None,
    ) -> dict:
        return {
            "intent_family": intent_family,
            "route": route,
            "confidence": round(float(confidence), 4),
            "evidence_mode": evidence_mode,
            "evidence_reason": evidence_reason,
            "embedding_route": embedding_route or route,
            "embedding_intent": embedding_intent or intent_family,
            "top_k_neighbours": top_k_neighbours or [],
            "guards_fired": guards_fired or [],
            "ephemeral": ephemeral,
        }

    # -----------------------------------------------------------------------
    # Main predict — 3 stages with semantic disambiguation
    # -----------------------------------------------------------------------

    def predict(self, query: str, k: int = 3) -> dict:
        self._lazy_init()
        guards_fired: list[str] = []

        # Stage 1: Structural safety
        if not query or not query.strip():
            return self._result(
                route="LOCAL",
                intent_family="local_answer",
                confidence=1.0,
                guards_fired=["empty_query"],
            )

        q_lower = query.lower()

        if self._is_creative_writing(q_lower):
            return self._result(
                route="LOCAL",
                intent_family="local_answer",
                confidence=1.0,
                guards_fired=["creative_writing"],
            )

        # Lightweight fringe/conspiracy guard: high-precision keyword for queries
        # that should never leave LOCAL (e.g. "Denver Airport conspiracy",
        # "Moon landing conspiracy", "9/11 conspiracy theory"). This is not a
        # keyword fortress — it catches a single category that embeddings may
        # confuse with location-based routes (TIME, NEWS) due to city names.
        if "conspiracy" in q_lower or "conspiracies" in q_lower:
            return self._result(
                route="LOCAL",
                intent_family="local_answer",
                confidence=1.0,
                guards_fired=["fringe_topic"],
            )

        # Encode query once — reused for embedding k-NN + semantic disambiguation
        query_emb = self._encode(query)

        # Evidence detection via policy.py + semantic disambiguation
        requires_evidence, evidence_reason = requires_evidence_mode(query)
        requires_evidence, evidence_reason = self._filter_policy_false_positives(
            query, q_lower, requires_evidence, evidence_reason, query_emb
        )

        # Stage 2: Embedding k-NN (primary routing)
        similarities = cosine_similarity(query_emb, self.embeddings)[0]
        top_k_idx = np.argsort(similarities)[-k:][::-1]

        intent_votes: Counter[str] = Counter()
        route_votes: Counter[str] = Counter()
        total_weight = 0.0

        for idx in top_k_idx:
            ex = self.examples[idx]
            labels = ex["labels"]
            weight = similarities[idx] ** 2
            intent_votes[labels["intent_family"]] += weight
            route_votes[labels["route"]] += weight
            total_weight += weight

        top_k_sims = [similarities[idx] for idx in top_k_idx]

        # Embedding collapse sanity check
        if self._embedding_collapsed(top_k_sims):
            return self._result(
                route="LOCAL",
                intent_family="local_answer",
                confidence=round(float(total_weight / k), 4),
                evidence_mode="required" if requires_evidence else "not_required",
                evidence_reason=evidence_reason,
                guards_fired=["embedding_collapse"],
            )

        # Exact-match boost
        top1_sim = similarities[top_k_idx[0]]
        if top1_sim >= 0.999:
            best_intent = self.examples[top_k_idx[0]]["labels"]["intent_family"]
            best_route = self.examples[top_k_idx[0]]["labels"]["route"]
        else:
            best_intent = intent_votes.most_common(1)[0][0]
            best_route = route_votes.most_common(1)[0][0]
        avg_sim = total_weight / k

        # Build top-k neighbour info
        top_k_neighbours = []
        for idx in top_k_idx:
            ex = self.examples[idx]
            top_k_neighbours.append(
                {
                    "query": ex.get("query", "")[:80],
                    "route": ex["labels"].get("route", "UNKNOWN"),
                    "intent": ex["labels"].get("intent_family", "unknown"),
                    "similarity": round(float(similarities[idx]), 4),
                }
            )

        # Classifier-head decision (frozen embeddings, learned boundary).
        # The head is optional; if it is missing or uncertain we fall back to k-NN.
        classifier_route = ""
        classifier_confidence = 0.0
        classifier_probs: dict[str, float] = {}
        if self.classifier_head is not None:
            try:
                classifier_route, classifier_confidence, classifier_probs = self._classify(
                    query_emb
                )
                if classifier_confidence >= self.classifier_threshold:
                    best_route = classifier_route
                    best_intent = self.classifier_route_to_intent.get(classifier_route, best_intent)
                    guards_fired.append("classifier_head")
            except Exception:
                pass

        # Diagnostic confidence signals (k-NN vote distribution)
        route_vote_total = sum(route_votes.values())
        if route_vote_total > 0:
            route_probs = [route_votes[r] / route_vote_total for r in route_votes]
            top2 = sorted(route_probs, reverse=True)[:2]
            confidence_margin = (top2[0] - top2[1]) if len(top2) == 2 else 1.0
            entropy = -sum(p * np.log(p + 1e-12) for p in route_probs)
        else:
            confidence_margin = 0.0
            entropy = 0.0

        # Keyword catches BEFORE confidence fallback (explicit user signals)
        if self._is_math_query(q_lower):
            guards_fired.append("math_query")
            return self._result(
                route="LOCAL",
                intent_family="local_answer",
                confidence=round(float(avg_sim), 4),
                embedding_route=best_route,
                embedding_intent=best_intent,
                top_k_neighbours=top_k_neighbours,
                guards_fired=guards_fired,
            )

        # Sports result catch — embedding sometimes misses major sporting events
        sports_events = [
            "world cup",
            "olympics",
            "super bowl",
            "championship",
            "final",
            "nba finals",
            "stanley cup",
            "grand prix",
            "tournament",
        ]
        if any(e in q_lower for e in sports_events) and (
            "won" in q_lower or "who won" in q_lower or "score" in q_lower or "result" in q_lower
        ):
            guards_fired.append("sports_event")
            return self._result(
                route="NEWS",
                intent_family="news_request",
                confidence=round(float(avg_sim), 4),
                embedding_route=best_route,
                embedding_intent=best_intent,
                top_k_neighbours=top_k_neighbours,
                guards_fired=guards_fired,
                ephemeral=True,
            )

        # Stage 3: Calibrated confidence fallback
        # Per-route thresholds: some routes are safer to trust than others
        safety_critical_reasons = {
            "medical_context",
            "medical_body_symptom",
            "veterinary_context",
            "legal_context",
            "financial_data",
        }
        is_safety_critical = evidence_reason in safety_critical_reasons

        # Safety-critical evidence NEVER falls back to LOCAL regardless of confidence.
        # If the classifier head decided the route, trust its probability instead of
        # the raw k-NN similarity.
        threshold = self.route_confidence_thresholds.get(best_route, 0.25)
        classifier_decided = "classifier_head" in guards_fired and best_route == classifier_route
        if (
            (avg_sim < threshold or top1_sim < 0.20)
            and not requires_evidence
            and not classifier_decided
        ):
            # If the query is a factual lookup, prefer AUGMENTED over LOCAL so we
            # compensate for local-model uncertainty with external sources.
            fallback_route = "AUGMENTED" if self._is_factual_lookup_query(query) else "LOCAL"
            return self._result(
                route=fallback_route,
                intent_family="local_answer" if fallback_route == "LOCAL" else "factual_lookup",
                confidence=round(float(avg_sim), 4),
                embedding_route=best_route,
                embedding_intent=best_intent,
                top_k_neighbours=top_k_neighbours,
                guards_fired=["low_confidence_fallback", "factual_lookup_boost"]
                if fallback_route == "AUGMENTED"
                else ["low_confidence_fallback"],
            )

        # Educational / conceptual override: time/climate/history questions
        # are about stable knowledge, not live data.
        if self._is_educational_time_query(q_lower) and best_route in ("TIME", "NEWS", "AUGMENTED"):
            guards_fired.append("educational_time_override")
            best_route = "LOCAL"
            best_intent = "local_answer"

        if self._is_climate_query(q_lower) and best_route in ("WEATHER", "NEWS", "AUGMENTED"):
            guards_fired.append("climate_knowledge_override")
            best_route = "LOCAL"
            best_intent = "local_answer"

        # Historical event override: embedding sometimes routes historical queries
        # to TIME because they mention cities that also appear in time queries.
        if best_route == "TIME":
            historical_markers = [
                "fall of",
                "siege of",
                "battle of",
                "war of",
                "treaty of",
                "rise of",
                "conference of",
                "revolution of",
                "invasion of",
                "history of",
                "historical",
                "in 19",
                "in 18",
                "in 17",
                "in 16",
                "ancient",
                "medieval",
                "renaissance",
                "century",
                "empire",
                "dynasty",
                "civilization",
                "reign of",
                "era of",
                "period of",
            ]
            if any(m in q_lower for m in historical_markers):
                guards_fired.append("historical_event_time_override")
                best_route = "LOCAL"
                best_intent = "local_answer"

        # Default: trust embedding
        ephemeral = best_intent == "ephemeral_query" or best_route in ("WEATHER", "TIME", "NEWS")

        # Use classifier confidence only when the classifier actually decided the route.
        if "classifier_head" in guards_fired and best_route == classifier_route:
            final_confidence = classifier_confidence
            routing_source = "classifier"
        else:
            final_confidence = avg_sim
            routing_source = "knn"

        result = self._result(
            route=best_route,
            intent_family=best_intent,
            confidence=round(float(final_confidence), 4),
            embedding_route=best_route,
            embedding_intent=best_intent,
            top_k_neighbours=top_k_neighbours,
            guards_fired=guards_fired,
            ephemeral=ephemeral,
        )
        result["classifier_route"] = classifier_route
        result["classifier_confidence"] = round(float(classifier_confidence), 4)
        result["confidence_margin"] = round(float(confidence_margin), 4)
        result["confidence_entropy"] = round(float(entropy), 4)
        result["routing_source"] = routing_source

        # Evidence override for safety-critical queries
        if requires_evidence:
            result["route"] = "AUGMENTED"
            result["evidence_mode"] = "required"
            result["evidence_reason"] = evidence_reason
            result["guards_fired"].append(f"policy_evidence_{evidence_reason}")

        return result


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def test():
    print("Hybrid Router V2 (Superior) Test")
    print("=" * 90)

    router = HybridRouterV2()

    test_queries = [
        ("What are the symptoms of flu?", "AUGMENTED"),
        ("Who was Ada Lovelace?", "LOCAL"),
        ("What time is it in Tokyo?", "TIME"),
        ("Latest news on Israel", "NEWS"),
        ("Write a story about a robot", "LOCAL"),
        ("What is 2+2?", "LOCAL"),
        ("How do I install Python?", "LOCAL"),
        ("Breaking news about earthquake", "NEWS"),
        ("Stock price of Apple", "AUGMENTED"),
        ("Is it legal to ride a bike on the sidewalk?", "AUGMENTED"),
        ("Explain quantum computing", "LOCAL"),
        ("Tell me a joke", "LOCAL"),
        ("What is the treatment for diabetes?", "AUGMENTED"),
        ("Current bitcoin price", "AUGMENTED"),
        ("Latest Supreme Court ruling", "AUGMENTED"),
        ("Who invented the telephone?", "LOCAL"),
        ("What is the capital of France?", "AUGMENTED"),
        ("How do I bake sourdough bread?", "AUGMENTED"),
        ("Translate hello to Japanese", "LOCAL"),
        ("What is CRISPR?", "LOCAL"),
        ("What are the side effects of aspirin?", "AUGMENTED"),
        ("How do I make pancakes?", "LOCAL"),
        ("What is the weather in London?", "WEATHER"),
        ("Current NVIDIA stock price", "AUGMENTED"),
        ("Is weed legal in California?", "AUGMENTED"),
        ("How do lungs work?", "LOCAL"),
        # New semantic disambiguation test cases
        ("What is Python?", "LOCAL"),  # programming, not snake
        ("My python won't eat", "AUGMENTED"),  # snake, vet
        ("How does the heart pump blood?", "LOCAL"),  # anatomy education
        ("My chest feels tight", "AUGMENTED"),  # medical symptom
        ("History of World War 2", "LOCAL"),  # historical
        ("What happened in Gaza today?", "NEWS"),  # current news
        ("How to bake a cake", "LOCAL"),  # cooking
        ("What is fermentation?", "LOCAL"),  # chemistry/science
    ]

    correct = 0
    for q, expected in test_queries:
        result = router.predict(q)
        actual = result["route"]
        status = "✅" if actual == expected else "❌"
        if actual == expected:
            correct += 1
        print(
            f"  {status} {q:50s} -> {actual:12s} (expected {expected:12s}) conf={result['confidence']:.3f} guards={result['guards_fired']}"
        )

    print(f"\nAccuracy: {correct}/{len(test_queries)} ({100 * correct / len(test_queries):.0f}%)")


if __name__ == "__main__":
    test()
