#!/usr/bin/env python3
"""Hybrid router: keyword evidence + embedding k-NN for intent.

Stage 1: Keyword-based evidence detection (fast, reliable for medical/financial/legal)
Stage 2: Check for cooking/recipe queries -> force LOCAL
Stage 3: Embedding k-NN for intent classification
Stage 4: Route derived from intent + evidence
"""

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from transformers import AutoModel, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
from policy import requires_evidence_mode


class HybridRouter:
    """Hybrid router combining keyword evidence + embedding similarity."""

    def __init__(self, embeddings_path: str = "comprehensive_embeddings.npy",
                 examples_path: str = "comprehensive_examples.json",
                 base_model: str = "answerdotai/ModernBERT-base"):
        self.device = "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(base_model)
        self.model = AutoModel.from_pretrained(base_model)
        self.model.eval()

        self.examples = json.load(open(examples_path))
        self.embeddings = np.load(embeddings_path)

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
            "fever", "temperature", "feel good", "not feeling", "feel well", "feeling bad",
            "unwell", "sick", "nausea", "nauseous", "vomit", "dizzy", "cough", "sneeze",
            "aches", "sore", "swelling", "swollen", "rash", "itchy", "burning",
            "numbness", "tingling", "weakness", "fatigue", "tired", "exhausted",
            "appetite", "weight loss", "weight gain", "bleeding", "bruising", "wound", "cut",
            "chills", "shivering", "dehydration", "seizure", "convulsion", "paralysis",
            "palpitation", "sweating", "hallucination", "delusion", "panic",
            # Pediatric indicators (NEW)
            "baby", "child", "kid", "toddler", "infant", "2-year-old", "3-year-old",
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
            "invest", "investing", "economy", "economic", "stock", "stocks",
            "risk", "return", "roi", "capital", "equity",
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
        ]
        self.time_keywords = [
            "time is it", "current time", "what day is it",
            "timezone", "what date", "how many days until",
            "time in ", "time now", "local time",
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
            "ingredient", "measurement", "cup", "tablespoon",
            "teaspoon", "ounce", "gram", "kilogram", "pound",
            "temperature", "preheat", "bake at", "cook at",
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
            for kw in self.financial_keywords:
                if kw in q_lower:
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

        # Stage 4: Override with keyword rules + embedding intent
        # Use embedding intent to catch news/time even when keyword lists miss
        if is_time or best_intent == "time_query":
            final_route = "TIME"
            final_intent = "time_query"
        elif (is_news or best_intent == "news_request") and not requires_evidence:
            final_route = "NEWS"
            final_intent = "news_request"
        elif requires_evidence:
            final_route = "AUGMENTED"
            final_intent = best_intent
        else:
            final_route = best_route
            final_intent = best_intent

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
