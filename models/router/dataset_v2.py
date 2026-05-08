#!/usr/bin/env python3
"""Expanded dataset with diverse subjects for semantic routing."""

import json
import random
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import Dataset


# ============================================================================
# Expanded synthetic templates covering ALL domains of human knowledge
# ============================================================================

SYNTHETIC_TEMPLATES = {
    # === LOCAL: Tasks the local model handles well ===
    "local_answer": [
        # Math & logic
        "what is {math_expression}",
        "solve {math_problem}",
        "calculate {math_expression}",
        "simplify {math_expression}",
        "factor {math_expression}",
        # Translation
        "translate '{phrase}' to {language}",
        "how do you say '{phrase}' in {language}",
        "what is '{phrase}' in {language}",
        # Coding / debugging
        "debug this code: {code_snippet}",
        "why am I getting {error_type}",
        "fix this {language} script",
        "refactor this function",
        # Writing help (non-creative)
        "help me write an email to {recipient} about {topic}",
        "draft a meeting agenda for {topic}",
        "summarize this paragraph: {text_snippet}",
        # General knowledge (static facts)
        "what is the capital of {country}",
        "who wrote {book_title}",
        "when did {historical_event} happen",
        "define {concept}",
        # Advice / opinion
        "should I {life_decision}",
        "what are the pros and cons of {topic}",
        "advice for {life_situation}",
        # Brainstorming
        "brainstorm ideas for {project_topic}",
        "give me 5 ideas for {project_topic}",
    ],

    # === BACKGROUND OVERVIEW: Static knowledge requiring depth ===
    "background_overview": [
        "explain {complex_topic} in simple terms",
        "what is {complex_topic} and why does it matter",
        "how did {complex_topic} develop historically",
        "overview of {complex_topic}",
        "introduction to {complex_topic}",
        "what are the key concepts in {complex_topic}",
        "tell me about {complex_topic}",
        "what do I need to know about {complex_topic}",
        "explain the relationship between {topic_a} and {topic_b}",
        "how does {complex_topic} compare to {alternative_topic}",
        "what are the main theories about {complex_topic}",
        "who are the important figures in {complex_topic}",
    ],

    # === TECHNICAL EXPLANATION: Deep technical detail ===
    "technical_explanation": [
        "how does {technology} work under the hood",
        "explain the architecture of {technology}",
        "what algorithm does {technology} use",
        "how is {technology} implemented",
        "technical specification of {technology}",
        "what protocol does {technology} use",
        "explain the math behind {math_concept}",
        "derive the formula for {math_concept}",
        "how does {physical_process} work at the molecular level",
        "what is the mechanism of {biological_process}",
        "step-by-step technical guide for {technical_task}",
        "deep dive into {technology} internals",
    ],

    # === CURRENT EVIDENCE: Needs real-time or verified data ===
    "current_evidence": [
        "what is the latest research on {research_topic}",
        "recent studies about {research_topic}",
        "current scientific consensus on {controversial_topic}",
        "what do we know about {emerging_topic} today",
        "latest developments in {emerging_topic}",
        "has {scientific_claim} been verified",
        "what does the evidence say about {controversial_topic}",
        "meta-analysis of {research_topic}",
        "systematic review of {research_topic}",
        "clinical trial results for {medical_topic}",
    ],

    # === NEWS REQUEST: Current events ===
    "news_request": [
        "latest news on {news_topic}",
        "what happened with {news_topic} today",
        "headlines about {news_topic}",
        "breaking news {news_topic}",
        "updates on {ongoing_event}",
        "news from {country_or_region}",
        "what is going on with {news_topic}",
        "current events in {country_or_region}",
        "political news about {political_topic}",
        "sports news about {sports_team}",
        "weather alert for {location}",
        "election results in {location}",
    ],

    # === TIME QUERY: Time-specific ===
    "time_query": [
        "what time is it in {location}",
        "current time in {location}",
        "time now {location}",
        "what is the date today",
        "what day of the week is {date_reference}",
        "how many days until {event_name}",
        "when is {holiday_name} this year",
        "timezone difference between {location_a} and {location_b}",
    ],

    # === MEDICAL INQUIRY: Health questions needing evidence ===
    "medical_inquiry": [
        "what are the symptoms of {medical_condition}",
        "treatment options for {medical_condition}",
        "is {medication} safe for {medical_condition}",
        "side effects of {medication}",
        "can I take {medication_a} with {medication_b}",
        "dosage of {medication} for {medical_condition}",
        "what does {medical_test} measure",
        "prognosis for {medical_condition}",
        "difference between {medical_condition_a} and {medical_condition_b}",
        "preventive measures for {medical_condition}",
        "when should I see a doctor for {symptom}",
        "is {symptom} serious",
    ],

    # === CREATIVE WRITING: Fiction, poetry, imagination ===
    "creative_writing": [
        "write a story about {creative_topic}",
        "create a poem about {creative_topic}",
        "write a short fiction piece about {scenario}",
        "imagine a world where {scenario}",
        "write a dialogue between {famous_person_a} and {famous_person_b}",
        "draft a screenplay scene about {creative_topic}",
        "write a fairy tale about {creative_topic}",
        "create a myth explaining {natural_phenomenon}",
        "write lyrics for a song about {creative_topic}",
        "compose a letter from {historical_figure} to {another_historical_figure}",
    ],

    # === CLARIFICATION: Vague or ambiguous queries ===
    "clarification": [
        "what",
        "how",
        "why",
        "when",
        "where",
        "explain",
        "tell me more",
        "go on",
        "elaborate",
        "what do you mean",
        "can you clarify",
        "I don't understand",
        "huh",
        "?",
    ],
}


