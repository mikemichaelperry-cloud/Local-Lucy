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
import sys
from pathlib import Path

import numpy as np
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

    def __init__(self, embeddings_path: str | None = None,
                 examples_path: str | None = None,
                 base_model: str | None = None):
        self.device = "cpu"
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
            "AUGMENTED": 0.35,
            "EVIDENCE": 0.30,
            "NEWS": 0.20,
            "TIME": 0.15,
            "WEATHER": 0.20,
        }
        self.time_keywords = [
            "time is it", "current time", "what day is it",
            "timezone", "what date", "how many days until",
            "time in ", "time now", "local time", "what is the time", "time right now",
        ]
        self.weather_keywords = [
            "weather", "forecast", "temperature", "rain", "raining", "snow", "snowing",
            "sunny", "cloudy", "windy", "storm", "humidity", "precipitation",
            "drizzle", "hail", "fog", "mist", "thunder", "lightning",
            "overcast", "barometer", "celsius", "fahrenheit", "uv index",
            "pollen count", "heat index", "wind chill", "current conditions",
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
                self.model = SentenceTransformer(self._base_model, device="cpu")
        finally:
            _tf_logger.setLevel(_orig_level)
            _hf_logger.setLevel(_orig_hf_level)

        self.model.eval()

        logger = logging.getLogger(__name__)

        with open(self._examples_path) as f:
            self.examples = json.load(f)

        try:
            self.embeddings = np.load(self._embeddings_path)
        except FileNotFoundError:
            logger.warning(
                "Embeddings file not found (%s). Building from %d examples — "
                "this will take ~30-60s on first run.",
                self._embeddings_path, len(self.examples),
            )
            self.embeddings = self._build_embeddings_from_examples()
            np.save(self._embeddings_path, self.embeddings)
            logger.info("Saved rebuilt embeddings to %s (%s)", self._embeddings_path, self.embeddings.shape)

        expected_dim = self.model.get_embedding_dimension()
        if self.embeddings.shape[1] != expected_dim:
            logger.warning(
                "Embeddings dimension mismatch: file has %s but model expects %d. "
                "Rebuilding from %d examples...",
                self.embeddings.shape, expected_dim, len(self.examples),
            )
            self.embeddings = self._build_embeddings_from_examples()
            np.save(self._embeddings_path, self.embeddings)
            logger.info(
                "Rebuilt and saved embeddings to %s (%s)",
                self._embeddings_path, self.embeddings.shape,
            )

        self.disambiguation_refs = {}
        for category, texts in _DISAMBIGUATION_REFS.items():
            embs = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            self.disambiguation_refs[category] = embs

        self._initialized = True

        self.creative_verbs = [
            "write", "compose", "craft", "tell", "create", "make up", "imagine",
            "describe", "depict", "portray", "paint", "draw",
        ]
        self.creative_nouns = [
            "story", "poem", "essay", "novel", "fiction", "script", "play", "song",
            "horror", "fantasy", "sci-fi", "romance", "thriller", "mystery",
            "character", "plot", "dialogue", "scene", "chapter",
            "haiku", "limerick", "sonnet",
        ]

    def _encode(self, text: str) -> np.ndarray:
        return self.model.encode(text, convert_to_numpy=True, show_progress_bar=False).reshape(1, -1)

    def _build_embeddings_from_examples(self) -> np.ndarray:
        texts = [ex["query"] for ex in self.examples]
        return self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    def fit(self, examples: list[dict]):
        self.examples = examples
        texts = [ex["query"] for ex in examples]
        print(f"Encoding {len(texts)} examples...")
        self.embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        print(f"Embeddings shape: {self.embeddings.shape}")

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
        return (
            all(s > 0.995 for s in top_k_sims)
            or (max(top_k_sims) - min(top_k_sims) < 0.001)
        )

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
            "rain", "raining", "snow", "snowing", "sunny", "cloudy",
            "windy", "storm", "hail", "fog", "mist", "thunder", "lightning",
            "weather", "humidity", "precipitation", "drizzle",
            "overcast", "barometer", "uv index", "pollen count", "heat index",
            "wind chill", "current conditions",
        ]
        for kw in core_weather:
            if re.search(rf'\b{re.escape(kw)}\b', q_lower):
                return True

        # "forecast" is common in economics, sports, and planning — require a
        # corroborating weather signal before treating it as a weather query.
        if "forecast" in q_lower:
            if any(re.search(rf'\b{re.escape(kw)}\b', q_lower) for kw in core_weather):
                return True
            if any(ctx in q_lower for ctx in [
                "weather", "temperature", "rain", "snow", "sunny", "cloudy",
                "storm", "wind", "humidity", "precipitation",
            ]):
                return True

        # Temperature words require corroborating weather context
        temperature_words = [
            "hot", "cold", "freezing", "warm", "chilly", "scorching",
            "sweltering", "frigid", "brisk", "cool", "mild", "temperate",
        ]
        has_temp = any(re.search(rf'\b{re.escape(kw)}\b', q_lower) for kw in temperature_words)
        if has_temp:
            weather_context = [
                "outside", "outdoor", "weather", "forecast", "today", "tomorrow",
                "tonight", "this week", "this weekend", "right now", "currently",
                "will it", "going to be", "feel like", "high of", "low of",
                "temperature", "degrees", "celsius", "fahrenheit",
            ]
            if any(ctx in q_lower for ctx in weather_context):
                return True

        return False

    def _is_educational_time_query(self, q_lower: str) -> bool:
        """Detect educational queries about time concepts (not current time).

        Requires BOTH a question phrase AND a time concept word to avoid
        false positives on generic questions like 'What is today's news?'.
        """
        question_phrases = [
            "how does", "how do", "explain", "history of", "how it works",
            "how they work", "purpose of", "function of", "structure of",
        ]
        time_concepts = [
            "daylight saving", "time zones", "time zone", "timezone",
            "leap year", "leap second", "calendar", "chronology",
            " Greenwich ", "coordinated universal time", "utc",
            "solar time", "lunar calendar", "gregorian calendar",
        ]
        has_question = any(p in q_lower for p in question_phrases)
        has_time_concept = any(t in q_lower for t in time_concepts)
        return has_question and has_time_concept

    def _is_climate_query(self, q_lower: str) -> bool:
        """Detect climate/climatology queries (not current weather)."""
        climate_phrases = [
            "climate", "climatology", "climate change", "global warming",
            "weather patterns", "weather pattern",
        ]
        return any(p in q_lower for p in climate_phrases)

    def _is_math_query(self, q_lower: str) -> bool:
        stripped = q_lower.strip().rstrip("?").strip()
        if len(stripped) <= 15 and all(c.isdigit() or c.isspace() or c in "+-*/=^." for c in stripped):
            return True
        math_phrases = ["what is", "what's", "calculate", "compute", "solve"]
        return any(p in q_lower for p in math_phrases) and any(c in q_lower for c in "+-*/=1234567890")

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
            "conspiracy", "conspirac", "hoax", "cover-up", "cover up",
            "secret plan", "hidden truth", "they don't want you to know",
            "false flag", "inside job", "mainstream media won't",
            # Specific theories
            "flat earth", "hollow earth", "moon landing fake", "moon hoax",
            "faked moon landing", "9/11 inside job", "9/11 conspiracy",
            "controlled demolition", "jfk assassination conspiracy",
            "chemtrails", "geoengineering",
            "reptilian", "lizard people", "shape-shifting", "shape shifting",
            "ancient aliens", "ancient astronaut", "ancient astronauts",
            "illuminati", "freemason", "bilderberg", "skull and bones",
            "new world order", "deep state", "shadow government",
            "mkultra", "mk-ultra", "montauk", "philadelphia experiment",
            "area 51", "area51", "dreamland", "s4 ", "roswell",
            "haarp", "blue beam", "project blue beam",
            "depopulation", "population control",
            "microchip", "microchips", "track everyone",
            "fema camps", "concentration camps",
            "gun confiscation", "take our guns",
            "pizzagate", "qanon", "q anon", "the storm", "the plan",
            # Fringe entities
            "bigfoot", "sasquatch", "nessie", "loch ness",
            "chupacabra", "mothman", "jersey devil",
            "crystal skull", "atlantis", "lemuria",
            "nibiru", "planet x", "wormwood",
            "pole shift", "magnetic reversal",
            # UFO / alien
            "ufo", "ufos", "unidentified flying", "flying saucer",
            "alien abduction", "abducted by aliens", "grey alien",
            "ancient aliens built", "aliens built the pyramids",
            "aliens among us", "aliens live among", "aliens walking among",
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

    def _filter_policy_false_positives(self, query: str, q_lower: str,
                                       requires_evidence: bool, reason: str,
                                       query_emb: np.ndarray) -> tuple[bool, str]:
        """Filter known policy.py false positives using semantic disambiguation."""
        if not requires_evidence:
            return False, ""

        # Conspiracy/fringe queries: never trigger paid providers
        # (unless genuinely safety-critical medical/vet)
        if self._is_conspiracy_or_fringe_query(q_lower):
            # Veterinary context with conspiracy markers (lizard people, reptilians)
            # is a conspiracy theory, not a pet health query
            if reason == "veterinary_context" and any(c in q_lower for c in ["lizard people", "reptilian", "shape-shift", "shapeshift"]):
                return False, ""
            if reason not in ("medical_context", "medical_body_symptom", "veterinary_context"):
                return False, ""
            # Even for medical: vaccine + depopulation is conspiracy, not medical advice
            if "vaccine" in q_lower and any(c in q_lower for c in ["depopulation", "microchip", "autism", "sterilize", "mind control"]):
                return False, ""
            if "fluoride" in q_lower and any(c in q_lower for c in ["mind control", "poison"]):
                return False, ""

        # Veterinary: "python" matches snake, not programming language
        if reason == "veterinary_context":
            # Fast path: explicit pet health markers override semantic disambiguation
            pet_health_markers = [
                "won't eat", "not eating", "refusing food", "lethargic", "limp",
                "vomit", "vomiting", "diarrhea", "cough", "sneeze", "sneezing",
                "fever", "tired", "itch", "itchy", "scratch", "scratching",
                "hair loss", "losing hair", "weight loss", "swollen", "lump",
                "bump", "tumor", "infection", "infected", "parasite", "worm",
                "flea", "tick", "mite", "surgery", "operation", "treatment",
                "medication", "medicine", "drug", "vaccine", "vaccination",
                "shot", "deworm", "neuter", "spay", "castrate", "vet ",
                "veterinary", "veterinarian", "clinic", "hospital",
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
            health_indicators = ["sick", "ill", "hurt", "pain", "symptom", "treatment", "vet ", "veterinar"]
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
            education_words = ["how do", "how does", "explain", "what is", "what are",
                               "describe", "how it works", "function of", "structure of",
                               "purpose of", "anatomy of", "biology of"]
            symptom_words = ["symptom", "symptoms", "side effect", "side effects", "treatment", "pain", "hurt", "hurts", "sick",
                             "diagnosis", "medication", "doctor", "hospital", "prescription",
                             "feel", "feeling", "not feeling", "feel well", "feel good",
                             "my chest", "my head", "my stomach", "my back", "my throat",
                             "i have", "i am", "i'm", "suffering", "experiencing",
                             "aspirin", "ibuprofen", "amoxicillin", "metformin", "insulin",
                             "warfarin", "lipitor", "omeprazole", "lisinopril", "amlodipine",
                             "albuterol", "prednisone", "antibiotics", "antidepressant",
                             "dosage", "dose", "contraindication", "overdose", "poisoning",
                             "allergy", "allergic", "reaction", "adverse",
                             # Drug interactions and medications
                             "interaction", "interactions", "drug interaction",
                             "tadalafil", "cialis", "viagra", "sildenafil",
                             "grapefruit", "grapefruit juice",
                             # Infectious diseases and pandemics
                             "covid", "coronavirus", "flu", "influenza", "pandemic",
                             "epidemic", "outbreak", "infection", "infectious",
                             "virus", "viral", "bacteria", "bacterial",
                             "malaria", "tuberculosis", "tb ", "hepatitis", "meningitis",
                             "pneumonia", "bronchitis", "hiv", "aids", "std", "sti",
                             # Public health
                             "vaccine", "vaccination", "immunization", "booster",
                             "quarantine", "isolation", "lockdown", "social distancing",
                             "mask", "masks", "ppe", "sanitizer",
                             "death toll", "mortality rate", "case fatality",
                             "r-naught", "r0", "reproduction number",
                             "herd immunity", "breakthrough infection",
                             "long covid", "post-covid", "variant", "strain",
                             "delta", "omicron", "alpha", "beta", "gamma"]
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
                "war", "conflict", "military", "invasion", "airstrike",
                "hostage", "evacuation", "sanctions", "ceasefire",
                "terrorist", "bombing", "shooting", "missile", "rocket",
                "troops", "army", "navy", "air force",
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
                route="LOCAL", intent_family="local_answer",
                confidence=1.0, guards_fired=["empty_query"],
            )

        q_lower = query.lower()

        if self._is_creative_writing(q_lower):
            return self._result(
                route="LOCAL", intent_family="local_answer",
                confidence=1.0, guards_fired=["creative_writing"],
            )

        # Lightweight fringe/conspiracy guard: high-precision keyword for queries
        # that should never leave LOCAL (e.g. "Denver Airport conspiracy",
        # "Moon landing conspiracy", "9/11 conspiracy theory"). This is not a
        # keyword fortress — it catches a single category that embeddings may
        # confuse with location-based routes (TIME, NEWS) due to city names.
        if "conspiracy" in q_lower or "conspiracies" in q_lower:
            return self._result(
                route="LOCAL", intent_family="local_answer",
                confidence=1.0, guards_fired=["fringe_topic"],
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

        from collections import Counter
        intent_votes = Counter()
        route_votes = Counter()
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
                route="LOCAL", intent_family="local_answer",
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
            top_k_neighbours.append({
                "query": ex.get("query", "")[:80],
                "route": ex["labels"].get("route", "UNKNOWN"),
                "intent": ex["labels"].get("intent_family", "unknown"),
                "similarity": round(float(similarities[idx]), 4),
            })

        # Keyword catches BEFORE confidence fallback (explicit user signals)
        if self._is_math_query(q_lower):
            guards_fired.append("math_query")
            return self._result(
                route="LOCAL", intent_family="local_answer",
                confidence=round(float(avg_sim), 4),
                embedding_route=best_route, embedding_intent=best_intent,
                top_k_neighbours=top_k_neighbours,
                guards_fired=guards_fired,
            )

        if self._is_time_query(q_lower) and not self._is_educational_time_query(q_lower):
            guards_fired.append("time_keyword")
            return self._result(
                route="TIME", intent_family="time_query",
                confidence=round(float(avg_sim), 4),
                embedding_route=best_route, embedding_intent=best_intent,
                top_k_neighbours=top_k_neighbours,
                guards_fired=guards_fired, ephemeral=True,
            )

        if self._is_weather_query(q_lower) and not self._is_climate_query(q_lower):
            # Non-earth weather (Mars, Jupiter, etc.) and historical weather
            # are general knowledge, not live weather data.
            non_earth = any(p in q_lower for p in [
                "mars", "venus", "jupiter", "saturn", "neptune", "uranus",
                "pluto", "mercury", "titan", "europa", "moon ", "lunar ",
            ])
            historical_weather = any(p in q_lower for p in [
                "in 19", "in 200", "in 201", "was the weather", "used to be",
                "historical weather", "weather during", "weather in ancient",
            ])
            if non_earth or historical_weather:
                guards_fired.append("non_earth_weather")
                return self._result(
                    route="LOCAL", intent_family="local_answer",
                    confidence=round(float(avg_sim), 4),
                    embedding_route=best_route, embedding_intent=best_intent,
                    top_k_neighbours=top_k_neighbours,
                    guards_fired=guards_fired,
                )
            guards_fired.append("weather_keyword")
            return self._result(
                route="WEATHER", intent_family="ephemeral_query",
                confidence=round(float(avg_sim), 4),
                embedding_route=best_route, embedding_intent=best_intent,
                top_k_neighbours=top_k_neighbours,
                guards_fired=guards_fired, ephemeral=True,
            )

        # Sports result catch — embedding sometimes misses major sporting events
        sports_events = ["world cup", "olympics", "super bowl", "championship", "final",
                         "nba finals", "stanley cup", "grand prix", "tournament"]
        if any(e in q_lower for e in sports_events) and ("won" in q_lower or "who won" in q_lower or "score" in q_lower or "result" in q_lower):
            guards_fired.append("sports_event")
            return self._result(
                route="NEWS", intent_family="news_request",
                confidence=round(float(avg_sim), 4),
                embedding_route=best_route, embedding_intent=best_intent,
                top_k_neighbours=top_k_neighbours,
                guards_fired=guards_fired, ephemeral=True,
            )

        # News catch for explicit current-event phrasing.
        # Skip if the query is clearly historical (year, "ancient", "historical",
        # "what was") — the embedding router should handle historical routing.
        historical_markers = [
            "in 19", "in 18", "in 17", "in 16", "in 200", "in 1500",
            "ancient", "medieval", "historical", "what was", "what were",
            "describe the", "history of",
        ]
        if any(m in q_lower for m in historical_markers):
            pass  # Let embedding router decide
        else:
            current_event_phrases = [
                "what happened yesterday", "what happened today", "what happened recently",
                "what is happening", "what's happening", "current events", "latest events",
                "recent events", "breaking news", "latest news", "news today",
                "what's going on", "what is going on",
                "drone strikes", "airstrikes", "air strikes",
                "death toll", "casualties", "civilian casualties",
                "situation report", "sitrep", "battlefield update",
                "developments in", "latest developments", "recent developments",
                "ai developments", "tech developments", "technology developments",
            ]
            if any(p in q_lower for p in current_event_phrases):
                guards_fired.append("current_event_news")
                return self._result(
                    route="NEWS", intent_family="news_request",
                    confidence=round(float(avg_sim), 4),
                    embedding_route=best_route, embedding_intent=best_intent,
                    top_k_neighbours=top_k_neighbours,
                    guards_fired=guards_fired, ephemeral=True,
                )

        # Legal keyword catch for phrasings policy.py misses
        legal_terms = ["is it legal", "legality of", "law regarding", "illegal", "legal in"]
        if any(t in q_lower for t in legal_terms):
            guards_fired.append("legal_keyword")
            return self._result(
                route="AUGMENTED", intent_family="current_evidence",
                confidence=round(float(avg_sim), 4),
                embedding_route=best_route, embedding_intent=best_intent,
                top_k_neighbours=top_k_neighbours,
                guards_fired=guards_fired,
            )

        # Stage 3: Calibrated confidence fallback
        # Per-route thresholds: some routes are safer to trust than others
        safety_critical_reasons = {
            "medical_context", "medical_body_symptom", "veterinary_context",
            "legal_context", "financial_data",
        }
        is_safety_critical = evidence_reason in safety_critical_reasons

        # Safety-critical evidence NEVER falls back to LOCAL regardless of confidence
        threshold = self.route_confidence_thresholds.get(best_route, 0.25)
        if (avg_sim < threshold or top1_sim < 0.20) and not requires_evidence:
            return self._result(
                route="LOCAL", intent_family="local_answer",
                confidence=round(float(avg_sim), 4),
                embedding_route=best_route, embedding_intent=best_intent,
                top_k_neighbours=top_k_neighbours,
                guards_fired=["low_confidence_fallback"],
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
                "fall of", "siege of", "battle of", "war of", "treaty of",
                "rise of", "conference of", "revolution of", "invasion of",
                "history of", "historical", "in 19", "in 18", "in 17", "in 16",
                "ancient", "medieval", "renaissance", "century", "empire",
                "dynasty", "civilization", "reign of", "era of", "period of",
            ]
            if any(m in q_lower for m in historical_markers):
                guards_fired.append("historical_event_time_override")
                best_route = "LOCAL"
                best_intent = "local_answer"

        # Default: trust embedding
        ephemeral = best_intent == "ephemeral_query" or best_route in ("WEATHER", "TIME", "NEWS")

        result = self._result(
            route=best_route, intent_family=best_intent,
            confidence=round(float(avg_sim), 4),
            embedding_route=best_route, embedding_intent=best_intent,
            top_k_neighbours=top_k_neighbours,
            guards_fired=guards_fired, ephemeral=ephemeral,
        )

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
        ("What is the capital of France?", "LOCAL"),
        ("How do I bake sourdough bread?", "LOCAL"),
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
        print(f"  {status} {q:50s} -> {actual:12s} (expected {expected:12s}) conf={result['confidence']:.3f} guards={result['guards_fired']}")

    print(f"\nAccuracy: {correct}/{len(test_queries)} ({100*correct/len(test_queries):.0f}%)")


if __name__ == "__main__":
    test()
