#!/usr/bin/env python3
"""Hybrid router: keyword evidence + embedding k-NN for intent.

Stage 1: Keyword-based evidence detection (fast, reliable for medical/financial/legal)
Stage 2: Check for cooking/recipe queries -> force LOCAL
Stage 3: Embedding k-NN for intent classification
Stage 4: Route derived from intent + evidence
"""

import contextlib
import io
import json
import logging
import os
import re
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from transformers import AutoModel, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
from policy import requires_evidence_mode


class HybridRouter:
    """Hybrid router combining keyword evidence + embedding similarity."""

    def __init__(self, embeddings_path: str | None = None,
                 examples_path: str | None = None,
                 base_model: str = "answerdotai/ModernBERT-base"):
        self.device = "cpu"

        # Suppress transformers loading output (tqdm progress bar + LOAD REPORT)
        # Only when not in explicit debug mode.
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
                self.tokenizer = AutoTokenizer.from_pretrained(base_model)
                self.model = AutoModel.from_pretrained(base_model)
        finally:
            _tf_logger.setLevel(_orig_level)
            _hf_logger.setLevel(_orig_hf_level)

        self.model.eval()

        # Resolve data files relative to this module so imports work from any CWD
        here = Path(__file__).parent.resolve()
        examples_path = examples_path or str(here / "comprehensive_examples.json")
        embeddings_path = embeddings_path or str(here / "comprehensive_embeddings.npy")

        logger = logging.getLogger(__name__)

        with open(examples_path) as f:
            self.examples = json.load(f)

        try:
            self.embeddings = np.load(embeddings_path)
        except FileNotFoundError:
            logger.warning(
                "Embeddings file not found (%s). Building from %d examples — "
                "this will take ~30-60s on first run.",
                embeddings_path, len(self.examples),
            )
            self.embeddings = self._build_embeddings_from_examples()
            np.save(embeddings_path, self.embeddings)
            logger.info("Saved rebuilt embeddings to %s (%s)", embeddings_path, self.embeddings.shape)

        # Evidence keywords (must stay in sync with policy.py requires_evidence_mode)
        self.medical_keywords = [
            "symptom", "symptoms", "treatment", "medication", "dosage",
            "side effect", "diagnosis", "disease", "condition", "prescription",
            "vaccine", "pregnancy", "cancer", "diabetes", "blood pressure",
            "cholesterol", "antibiotics", "pain", "headache", "infection",
            "virus", "flu ", "covid", "stroke", "heart attack", "allergy",
            "asthma", "depression", "anxiety", "arthritis", "migraine",
            "epilepsy", "pneumonia", "fracture", "burn", "emergency",
            "hospital", "doctor ", "medicine", "mental health", "therapy",
            "surgery", "operation", "transplant", "biopsy", "scan",
            "blood test", "physical therapy", "diet", "nutrition",
            "vitamin", "supplement", "herbal", "acupuncture", "chiropractic",
            # Body parts + symptoms (NEW)
            "chest", "breath", "breathing", "shortness of breath",
            "fever", "high temperature", "body temperature", "feel good", "not feeling", "feel well", "feeling bad",
            "hypertension", "high blood pressure",
            "unwell", "sick", "nausea", "nauseous", "vomit", "dizzy", "cough", "sneeze",
            "aches", "sore", "swelling", "swollen", "rash", "itchy", "burning",
            "numbness", "tingling", "weakness", "fatigue", "tired", "exhausted",
            "appetite", "weight loss", "weight gain", "bleeding", "bruising", "wound", "cut",
            "chills", "shivering", "dehydration", "seizure", "convulsion", "paralysis",
            "palpitation", "sweating", "hallucination", "delusion", "panic",
            # Pediatric indicators (NEW)
            "baby", "child", "toddler", "infant", "2-year-old", "3-year-old",
            "4-year-old", "5-year-old", "year old", "years old", "my son", "my daughter",
            # Educational medical terms (NEW)
            "insulin", "glucose", "metabolism", "hormone", "enzyme", "protein",
            "cell", "organ", "tissue", "muscle", "bone", "blood", "immune",
        ]
        self.financial_keywords = [
            "stock price", "share price", "bitcoin", "ethereum", "crypto",
            "exchange rate", "interest rate", "market cap", "nasdaq", "nyse",
            "s&p 500", "dow jones", "ftse", "trading at", "earnings",
            "revenue", "profit", "gdp", "inflation rate", "cpi",
            "unemployment rate", "federal reserve", "fed rate", "ecb rate",
            "treasury yield", "bond", "dividend", "portfolio", "investment",
            "forex", "commodity", "gold price", "oil price", "gas price",
            "mortgage rate", "loan rate", "credit score", "debt",
            "retirement", "pension", "401k", "ira", "mutual fund",
            "etf", "hedge fund", "venture capital", "ipo", "merger",
            # Investment and planning (NEW)
            "invest", "investing", "economy", "economic",
            "risk", "return", "roi", "capital gains", "working capital", "capital market", "equity",
            "loan", "mortgage", "refinance", "credit", "bankruptcy",
            "savings", "account", "bank", "credit card",
            "salary", "income", "expense", "budget", "valuation", "worth",
            "net worth", "wealth", "insurance", "premium",
        ]
        self.legal_keywords = [
            "legal to", "court ruling", "supreme court", "tenant rights",
            "statute", "ordinance", "legality of", "law regarding",
            "regulation", "compliance", "penalty for", "is it illegal",
            "can i be sued", "contract law", "copyright", "patent",
            "trademark", "divorce", "custody", "immigration", "visa",
            "green card", "tax law", "labor law", "employment law",
            "discrimination", "warranty", "liability", "negligence",
            "fraud", "theft", "assault", "dui", "speeding ticket",
            "traffic violation", "small claims", "arrested", "charged with",
            "indicted", "subpoena", "deposition", "weed", "cannabis",
            "marijuana", "thc", "cbd", "drug test", "parole", "probation",
            # Licenses and permits (NEW)
            "business license", "license", "permit", "zoning",
            # Immigration and citizenship (NEW)
            "citizenship", "passport", "work permit",
            # Employment law (NEW)
            "harassment", "wrongful termination",
            "nda", "non-compete", "non-disclosure",
            # IP and defamation (NEW)
            "plagiarism", "defamation", "libel", "slander",
            # Litigation and remedies (NEW)
            "contract", "breach", "class action",
            "lawsuit", "settlement", "damages", "injunction",
            "restraining order", "felony", "misdemeanor", "warrant",
            # Family law (NEW)
            "power of attorney", "guardianship", "child support",
            "alimony", "adoption", "wills", "estate", "inheritance",
            "probate", "trust",
            # Business structures (NEW)
            "llc", "incorporation", "partnership", "nonprofit",
            # Tax and audit (NEW)
            "tax", "taxes", "audit", "tax attorney",
            # Courts and appeals (NEW)
            "expert witness", "appeal", "appellate",
            "family court", "attorney general",
            "district attorney", "prosecutor", "defense attorney",
            "legal aid", "habeas corpus",
            # Statutes and constitutional
            "basic law", "constitution", "constitutional", "freedom of speech",
            "human rights", "civil rights", "bill of rights",
            # Vague legal
            "problem with the law", "trouble with the law",
        ]
        self.source_keywords = [
            "source", "cite", "citation", "reference", "evidence",
            "where did you get", "how do you know", "prove that",
            "verify", "fact check", "peer-reviewed", "study", "research paper",
            "clinical trial", "meta-analysis", "systematic review",
            "according to", "who said", "which expert", "official report",
            "wikipedia",
            # Vague source requests
            "evidence for that", "proof", "sources",
        ]
        self.news_keywords = [
            "news", "headlines", "breaking", "latest updates",
            "current events", "what happened", "what's happening",
            # Weather and disaster events
            "hurricane", "earthquake", "flood", "wildfire", "tornado",
            "typhoon", "tsunami", "volcano", "storm", "blizzard",
            # Sports and competitions
            "won the", "final", "championship", "tournament", "match",
            "game", "score", "season", "playoff",
            # Science and discoveries
            "scientific discovery", "discovery", "breakthrough",
            # Politics and elections
            "election", "vote", "poll", "campaign", "debate",
            # General updates
            "update on", "latest on", "development", "developments",
            "trending", "world cup", "olympics", "super bowl", "nba", "nfl", "premier league",
        ]
        self.time_keywords = [
            "time is it", "current time", "what day is it",
            "timezone", "what date", "how many days until",
            "time in ", "time now", "local time", "what is the time", "time right now",
        ]
        # Ephemeral queries change hour-to-hour and should skip memory
        self.ephemeral_keywords = [
            # Weather
            "weather", "forecast", "temperature", "rain", "snow", "sunny",
            "cloudy", "windy", "storm", "humidity", "precipitation",
            "hot", "cold", "warm", "freezing", "chilly", "humid",
            # Real-time prices
            "stock price", "bitcoin price", "crypto price", "current price",
            "price of", "trading at", "market cap", "market price", "markets",
            "exchange rate", "currency rate", "forex",
            # Sports scores
            "score", "who won", "game result", "match result", "final score",
            "live score", "half time", "full time", "overtime",
            # Traffic / transit
            "traffic", "delay", "road closure", "accident on", "congestion",
            "flight status", "departure", "arrival", "gate", "boarding",
            # Election / polls
            "election results", "vote count", "polls closed", "live updates",
        ]
        # Cooking/recipe queries should always be LOCAL
        self.cooking_keywords = [
            "bake", "cook", "recipe", "pancake", "sourdough",
            "bread", "cake", "cookie", "pizza", "pasta",
            "grill", "roast", "fry", "steam", "boil",
            "simmer", "saute", "braise", "poach", "blanch",
            "marinade", "dressing", "sauce", "soup", "stew",
            "salad", "sandwich", "burger", "taco", "sushi",
            "curry", "stir fry", "bbq", "barbecue", "smoke",
            " ferment", "pickle", "preserve", "canning",
            "kitchen", "oven", "stove", "microwave", "air fryer",
            "slow cooker", "instant pot", "pressure cooker",
            "ingredient", "measurement", "tablespoon",
            "teaspoon", "ounce", " gram", " grams", "kilogram", " pound",
            "preheat", "bake at", "cook at",
            "how long to cook", "how to make", "how to prepare",
            "best way to cook", "easy recipe", "quick recipe",
            "healthy recipe", "vegan recipe", "gluten free",
            "keto", "paleo", "low carb", "mediterranean diet",
        ]

    def _encode(self, text: str) -> np.ndarray:
        inputs = self.tokenizer(
            text, return_tensors="pt", truncation=True,
            max_length=256, padding=True,
        )
        import torch
        with torch.no_grad():
            outputs = self.model(**inputs)
        return outputs.last_hidden_state[:, 0, :].cpu().numpy()

    def _build_embeddings_from_examples(self) -> np.ndarray:
        """Batch-encode all training examples to rebuild the embedding matrix."""
        import torch
        texts = [ex["query"] for ex in self.examples]
        batch_size = 16
        embeddings = []
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                inputs = self.tokenizer(
                    batch, return_tensors="pt", truncation=True,
                    max_length=256, padding=True,
                )
                outputs = self.model(**inputs)
                cls = outputs.last_hidden_state[:, 0, :].cpu().numpy()
                embeddings.append(cls)
        return np.vstack(embeddings)

    def predict(self, query: str, k: int = 3) -> dict:
        """Predict route using hybrid approach."""
        # Stage -1: Empty query -> LOCAL
        if not query or not query.strip():
            return {
                "intent_family": "local_answer",
                "route": "LOCAL",
                "confidence": 1.0,
                "evidence_mode": "not_required",
                "evidence_reason": "",
                "embedding_route": "LOCAL",
                "embedding_intent": "local_answer",
            }
        
        q_lower = query.lower()

        # Stage 0: Creative writing guard — fictional/artistic requests are always LOCAL
        # even if they contain medical/financial/legal topic keywords.
        creative_verbs = ["write", "compose", "craft", "tell", "create", "make up", "imagine"]
        creative_nouns = [
            "story", "poem", "essay", "novel", "fiction", "script", "play", "song",
            "horror", "fantasy", "sci-fi", "romance", "thriller", "mystery",
            "character", "plot", "dialogue", "scene", "chapter",
            "haiku", "limerick", "sonnet",
        ]
        has_creative_verb = any(v in q_lower for v in creative_verbs)
        has_creative_noun = any(n in q_lower for n in creative_nouns)
        if has_creative_verb and has_creative_noun:
            return {
                "intent_family": "local_answer",
                "route": "LOCAL",
                "confidence": 1.0,
                "evidence_mode": "not_required",
                "evidence_reason": "creative_writing",
                "embedding_route": "LOCAL",
                "embedding_intent": "local_answer",
            }

        # Stage 1: Fast keyword detection
        requires_evidence = False
        evidence_reason = ""
        for kw in self.medical_keywords:
            if kw in q_lower:
                requires_evidence = True
                evidence_reason = "medical_context"
                break
        if not requires_evidence:
            historical_price = any(kw in q_lower for kw in ["in 19", "in 200", "in 201", "back in", "was the price", "historical", "at its peak", "all time high"])
            for kw in self.financial_keywords:
                if kw in q_lower:
                    if historical_price and kw in ["bitcoin", "stock", "stocks"]:
                        continue
                    requires_evidence = True
                    evidence_reason = "financial_data"
                    break
        if not requires_evidence:
            for kw in self.legal_keywords:
                if kw in q_lower:
                    requires_evidence = True
                    evidence_reason = "legal_context"
                    break
        if not requires_evidence:
            for kw in self.source_keywords:
                if kw in q_lower:
                    requires_evidence = True
                    evidence_reason = "source_request"
                    break

        # Body-part + symptom pattern detection
        body_parts = [
            "chest", "head", "stomach", "back", "throat", "heart", "lungs",
            "arm", "leg", "knee", "shoulder", "neck", "ear", "eye", "nose",
            "mouth", "tooth", "teeth", "finger", "toe", "foot", "hand",
            "wrist", "ankle", "hip", "elbow", "skin", "face", "forehead",
            "abdomen", "gut", "intestine", "bowel", "bladder",
            "kidney", "liver", "spleen", "pancreas", "gallbladder",
        ]
        symptoms = [
            "hurts", "hurt", "pain", "pains", "tight", "pressure", "aches", "ache",
            "burns", "burning", "feels funny", "feels weird", "feels strange",
            "feels wrong", "sore", "stiff", "swollen", "numb", "tingling",
            "weak", "throbbing", "sharp", "dull", "constant", "intermittent",
            "cramping", "spasm", "twitch", "pounding", "racing", "flutter",
        ]
        for bp in body_parts:
            if bp in q_lower:
                for sym in symptoms:
                    if sym in q_lower:
                        requires_evidence = True
                        evidence_reason = "medical_body_symptom"
                        break
                if requires_evidence:
                    break

        # Typos-tolerant news detection
        news_typos = ["newz", "nooz", "nuwz", "hedline", "hedlines", "hedlinez"]
        has_news_typo = any(t in q_lower for t in news_typos)
        news_context = ["latest", "current", "breaking", "update", "updates", "today", "now"]
        has_news_context = any(c in q_lower for c in news_context)
        wat_pattern = any(p in q_lower for p in ["wats ", "wat ", "wut ", "whats "])
        is_news = any(kw in q_lower for kw in self.news_keywords) or has_news_typo or (wat_pattern and has_news_context)
        is_time = any(kw in q_lower for kw in self.time_keywords)
        is_cooking = any(kw in q_lower for kw in self.cooking_keywords)
        # Use word-boundary matching for short/ambiguous keywords to avoid
        # false positives (e.g., "hot" in "photosynthesis", "cold" in "scold").
        def _matches_ephemeral_keyword(query: str, keyword: str) -> bool:
            if len(keyword) <= 4:
                # Short keywords need word boundaries
                return bool(re.search(rf"\\b{re.escape(keyword)}\\b", query))
            return keyword in query

        is_ephemeral = any(_matches_ephemeral_keyword(q_lower, kw) for kw in self.ephemeral_keywords)

        # Pre-compute keyword presence for collapse detection and length normalization
        has_any_keyword = is_time or is_news or is_ephemeral or requires_evidence or is_cooking

        # Stage 2: Cooking -> always LOCAL
        if is_cooking:
            return {
                "intent_family": "local_answer",
                "route": "LOCAL",
                "confidence": 1.0,
                "evidence_mode": "not_required",
                "evidence_reason": "",
                "embedding_route": "LOCAL",
                "embedding_intent": "local_answer",
            }

        # Stage 3: Embedding similarity for intent
        query_emb = self._encode(query)
        similarities = cosine_similarity(query_emb, self.embeddings)[0]
        top_k_idx = np.argsort(similarities)[-k:][::-1]

        from collections import Counter
        intent_votes = Counter()
        route_votes = Counter()
        total_weight = 0

        for idx in top_k_idx:
            ex = self.examples[idx]
            labels = ex["labels"]
            weight = similarities[idx] ** 2
            intent_votes[labels["intent_family"]] += weight
            route_votes[labels["route"]] += weight
            total_weight += weight

        # Detect embedding collapse: when top-k similarities are all
        # extremely high (>0.995) or nearly identical (range < 0.001),
        # the embedding space has collapsed and cannot distinguish
        # semantically unrelated queries. Do NOT trust it for routing.
        top_k_sims = [similarities[idx] for idx in top_k_idx]
        embedding_collapsed = (
            all(s > 0.995 for s in top_k_sims)
            or (max(top_k_sims) - min(top_k_sims) < 0.001)
        )

        # Exact-match boost: if top-1 neighbor is essentially identical,
        # trust it over a k-NN vote that could be outvoted by other close neighbors
        # BUT: skip the boost if embedding has collapsed — the top-1 match is
        # arbitrary when all vectors are nearly identical.
        top1_sim = similarities[top_k_idx[0]]
        if top1_sim >= 0.999 and not embedding_collapsed:
            best_intent = self.examples[top_k_idx[0]]["labels"]["intent_family"]
            best_route = self.examples[top_k_idx[0]]["labels"]["route"]
        else:
            best_intent = intent_votes.most_common(1)[0][0]
            best_route = route_votes.most_common(1)[0][0]
        avg_sim = total_weight / k

        # Build top-k neighbour info for logging/diagnostics
        top_k_neighbours = []
        for idx in top_k_idx:
            ex = self.examples[idx]
            top_k_neighbours.append({
                "query": ex.get("query", "")[:80],
                "route": ex["labels"].get("route", "UNKNOWN"),
                "intent": ex["labels"].get("intent_family", "unknown"),
                "similarity": round(float(similarities[idx]), 4),
            })

        # Track which guards fired
        guards_fired = []
        if not query or not query.strip():
            guards_fired.append("empty_query")
        if has_creative_verb and has_creative_noun:
            guards_fired.append("creative_writing")
        if is_cooking:
            guards_fired.append("cooking")
        if requires_evidence:
            guards_fired.append(f"keyword_{evidence_reason}")
        if is_time:
            guards_fired.append("time_keyword")
        if is_news and not requires_evidence:
            guards_fired.append("news_keyword")
        if is_ephemeral:
            guards_fired.append("ephemeral")

        # Stage 4: Override with keyword rules + embedding intent
        LOW_CONFIDENCE_THRESHOLD = 0.25
        # Embedding-based ephemeral detection takes priority
        # Also consider top-1 neighbor if it's a strong ephemeral match
        top1_idx = top_k_idx[0]
        top1_sim = similarities[top1_idx]
        top1_is_ephemeral = self.examples[top1_idx]["labels"]["intent_family"] == "ephemeral_query"
        is_ephemeral_embedding = (
            best_intent == "ephemeral_query"
            or best_route == "EPHEMERAL"
            or (top1_is_ephemeral and top1_sim > 0.99)
        )
        if is_ephemeral_embedding:
            guards_fired.append("embedding_ephemeral")
            # Sub-disambiguate ephemeral sub-type with keywords
            # Order: most specific first. Weather/stock keywords are more specific than
            # the broad is_news pattern (which catches "Whats" + "current").
            if is_time:
                final_route = "TIME"
                final_intent = "time_query"
            elif any(kw in q_lower for kw in ["weather", "forecast", "temperature", "rain", "rainy", "raining", "snow", "sunny", "cloudy", "windy", "storm", "humidity", "precipitation", "umbrella", "jacket", "coat", "hot", "cold", "warm", "freezing", "chilly", "humid"]):
                # Weather queries get dedicated WEATHER route for live data
                # BUT: other planets, historical weather, fictional weather → LOCAL
                non_earth_weather = any(kw in q_lower for kw in ["mars", "venus", "jupiter", "saturn", "neptune", "uranus", "pluto", "mercury", "titan", "europa", "moon "])
                historical_weather = any(kw in q_lower for kw in ["in 19", "in 200", "in 201", "was the weather", "used to be", "historical weather"])
                if non_earth_weather or historical_weather:
                    final_route = "LOCAL"
                    final_intent = "local_answer"
                else:
                    final_route = "WEATHER"
                    final_intent = "ephemeral_query"
            elif any(kw in q_lower for kw in ["stock price", "share price", "bitcoin", "crypto", "trading at", "market cap", "exchange rate", "forex", "currency rate"]):
                # Historical price queries → LOCAL (not live data)
                historical_price = any(kw in q_lower for kw in ["in 19", "in 200", "in 201", "back in", "was the price", "historical", "at its peak", "all time high"])
                if historical_price:
                    final_route = "LOCAL"
                    final_intent = "local_answer"
                else:
                    final_route = "AUGMENTED"
                    final_intent = "current_evidence"
                    evidence_reason = "financial_data"
                    requires_evidence = True
            elif is_news and not requires_evidence:
                final_route = "NEWS"
                final_intent = "news_request"
            else:
                # No strong keyword match, but embedding was confident
                if avg_sim >= 0.5 and best_route in ("WEATHER", "TIME", "NEWS"):
                    final_route = best_route
                    final_intent = best_intent
                else:
                    # Traffic, flights, vague ephemeral → LOCAL (skip memory)
                    final_route = "LOCAL"
                    final_intent = "local_answer"
        elif is_ephemeral and not requires_evidence:
            # Keyword-detected ephemeral that embedding missed (e.g., close to old current_evidence examples)
            guards_fired.append("keyword_ephemeral_fallback")
            if is_time:
                final_route = "TIME"
                final_intent = "time_query"
            elif any(kw in q_lower for kw in ["weather", "forecast", "temperature", "rain", "rainy", "raining", "snow", "sunny", "cloudy", "windy", "storm", "humidity", "precipitation", "umbrella", "jacket", "coat", "hot", "cold", "warm", "freezing", "chilly", "humid"]):
                non_earth_weather = any(kw in q_lower for kw in ["mars", "venus", "jupiter", "saturn", "neptune", "uranus", "pluto", "mercury", "titan", "europa", "moon "])
                historical_weather = any(kw in q_lower for kw in ["in 19", "in 200", "in 201", "was the weather", "used to be", "historical weather"])
                if non_earth_weather or historical_weather:
                    final_route = "LOCAL"
                    final_intent = "local_answer"
                else:
                    final_route = "WEATHER"
                    final_intent = "ephemeral_query"
            elif any(kw in q_lower for kw in ["stock price", "share price", "bitcoin", "crypto", "trading at", "market cap", "exchange rate", "forex", "currency rate"]):
                historical_price = any(kw in q_lower for kw in ["in 19", "in 200", "in 201", "back in", "was the price", "historical", "at its peak", "all time high"])
                if historical_price:
                    final_route = "LOCAL"
                    final_intent = "local_answer"
                else:
                    final_route = "AUGMENTED"
                    final_intent = "current_evidence"
                    evidence_reason = "financial_data"
                    requires_evidence = True
            elif is_news:
                final_route = "NEWS"
                final_intent = "news_request"
            else:
                if avg_sim >= 0.5 and best_route in ("WEATHER", "TIME", "NEWS"):
                    final_route = best_route
                    final_intent = best_intent
                else:
                    final_route = "LOCAL"
                    final_intent = "local_answer"
        # Low-confidence safety net: if embedding is uncertain, default to LOCAL
        elif avg_sim < LOW_CONFIDENCE_THRESHOLD and not requires_evidence and not is_time and not is_news:
            final_route = "LOCAL"
            final_intent = "local_answer"
            guards_fired.append("low_confidence_fallback")
        elif is_time or best_intent == "time_query":
            # News-vs-time disambiguation: strong news keywords override time embedding
            if is_news and not requires_evidence:
                final_route = "NEWS"
                final_intent = "news_request"
                guards_fired.append("news_disambiguated_time")
            # Weather-vs-time disambiguation: weather keywords should not route to TIME
            elif any(kw in q_lower for kw in ["weather", "forecast", "temperature", "rainy", "raining", "snow", "sunny", "cloudy", "windy", "storm", "humidity", "precipitation"]):
                final_route = "LOCAL"
                final_intent = "local_answer"
                guards_fired.append("weather_disambiguated_time")
            else:
                final_route = "TIME"
                final_intent = "time_query"
        elif (is_news or best_intent == "news_request") and not requires_evidence:
            # Don't override confident LOCAL embedding for bare "news" keyword
            strong_news_signals = ["headlines", "breaking", "latest updates", "current events", "what happened", "what's happening", "update on", "latest on", "developments", "trending"]
            if best_route == "LOCAL" and avg_sim >= 0.5 and not any(c in q_lower for c in strong_news_signals):
                final_route = "LOCAL"
                final_intent = "local_answer"
                guards_fired.append("news_guard_respects_local")
            else:
                final_route = "NEWS"
                final_intent = "news_request"
        elif requires_evidence:
            final_route = "AUGMENTED"
            final_intent = best_intent
        elif best_route == "TIME" and not is_time and any(kw in q_lower for kw in ["weather", "forecast", "temperature", "rain", "snow", "sunny", "cloudy", "windy", "storm", "humidity", "precipitation"]):
            # Embedding mislabeled weather as time — override to LOCAL
            final_route = "LOCAL"
            final_intent = "local_answer"
            guards_fired.append("weather_vs_time_embedding_fix")
        else:
            final_route = best_route
            final_intent = best_intent

        # Embedding collapse safety net: if the embedding collapsed and
        # no keywords matched to corroborate the route, fall back to LOCAL.
        # This prevents routing semantically-unrelated queries to TIME/NEWS
        # purely based on collapsed [CLS] embeddings.
        if embedding_collapsed and not has_any_keyword and final_route in ("TIME", "NEWS", "WEATHER"):
            final_route = "LOCAL"
            final_intent = "local_answer"
            guards_fired.append("embedding_collapse_fallback")

        # No-keyword safety net: when no keyword signals matched at all
        # but the embedding (even non-collapsed) suggests a live-data route,
        # require stronger confidence or corroborating keywords.
        # Short queries are more prone to embedding collapse, so we raise the
        # threshold for queries with 5 or fewer words.
        if not has_any_keyword and final_route in ("TIME", "NEWS", "WEATHER"):
            word_count = len(query.split())
            threshold = 0.90 if word_count <= 5 else 0.85
            if avg_sim < threshold:
                final_route = "LOCAL"
                final_intent = "local_answer"
                guards_fired.append("no_keyword_live_data_fallback")

        # Ephemeral flag: embedding-detected OR keyword-detected
        ephemeral_flag = is_ephemeral_embedding or is_ephemeral

        return {
            "intent_family": final_intent,
            "route": final_route,
            "confidence": round(float(avg_sim), 4),
            "evidence_mode": "required" if requires_evidence else "not_required",
            "evidence_reason": evidence_reason,
            "embedding_route": best_route,
            "embedding_intent": best_intent,
            "top_k_neighbours": top_k_neighbours,
            "guards_fired": guards_fired,
            "ephemeral": ephemeral_flag,
        }


def test():
    print("Hybrid Router Test")
    print("=" * 90)

    router = HybridRouter()

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
        ("What is the weather in London?", "LOCAL"),
        ("Current NVIDIA stock price", "AUGMENTED"),
        ("Is weed legal in California?", "AUGMENTED"),
    ]

    correct = 0
    for q, expected in test_queries:
        result = router.predict(q)
        actual = result["route"]
        status = "✅" if actual == expected else "❌"
        if actual == expected:
            correct += 1
        print(f"  {status} {q:50s} -> {actual:12s} (expected {expected:12s}) conf={result['confidence']:.3f}")

    print(f"\nAccuracy: {correct}/{len(test_queries)} ({100*correct/len(test_queries):.0f}%)")


if __name__ == "__main__":
    test()