# ============================================================================
# Expanded slot values covering ALL subjects
# ============================================================================

SLOT_VALUES: dict[str, list[str]] = {
    # STEM
    "complex_topic": [
        "quantum computing", "machine learning", "climate change", "CRISPR gene editing",
        "blockchain technology", "nuclear fusion", "dark matter", "artificial intelligence",
        "renewable energy", "neuroscience", "evolutionary biology", "astrophysics",
        "cybersecurity", "nanotechnology", "synthetic biology", "gravitational waves",
        "the Higgs boson", "photosynthesis", "DNA replication", "plate tectonics",
        "the immune system", "consciousness", "game theory", "chaos theory",
        "general relativity", "quantum entanglement", "the microbiome", "epigenetics",
    ],
    "research_topic": [
        "sleep and memory", "gut health and mood", "climate tipping points",
        "longevity interventions", "psychedelic therapy", "mRNA vaccines",
        "carbon capture technology", "battery technology", "hydrogen fuel cells",
        "gene therapy for blindness", "Alzheimer's prevention", "cancer immunotherapy",
        "depression treatment", "autism causes", "exoplanet atmospheres",
        "dark energy", "ocean acidification", "deforestation effects",
    ],
    "technology": [
        "transformer neural networks", "Docker containers", "Kubernetes orchestration",
        "PostgreSQL indexing", "Redis caching", "WebSocket protocols",
        "TLS handshake", "BGP routing", "RAID storage", "LLVM compiler",
        "WebAssembly", "HTTP/3", "gRPC", "Kafka streaming", "Elasticsearch",
        "TCP congestion control", "GPU shader pipelines", "blockchain consensus",
        "operating system kernels", "virtual memory", "garbage collection",
    ],
    "technical_task": [
        "building a CI/CD pipeline", "optimizing SQL queries", "setting up load balancing",
        "implementing OAuth2", "designing a distributed cache", "tuning JVM performance",
        "configuring nginx reverse proxy", "deploying on AWS Lambda",
    ],
    "math_concept": [
        "Fourier transforms", "eigenvalues", "Bayesian inference", "gradient descent",
        "backpropagation", "support vector machines", "Markov chains",
        "Monte Carlo methods", "principal component analysis", "entropy",
    ],
    "physical_process": [
        "superconductivity", "nuclear fission", "protein folding", "photosynthesis",
        "ion channel gating", "synaptic transmission", "laser operation",
        "semiconductor doping", "ferromagnetism",
    ],
    "biological_process": [
        "cellular respiration", "DNA transcription", "protein synthesis",
        "apoptosis", "meiosis", "antibody production", "hormone signaling",
        "stem cell differentiation", "viral replication",
    ],
    "emerging_topic": [
        "AI regulation", "space tourism", "lab-grown meat", "brain-computer interfaces",
        "quantum internet", "fusion energy progress", "autonomous vehicles",
        "personalized medicine", "vertical farming", "carbon removal",
    ],
    "scientific_claim": [
        "cold fusion", "faster-than-light travel", "homeopathy",
        "vaccines cause autism", "climate change is a hoax", "5G causes illness",
        "the moon landing was faked", "evolution is just a theory",
    ],
    "controversial_topic": [
        "vaccine safety", "GMO foods", "nuclear power", "fracking",
        "antidepressant effectiveness", "mask effectiveness for COVID",
        "intermittent fasting benefits", "keto diet safety",
    ],

    # Humanities
    "book_title": [
        "1984", "To Kill a Mockingbird", "Pride and Prejudice", "Moby Dick",
        "The Great Gatsby", "War and Peace", "One Hundred Years of Solitude",
        "The Odyssey", "Hamlet", "The Divine Comedy", "Don Quixote",
    ],
    "historical_event": [
        "the fall of Rome", "the French Revolution", "the moon landing",
        "the Industrial Revolution", "World War I", "the Chernobyl disaster",
        "the Berlin Wall falling", "the Renaissance", "the Black Death",
        "the discovery of penicillin", "the printing press invention",
    ],
    "country": [
        "Japan", "Brazil", "Nigeria", "India", "Germany", "Canada",
        "Australia", "Egypt", "Mexico", "South Korea", "Sweden", "Kenya",
    ],
    "concept": [
        "justice", "democracy", "existentialism", "utilitarianism",
        "Stoicism", "the subconscious", "cognitive dissonance",
        "confirmation bias", "Occam's razor", "the trolley problem",
    ],
    "topic_a": [
        "capitalism", "democracy", "individualism", "science",
        "technology", "globalization", "urbanization", "secularism",
    ],
    "topic_b": [
        "socialism", "authoritarianism", "collectivism", "religion",
        "nature", "nationalism", "rural life", "spirituality",
    ],
    "alternative_topic": [
        "classical mechanics", "Newtonian physics", "monarchy",
        "tradition", "analog technology", "local economies",
    ],

    # Current events / news
    "news_topic": [
        "the war in Ukraine", "climate policy", "inflation", "tech layoffs",
        "space exploration", "AI regulation", "healthcare reform",
        "immigration policy", "energy prices", "cybersecurity breaches",
        "cryptocurrency markets", "electric vehicles", "genetic engineering",
    ],
    "ongoing_event": [
        "the Israel-Gaza conflict", "the war in Sudan", "the COP climate summit",
        "the Olympic Games", "the World Cup", "the US presidential election",
        "the EU digital markets act", "the WHO pandemic treaty",
    ],
    "country_or_region": [
        "the Middle East", "Europe", "Sub-Saharan Africa", "Southeast Asia",
        "Latin America", "the Arctic", "the Pacific Islands",
        "Ukraine", "Taiwan", "Iran", "North Korea", "Myanmar",
    ],
    "political_topic": [
        "the UN Security Council", "NATO expansion", "Brexit consequences",
        "the Iran nuclear deal", "trade war between US and China",
    ],
    "sports_team": [
        "Manchester United", "Real Madrid", "the Lakers", "the Yankees",
        "the All Blacks", "Barcelona", "Bayern Munich",
    ],

    # Medical
    "medical_condition": [
        "type 2 diabetes", "hypertension", "major depressive disorder",
        "rheumatoid arthritis", "Crohn's disease", "multiple sclerosis",
        "Parkinson's disease", "Alzheimer's disease", "asthma",
        "atrial fibrillation", "chronic kidney disease", "hepatitis C",
        "osteoporosis", "glaucoma", "migraine", "epilepsy",
        "COPD", "sleep apnea", "fibromyalgia", "PCOS",
    ],
    "medication": [
        "metformin", "lisinopril", "atorvastatin", "amlodipine",
        "metoprolol", "omeprazole", "levothyroxine", "albuterol",
        "gabapentin", "prednisone", "sertraline", "fluoxetine",
        "warfarin", "rivaroxaban", "insulin glargine", "semaglutide",
        "adalimumab", "etanercept", "methotrexate", "azathioprine",
    ],
    "medication_a": [
        "warfarin", "lisinopril", "metformin", "sertraline",
        "amoxicillin", "ibuprofen", "atorvastatin", "omeprazole",
    ],
    "medication_b": [
        "aspirin", "potassium supplements", "grapefruit juice", "alcohol",
        "St. John's Wort", "NSAIDs", "clarithromycin", "digoxin",
    ],
    "symptom": [
        "chest pain", "shortness of breath", "unexplained weight loss",
        "blood in stool", "persistent cough", "severe headache",
        "vision changes", "numbness in limbs", "persistent fever",
    ],
    "medical_test": [
        "HbA1c", "C-reactive protein", "LDL cholesterol", "eGFR",
        "troponin", "D-dimer", "PSA", "CEA", "MRI with contrast",
    ],
    "medical_condition_a": ["Crohn's disease", "ulcerative colitis", "IBS"],
    "medical_condition_b": ["rheumatoid arthritis", "osteoarthritis", "gout"],

    # Creative
    "creative_topic": [
        "a robot who falls in love", "the last library on Earth",
        "a detective in a world without lies", "the first human on Mars",
        "a ship that sails between dimensions", "a city built on the back of a giant turtle",
        "time travel gone wrong", "a negotiation with Death",
        "the invention of color in a grayscale world", "a message from the future",
    ],
    "scenario": [
        "humans can photosynthesize", "gravity reverses every night",
        "memories become currency", "animals gain human intelligence",
        "the internet becomes sentient", "fossil fuels never existed",
    ],
    "famous_person_a": [
        "Marie Curie", "Nikola Tesla", "Frida Kahlo", "Alan Turing",
        "Ada Lovelace", "Sun Tzu", "Hypatia", "Ibn Sina",
    ],
    "famous_person_b": [
        "Albert Einstein", "Thomas Edison", "Pablo Picasso", "Charles Babbage",
        "Grace Hopper", "Confucius", "Eratosthenes", "Al-Khwarizmi",
    ],
    "natural_phenomenon": [
        "thunder", "rainbows", "volcanic eruptions", "the tides",
        "earthquakes", "aurora borealis", "whirlpools", "sand dunes",
    ],
    "historical_figure": [
        "Julius Caesar", "Cleopatra", "Leonardo da Vinci", "Genghis Khan",
        "Queen Elizabeth I", "Catherine the Great", "Marcus Aurelius",
    ],
    "another_historical_figure": [
        "Cicero", "Mark Antony", "Lorenzo de Medici", "Kublai Khan",
        "Francis Drake", "Voltaire", "Seneca",
    ],

    # Coding / tech
    "code_snippet": [
        "def foo(): pass  # expected return value missing",
        "for i in range(n): print(i)  # infinite loop suspected",
        "import tensorflow as tf  # ModuleNotFoundError",
        "SELECT * FROM users WHERE id = {user_id}  # SQL injection risk",
        "const x = null; x.toString()  # TypeError",
        "malloc(sizeof(int) * n)  # potential memory leak",
        "async function() { await fetch(url) }  # unhandled rejection",
    ],
    "error_type": [
        "Segmentation fault", "null pointer exception", "IndexError",
        "KeyError", "AttributeError", "TypeError", "MemoryError",
        "StackOverflowError", "Deadlock detected", "Race condition",
    ],
    "language": [
        "Spanish", "Mandarin", "French", "German", "Japanese",
        "Arabic", "Russian", "Portuguese", "Italian", "Korean",
        "Hindi", "Swahili", "Dutch", "Polish", "Turkish",
    ],
    "phrase": [
        "hello", "thank you very much", "where is the bathroom",
        "I love you", "good morning", "see you tomorrow",
        "how much does this cost", "I need help", "nice to meet you",
    ],
    "math_expression": [
        "2+2", "the integral of x squared", "the derivative of e to the x",
        "15 percent of 240", "the square root of 144",
        "log base 2 of 64", "sin of 30 degrees",
    ],
    "math_problem": [
        "3x + 7 = 22 for x", "the area of a circle with radius 5",
        "the factorial of 6", "the greatest common divisor of 48 and 18",
    ],

    # Practical / life
    "life_decision": [
        "learn Python or JavaScript first", "buy or rent a house",
        "get a master's degree", "switch careers to tech",
        "start my own business", "move to a different city",
    ],
    "life_situation": [
        "dealing with burnout", "negotiating a salary raise",
        "managing remote work", "improving public speaking",
        "building a professional network", "work-life balance",
    ],
    "project_topic": [
        "a mobile app for mental health", "a sustainable food delivery service",
        "an open source documentation tool", "a community garden initiative",
        "a podcast about local history", "a tool for language learning",
    ],
    "recipient": [
        "my boss", "a client", "my professor", "a hiring manager",
        "my landlord", "customer support",
    ],
    "text_snippet": [
        "The quick brown fox jumps over the lazy dog.",
        "Climate change refers to long-term shifts in temperatures and weather patterns.",
        "Photosynthesis is the process by which plants use sunlight to synthesize foods.",
    ],

    # Time / location
    "location": [
        "Tokyo", "New York", "London", "Sydney", "Berlin",
        "Paris", "Moscow", "Beijing", "Dubai", "Rio de Janeiro",
        "Mumbai", "Cairo", "Istanbul", "Bangkok", "Seoul",
        "Los Angeles", "Chicago", "Toronto", "Mexico City", "Lagos",
    ],
    "location_a": ["New York", "London", "Tokyo", "Sydney"],
    "location_b": ["Los Angeles", "Paris", "Beijing", "Dubai"],
    "date_reference": [
        "March 15", "next Tuesday", "the third Thursday of November",
        "leap day", "New Year's Day 2025",
    ],
    "event_name": [
        "Christmas", "my birthday", "the eclipse", "the conference",
        "the product launch", "the deadline",
    ],
    "holiday_name": [
        "Thanksgiving", "Easter", "Ramadan", "Diwali",
        "Chinese New Year", "Passover", "Halloween",
    ],
}


