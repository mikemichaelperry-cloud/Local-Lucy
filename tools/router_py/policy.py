#!/usr/bin/env python3
"""
Router policy functions - Python port of shell implementations.
Deterministic policy decisions with no side effects.
"""

import re
from typing import Literal


# Valid augmentation policy values
AugmentationPolicy = Literal["disabled", "fallback_only", "direct_allowed"]


def normalize_augmentation_policy(raw: str) -> AugmentationPolicy:
    """
    Normalize augmentation policy string to canonical value.
    
    Args:
        raw: Raw policy string (case-insensitive)
        
    Returns:
        Canonical policy: "disabled", "fallback_only", or "direct_allowed"
        
    Examples:
        >>> normalize_augmentation_policy("OFF")
        'disabled'
        >>> normalize_augmentation_policy("fallback")
        'fallback_only'
        >>> normalize_augmentation_policy("2")
        'direct_allowed'
    """
    normalized = raw.lower().strip() if raw else "disabled"
    
    # Disabled variants
    if normalized in ("disabled", "off", "none", "0", "false", "no", ""):
        return "disabled"
    
    # Fallback only variants
    if normalized in ("fallback_only", "fallback", "1", "true", "yes", "on"):
        return "fallback_only"
    
    # Direct allowed variants
    if normalized in ("direct_allowed", "direct", "2"):
        return "direct_allowed"
    
    # Default to disabled for unknown values
    return "disabled"