def fill_template(template: str) -> str:
    """Replace {slot} placeholders with random values."""
    result = template
    for slot, values in SLOT_VALUES.items():
        placeholder = f"{{{slot}}}"
        while placeholder in result:
            result = result.replace(placeholder, random.choice(values), 1)
    return result


def generate_synthetic_examples(intent_family: str, count: int) -> list[dict]:
    """Generate synthetic labeled examples for a given intent family."""
    templates = SYNTHETIC_TEMPLATES.get(intent_family, [])
    if not templates:
        return []

    examples = []
    for _ in range(count):
        template = random.choice(templates)
        query = fill_template(template)

        route = _intent_to_default_route(intent_family)
        evidence = "required" if intent_family in ("medical_inquiry", "current_evidence") else "not_required"
        policy = "none"

        examples.append({
            "query": query,
            "labels": {
                "intent_family": intent_family,
                "evidence_mode": evidence,
                "route": route,
                "policy_override": policy,
            },
            "metadata": {
                "source": "synthetic_v2",
                "confidence": 1.0,
                "template": template,
            }
        })

    return examples


def _intent_to_default_route(intent: str) -> str:
    mapping = {
        "local_answer": "LOCAL",
        "background_overview": "LOCAL_WITH_FALLBACK",
        "technical_explanation": "LOCAL_WITH_FALLBACK",
        "current_evidence": "AUGMENTED",
        "news_request": "NEWS",
        "time_query": "TIME",
        "medical_inquiry": "AUGMENTED",
        "creative_writing": "LOCAL",
        "clarification": "CLARIFY",
    }
    return mapping.get(intent, "LOCAL")


def load_historical_data(path: Path) -> list[dict]:
    """Load historical examples from JSONL."""
    if not path.exists():
        return []
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def balance_dataset(examples: list[dict], target_per_class: int) -> list[dict]:
    """Oversample rare classes with synthetic data to reach target count."""
    from collections import Counter

    intent_counts = Counter(ex["labels"]["intent_family"] for ex in examples)
    balanced = list(examples)

    for intent, count in intent_counts.items():
        if count < target_per_class:
            needed = target_per_class - count
            synthetic = generate_synthetic_examples(intent, needed)
            balanced.extend(synthetic)
            print(f"  Generated {needed} synthetic examples for {intent}")

    # Also generate for completely missing classes
    all_intents = set(SYNTHETIC_TEMPLATES.keys())
    present_intents = set(intent_counts.keys())
    for intent in all_intents - present_intents:
        synthetic = generate_synthetic_examples(intent, target_per_class)
        balanced.extend(synthetic)
        print(f"  Generated {target_per_class} synthetic examples for missing class {intent}")

    random.shuffle(balanced)
    return balanced


def load_and_balance_data(config: dict[str, Any]) -> tuple[list[dict], list[dict], list[dict]]:
    """Load historical data, augment with synthetic, split train/val/test."""
    historical_path = Path(config.get("historical_path", "historical_routes.jsonl"))
    target_per_class = config.get("target_per_class", 50)
    val_ratio = config.get("val_ratio", 0.15)
    test_ratio = config.get("test_ratio", 0.15)

    historical = load_historical_data(historical_path)
    print(f"Loaded {len(historical)} historical examples")

    balanced = balance_dataset(historical, target_per_class)
    print(f"Balanced dataset size: {len(balanced)}")

    # Stratified split
    from collections import defaultdict
    by_intent = defaultdict(list)
    for ex in balanced:
        by_intent[ex["labels"]["intent_family"]].append(ex)

    train, val, test = [], [], []
    for intent, examples in by_intent.items():
        random.shuffle(examples)
        n = len(examples)
        n_test = int(n * test_ratio)
        n_val = int(n * val_ratio)
        test.extend(examples[:n_test])
        val.extend(examples[n_test:n_test + n_val])
        train.extend(examples[n_test + n_val:])

    random.shuffle(train)
    random.shuffle(val)
    random.shuffle(test)

    return train, val, test