def requires_evidence_mode(query: str, context: dict | None = None) -> tuple[bool, str]:
    """
    Determine if a query requires evidence mode.
    
    Evidence mode is required for:
    - Medical/health queries
    - Live conflict/geopolitics
    - Source verification requests
    
    Args:
        query: The user's query string
        context: Optional context dict with additional metadata
        
    Returns:
        Tuple of (requires_evidence: bool, reason: str)
        
    Examples:
        >>> requires_evidence_mode("What are the symptoms of flu?")
        (True, 'medical_context')
        >>> requires_evidence_mode("What is 2+2?")
        (False, 'default_light')
    """
    if not query:
        return False, "default_light"
    
    # Normalize for keyword matching
    normalized = query.lower()
    
    # Creative writing guard — fictional/artistic requests should never trigger evidence
    # even if they contain medical/financial/legal topic keywords (e.g. "write a horror story about a hospital")
    creative_verbs = ["write", "compose", "craft", "tell", "create", "make up", "imagine"]
    creative_nouns = [
        "story", "poem", "essay", "novel", "fiction", "script", "play", "song",
        "horror", "fantasy", "sci-fi", "romance", "thriller", "mystery",
        "character", "plot", "dialogue", "scene", "chapter",
    ]
    has_creative_verb = any(v in normalized for v in creative_verbs)
    has_creative_noun = any(n in normalized for n in creative_nouns)
    if has_creative_verb and has_creative_noun:
        return False, "creative_writing"
    
    # Veterinary / animal health — check FIRST so vet-specific queries get
    # veterinary_context instead of being swallowed by medical_context.
    
    # Tier 1: Specific animal species — immediate trigger (very high confidence)
    specific_animal_terms = [
        "dog", "dogs", "puppy", "puppies", "canine",
        "cat", "cats", "kitten", "kittens", "feline",
        "equine", "horse", "horses", "pony", "ponies",
        "bovine", "cow", "cows", "bull", "bulls", "calf", "calves",
        "ovine", "sheep", "lamb", "lambs", "goat", "goats",
        "pig", "pigs", "swine", "hog", "hogs",
        "avian", "bird", "birds", "parrot", "parrots", "parakeet", "parakeets",
        "canary", "canaries", "finch", "finches", "budgie", "budgies",
        "cockatiel", "cockatiels", "macaw", "macaws",
        "rabbit", "rabbits", "bunny", "bunnies",
        "hamster", "hamsters", "gerbil", "gerbils",
        "rat", "rats", "mouse", "mice",
        "guinea pig", "guinea pigs",
        "ferret", "ferrets", "chinchilla", "chinchillas",
        "hedgehog", "hedgehogs",
        "sugar glider", "sugar gliders",
        "reptile", "reptiles",
        "snake", "snakes", "python", "pythons",
        "lizard", "lizards", "gecko", "geckos", "iguana", "iguanas",
        "bearded dragon", "bearded dragons",
        "chameleon", "chameleons",
        "turtle", "turtles", "tortoise", "tortoises",
        "fish", "fishes", "betta", "bettas", "goldfish", "koi",
        "chicken", "chickens", "hen", "hens", "rooster", "roosters",
        "duck", "ducks", "goose", "geese",
        "turkey", "turkeys",
        "alpaca", "alpacas", "llama", "llamas",
        "camel", "camels", "donkey", "donkeys", "mule", "mules",
    ]
    for term in specific_animal_terms:
        if " " in term:
            # Multi-word term — substring match is safe
            if term in normalized:
                return True, "veterinary_context"
        else:
            # Single-word term — require word boundaries to avoid
            # matching inside other words (e.g., "cat" in "medication")
            pattern = r'(?<![a-z])' + re.escape(term) + r'(?![a-z])'
            if re.search(pattern, normalized):
                return True, "veterinary_context"
    
    # Tier 2: General animal terms — require health context to avoid false positives
    # (e.g., "animal rights", "pet project", "pet peeve")
    general_animal_terms = ["pet", "pets", "animal", "animals", "livestock"]
    has_general_animal = any(t in normalized for t in general_animal_terms)
    if has_general_animal:
        health_indicators = [
            "sick", "ill", "hurt", "pain", "injury", "injured", "wound", "wounded",
            "bleeding", "vomit", "vomiting", "diarrhea", "cough", "sneeze", "sneezing",
            "fever", "tired", "lethargic", "limp", "limping", "lame", "lameness",
            "itch", "itchy", "scratch", "scratching", "bald", "hair loss", "losing hair",
            "plucking feathers", "plucking",
            "weight loss", "not eating", "wont eat", "refusing food", "dehydrated",
            "swollen", "lump", "bump", "tumor", "cancer", "infection", "infected",
            "parasite", "worm", "flea", "tick", "mite", "mange", "rabies",
            "surgery", "operation", "treatment", "medication", "medicine", "drug",
            "vaccine", "vaccination", "shot", "deworm", "neuter", "spay", "castrate",
            "vet", "veterinary", "veterinarian", "clinic", "hospital",
            "symptom", "symptoms", "diagnosis", "diagnose", "disease", "condition",
            "problem", "issue", "concern", "worried", "worry", "wrong",
        ]
        if any(h in normalized for h in health_indicators):
            return True, "veterinary_context"
    
    # Tier 3: Veterinary-specific procedures, sources, and medications
    veterinary_procedures = [
        "veterinary", "vet ", "veterinarian", "animal health",
        "pet medication", "dog medication", "cat medication",
        "heartworm", "flea treatment", "tick treatment", "deworm",
        "parvovirus", "distemper", "kennel cough", "bordetella",
        "spay", "neuter", "castration", "ovariohysterectomy",
        "hip dysplasia", "luxating patella", "bloat", "gdv",
        "pancreatitis", "kidney disease", "liver disease",
        "diabetes in dogs", "diabetes in cats", "hyperthyroidism in cats",
        "cushing's disease in dogs", "addison's disease in dogs",
        "merck vet", "vcahospitals", "avma", "aaha",
    ]
    for keyword in veterinary_procedures:
        if keyword in normalized:
            return True, "veterinary_context"
    
    # Medical/health keywords — comprehensive coverage for safety-critical queries
    medical_keywords = [
        # General health inquiry
        "symptom", "symptoms", "diagnosis", "treatment", "treat", "medication",
        "disease", "condition", "prescription", "drug", "vaccine",
        "vaccination", "pregnancy", "pregnant", "cancer", "diabetes",
        "heart attack", "stroke", "infection", "virus", "bacteria",
        "pain", "headache", "injury", "emergency", "hospital", "doctor", "medicine",
        # Body parts + symptom combinations (critical for catching novel phrasings)
        "chest", "breath", "breathing", "shortness of breath",
        "fever", "temperature", "feel good", "not feeling", "feel well", "feeling bad",
        "unwell", "sick", "nausea", "nauseous", "vomit", "dizzy", "cough", "sneeze",
        "aches", "sore", "swelling", "swollen", "rash", "itchy", "burning",
        "numbness", "tingling", "weakness", "fatigue", "tired", "exhausted",
        "appetite", "weight loss", "weight gain", "bleeding", "bruising", "wound", "cut",
        "chills", "shivering", "dehydration", "seizure", "convulsion", "paralysis",
        "palpitation", "sweating", "hallucination", "delusion", "panic",
        # Pediatric indicators
        "baby", "child", "kid", "toddler", "infant", "2-year-old", "3-year-old",
        "4-year-old", "5-year-old", "year old", "years old", "my son", "my daughter",
        # Medications and interactions
        "tadalafil", "cialis", "viagra", "sildenafil", "interaction", "interact",
        "grapefruit", "side effect", "contraindication", "dosage", "dose",
        "amoxicillin", "aspirin", "metformin", "insulin", "ibuprofen", "warfarin",
        "atorvastatin", "lipitor", "omeprazole", "pharmacy", "pharmacist",
        "acetaminophen", "paracetamol", "naproxen", "clopidogrel", "lisinopril",
        "amlodipine", "metoprolol", "atorvastatin", "simvastatin", "levothyroxine",
        "albuterol", "gabapentin", "prednisone", "fluticasone", "montelukast",
        # Conditions and diseases
        "hypertension", "high blood pressure", "cholesterol", "asthma", "copd",
        "arthritis", "osteoporosis", "depression", "anxiety", "bipolar",
        "epilepsy", "seizure", "migraine", "allergy", "allergic", "anaphylaxis",
        "pneumonia", "bronchitis", "tuberculosis", "hepatitis", "meningitis",
        "appendicitis", "gallstones", "kidney stone", "fracture", "burn",
        "covid", "coronavirus", "flu", "influenza", "hiv", "aids", "malaria",
        "measles", "mumps", "rubella", "chickenpox", "shingles", "herpes",
        # Body systems and anatomy
        "liver", "kidney", "heart", "lung", "brain", "spine", "nerve",
        "blood clot", "aneurysm", "arrhythmia", "atrial fibrillation", "afib",
        # Procedures
        "surgery", "operation", "transplant", "biopsy", "mri", "ct scan",
        "x-ray", "ultrasound", "colonoscopy", "endoscopy", "chemotherapy",
        "radiation", "dialysis", "vaccination", "immunization",
        # Mental health
        "suicide", "self-harm", "overdose", "poisoning", "antidepressant",
        "antipsychotic", "benzodiazepine", "ssri", "snri",
    ]
    
    for keyword in medical_keywords:
        if keyword in normalized:
            return True, "medical_context"
    
    # Body-part + symptom pattern detection — catches novel phrasings like "my chest feels tight"
    body_parts = [
        "chest", "head", "stomach", "back", "throat", "heart", "lungs",
        "arm", "leg", "knee", "shoulder", "neck", "ear", "eye", "nose",
        "mouth", "tooth", "teeth", "finger", "toe", "foot", "hand",
        "wrist", "ankle", "hip", "elbow", "skin", "face", "forehead",
        "abdomen", "stomach", "gut", "intestine", "bowel", "bladder",
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
        if bp in normalized:
            for sym in symptoms:
                if sym in normalized:
                    return True, "medical_body_symptom"
    
    # Live conflict/geopolitics keywords — real-time verification needed
    conflict_keywords = [
        "breaking news", "latest news", "latest updates", "current conflict", "war in",
        "ongoing war", "live updates", "just happened", "today in",
        "current situation", "latest development",
        # Geopolitics and sanctions
        "sanctions", "ceasefire", "peace talks", "evacuation", "hostage",
        "diplomatic crisis", "embassy", "consulate", "diplomat",
        # Elections and political events
        "election results", "vote count", "exit poll", "inauguration",
        "election night", "primary results", " runoff",
        # Terrorism and security
        "terrorist attack", "bombing", "shooting", "hostage crisis",
        "security alert", "travel advisory", "embassy warning",
        # Natural disasters (real-time)
        "earthquake", "tsunami", "hurricane", "typhoon", "tornado",
        "flood warning", "wildfire", "volcano eruption", "evacuation order",
        "severe weather alert", "amber alert", "emergency broadcast",
    ]
    
    for keyword in conflict_keywords:
        if keyword in normalized:
            return True, "conflict_live"
    
    # Source verification requests — user explicitly wants citations
    source_keywords = [
        "source", "cite", "citation", "reference", "evidence",
        "where did you get", "how do you know", "prove that",
        "verify", "fact check", "peer-reviewed", "study", "research paper",
        "clinical trial", "meta-analysis", "systematic review",
        "according to", "who said", "which expert", "official report",
    ]
    
    # Financial / market data — requires real-time accurate data
    financial_keywords = [
        "stock price", "share price", "market cap", "market capitalization",
        "trading at", "nasdaq", "nyse", "s&p 500", "dow jones", "ftse",
        "bitcoin price", "crypto price", "ethereum", "exchange rate",
        "interest rate", "federal reserve", "fed rate", "ecb rate",
        "inflation rate", "cpi", "gdp", "unemployment rate",
        "earnings report", "quarterly results", "revenue", "profit margin",
        # Investment and planning (NEW)
        "invest", "investing", "investment", "retirement", "401k", "ira", "roth",
        "bitcoin", "ethereum", "crypto", "cryptocurrency",
        "economy", "economic", "stock", "stocks", "portfolio",
        "mutual fund", "etf", "bond", "bonds", "dividend", "yield",
        "asset", "risk", "return", "roi", "capital gains", "working capital", "equity",
        "debt", "loan", "mortgage", "refinance", "credit", "credit score",
        "bankruptcy", "savings", "account", "bank", "credit card",
        "salary", "income", "expense", "budget", "valuation", "worth",
        "net worth", "wealth", "pension", "insurance", "premium",
    ]
    
    # Legal / regulatory — statutory text changes slowly but case law is live
    legal_keywords = [
        "is it legal to", "legality of", "law regarding", "regulation",
        "court ruling", "supreme court", "recent ruling", "precedent",
        "statute", "ordinance", "compliance requirement", "penalty for",
        # Licenses and permits (NEW)
        "business license", "license", "permit", "zoning",
        # Immigration and citizenship (NEW)
        "citizenship", "visa", "immigration", "passport", "work permit",
        # Employment law (NEW)
        "discrimination", "harassment", "wrongful termination",
        "nda", "non-compete", "non-disclosure",
        # IP and defamation (NEW)
        "copyright", "trademark", "patent", "plagiarism", "defamation",
        "libel", "slander",
        # Litigation and remedies (NEW)
        "contract", "breach", "liability", "negligence", "class action",
        "lawsuit", "settlement", "damages", "injunction",
        "restraining order", "probation", "parole", "bail",
        "felony", "misdemeanor", "warrant", "subpoena",
        # Family law (NEW)
        "power of attorney", "guardianship", "custody", "child support",
        "alimony", "divorce", "adoption", "wills", "estate", "inheritance",
        "probate", "trust",
        # Business structures (NEW)
        "llc", "incorporation", "partnership", "nonprofit",
        # Tax and audit (NEW)
        "tax", "taxes", "audit", "tax attorney",
        # Courts and appeals (NEW)
        "expert witness", "appeal", "appellate",
        "family court", "small claims", "attorney general",
        "district attorney", "prosecutor", "defense attorney",
        "legal aid", "habeas corpus",
    ]
    
    for keyword in source_keywords:
        if keyword in normalized:
            return True, "source_request"
    
    # Financial / market data — accuracy matters
    for keyword in financial_keywords:
        if keyword in normalized:
            return True, "financial_data"
    
    # Legal / regulatory — accuracy matters
    for keyword in legal_keywords:
        if keyword in normalized:
            return True, "legal_context"
    
    # Veterinary / animal health — requires trusted sources
    veterinary_keywords = [
        "veterinary", "vet ", "veterinarian", "animal health",
        "pet medication", "dog medication", "cat medication",
        "canine", "feline", "equine", "bovine", "ovine",
        "heartworm", "flea treatment", "tick treatment", "deworm",
        "parvovirus", "distemper", "kennel cough", "bordetella",
        "spay", "neuter", "castration", "ovariohysterectomy",
        "hip dysplasia", "luxating patella", "bloat", "gdv",
        "pancreatitis", "kidney disease", "liver disease",
        "diabetes in dogs", "diabetes in cats", "hyperthyroidism",
        "hypothyroidism", "cushing's disease", "addison's disease",
        "merck vet", "vcahospitals", "avma", "aaha",
    ]
    for keyword in veterinary_keywords:
        if keyword in normalized:
            return True, "veterinary_context"
    
    # Default: no evidence required
    return False, "default_light"


def provider_usage_class_for(provider: str) -> Literal["paid", "free", "local", "none"]:
    """
    Classify a provider by its usage/cost class.
    
    Args:
        provider: Provider name (e.g., "openai", "wikipedia", "local")
        
    Returns:
        Usage class: "paid", "free", "local", or "none"
        
    Examples:
        >>> provider_usage_class_for("openai")
        'paid'
        >>> provider_usage_class_for("wikipedia")
        'free'
        >>> provider_usage_class_for("local")
        'local'
    """
    normalized = provider.lower().strip() if provider else ""
    
    if normalized in ("openai", "kimi"):
        return "paid"
    if normalized == "wikipedia":
        return "free"
    if normalized == "local":
        return "local"
    
    return "none"


def manifest_evidence_selection_label(
    evidence_mode: str | None,
    evidence_reason: str | None
) -> str:
    """
    Generate a human-readable label for evidence selection.
    
    Args:
        evidence_mode: The selected evidence mode (or None)
        evidence_reason: The reason for evidence selection (or None)
        
    Returns:
        Human-readable label string
        
    Examples:
        >>> manifest_evidence_selection_label("required", "medical_context")
        'policy-triggered'
        >>> manifest_evidence_selection_label(None, None)
        'not_applicable'
    """
    if not evidence_mode:
        return "not_applicable"
    
    reason = evidence_reason or ""
    
    if reason in ("default_light", ""):
        return "default-light"
    
    if reason.startswith(("explicit_", "source_request")):
        return "explicit-user-triggered"
    
    if reason.startswith(("policy_", "medical_context", "conflict_live")):
        return "policy-triggered"
    
    return "manifest-selected"


if __name__ == "__main__":
    # Quick sanity checks
    print("normalize_augmentation_policy('OFF'):", normalize_augmentation_policy("OFF"))
    print("normalize_augmentation_policy('fallback'):", normalize_augmentation_policy("fallback"))
    print("normalize_augmentation_policy('direct'):", normalize_augmentation_policy("direct"))
    print()
    print("requires_evidence_mode('flu symptoms'):", requires_evidence_mode("flu symptoms"))
    print("requires_evidence_mode('hello'):", requires_evidence_mode("hello"))
    print()
    print("provider_usage_class_for('openai'):", provider_usage_class_for("openai"))
    print("provider_usage_class_for('wikipedia'):", provider_usage_class_for("wikipedia"))