class RouterDataset(Dataset):
    """PyTorch Dataset for router classification."""

    def __init__(self, examples: list[dict], tokenizer, max_length: int = 256):
        self.examples = examples
        self.tokenizer = tokenizer
        self.max_length = max_length

        # Build label mappings
        all_intents = sorted({ex["labels"]["intent_family"] for ex in examples})
        all_evidence = sorted({ex["labels"]["evidence_mode"] for ex in examples})
        all_routes = sorted({ex["labels"]["route"] for ex in examples})
        all_policies = sorted({ex["labels"]["policy_override"] for ex in examples})

        self.intent2idx = {l: i for i, l in enumerate(all_intents)}
        self.evidence2idx = {l: i for i, l in enumerate(all_evidence)}
        self.route2idx = {l: i for i, l in enumerate(all_routes)}
        self.policy2idx = {l: i for i, l in enumerate(all_policies)}

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        ex = self.examples[idx]
        query = ex["query"]
        labels = ex["labels"]

        encoding = self.tokenizer(
            query,
            truncation=True,
            max_length=self.max_length,
            padding="max_length",
            return_tensors="pt",
        )

        return {
            "input_ids": encoding["input_ids"].squeeze(0),
            "attention_mask": encoding["attention_mask"].squeeze(0),
            "labels": {
                "intent": torch.tensor(self.intent2idx[labels["intent_family"]], dtype=torch.long),
                "evidence": torch.tensor(self.evidence2idx[labels["evidence_mode"]], dtype=torch.long),
                "route": torch.tensor(self.route2idx[labels["route"]], dtype=torch.long),
                "policy": torch.tensor(self.policy2idx[labels["policy_override"]], dtype=torch.long),
            },
        }


def generate_large_dataset(target_total: int = 1000) -> list[dict]:
    """Generate a large synthetic dataset by oversampling templates."""
    from collections import Counter
    
    examples = []
    intents = list(SYNTHETIC_TEMPLATES.keys())
    
    # Generate evenly distributed examples
    per_intent = target_total // len(intents)
    
    for intent in intents:
        intent_examples = generate_synthetic_examples(intent, per_intent)
        examples.extend(intent_examples)
    
    # Fill remainder
    while len(examples) < target_total:
        intent = random.choice(intents)
        examples.extend(generate_synthetic_examples(intent, 1))
    
    random.shuffle(examples)
    return examples[:target_total]
