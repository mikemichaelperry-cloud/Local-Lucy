#!/usr/bin/env python3
"""
Generate synthetic training examples to fill critical route gaps.

Produces examples in the same format as comprehensive_examples.json
and appends them to comprehensive_examples_clean.json.
"""

import json
import random
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
CLEAN_PATH = ROOT / "comprehensive_examples_clean.json"
FLAGGED_PATH = ROOT / "comprehensive_examples_flagged.json"
OUTPUT_PATH = ROOT / "comprehensive_examples_augmented.json"


def _make_example(query: str, route: str, intent_family: str = "", evidence_mode: str = "") -> dict:
    """Build a single example in the comprehensive_examples format."""
    if not intent_family:
        intent_family = {
            "LOCAL": "local_answer",
            "AUGMENTED": "synthesis_explanation",
            "EVIDENCE": "evidence_request",
            "NEWS": "current_evidence",
            "TIME": "local_answer",
            "WEATHER": "local_answer",
            "EPHEMERAL": "ephemeral_query",
        }.get(route, "local_answer")

    if not evidence_mode:
        evidence_mode = "required" if route == "EVIDENCE" else "not_required"

    return {
        "query": query,
        "labels": {
            "intent_family": intent_family,
            "evidence_mode": evidence_mode,
            "route": route,
            "policy_override": "none",
        },
        "metadata": {
            "source": "synthetic_augmentation",
            "feedback_type": "manual_label",
        },
    }


# ---------------------------------------------------------------------------
# EVIDENCE examples: medical, legal, financial, scientific
# These MUST require citations / trusted sources
# ---------------------------------------------------------------------------

_EVIDENCE_MEDICAL = [
    "What are the symptoms of appendicitis?",
    "What is the recommended treatment for type 2 diabetes?",
    "What are the side effects of metformin?",
    "How is strep throat diagnosed?",
    "What are the early signs of melanoma?",
    "What is the prognosis for stage 1 breast cancer?",
    "What antibiotics are prescribed for bacterial pneumonia?",
    "What are the symptoms of a concussion?",
    "How is high blood pressure treated?",
    "What is the standard dosage of amoxicillin for adults?",
    "What are the contraindications for ibuprofen?",
    "What are the symptoms of COVID-19?",
    "How effective is the flu vaccine?",
    "What is the recovery time for a torn ACL?",
    "What are the risk factors for heart disease?",
    "What is the difference between a CT scan and an MRI?",
    "What are the symptoms of Lyme disease?",
    "How is asthma managed long-term?",
    "What are the warning signs of a stroke?",
    "What is the treatment for gout?",
    "What are the symptoms of hypothyroidism?",
    "How is sleep apnea diagnosed?",
    "What are the side effects of statins?",
    "What is the recommended screening age for colon cancer?",
    "What are the symptoms of kidney stones?",
]

_EVIDENCE_LEGAL = [
    "What are my tenant rights if my landlord raises rent by 20%?",
    "What is the statute of limitations for personal injury claims?",
    "What does GDPR require for data consent?",
    "What are the penalties for copyright infringement?",
    "How is child custody determined in divorce proceedings?",
    "What is the legal definition of self-defense?",
    "What are the requirements for a valid will?",
    "What is the difference between a felony and a misdemeanor?",
    "What are the labor laws regarding overtime pay?",
    "What is the legal process for trademark registration?",
]

_EVIDENCE_FINANCIAL = [
    "What is the current Federal Reserve interest rate?",
    "What are the SEC reporting requirements for public companies?",
    "What is the difference between a Roth IRA and a traditional IRA?",
    "What are the tax implications of capital gains?",
    "What is the current inflation rate?",
    "What are the reserve requirements for banks?",
    "What is the difference between stocks and bonds?",
    "What are the FINRA rules for broker-dealers?",
    "What is the legal retirement age for full Social Security benefits?",
    "What are the Basel III capital requirements?",
]

_EVIDENCE_SCIENTIFIC = [
    "What does the latest research say about intermittent fasting?",
    "What evidence supports the theory of anthropogenic climate change?",
    "What are the peer-reviewed findings on meditation and stress reduction?",
    "What does current research say about the effectiveness of masks for respiratory viruses?",
    "What are the established facts about herd immunity thresholds?",
    "What does the scientific consensus say about GMO safety?",
    "What evidence exists for the health effects of microplastics?",
    "What do clinical trials show about the efficacy of SSRIs for depression?",
]

# Conversational prefixes to prepend
_CONVERSATIONAL_PREFIXES = [
    "",
    "Can you tell me ",
    "I need to know ",
    "Do you know ",
    "Please explain ",
    "I'm trying to understand ",
    "My doctor mentioned this but I forgot: ",
    "For a school paper, ",
    "I'm doing research on ",
]


def _generate_evidence_examples(target: int = 50) -> list[dict]:
    """Generate diverse EVIDENCE examples."""
    all_templates = _EVIDENCE_MEDICAL + _EVIDENCE_LEGAL + _EVIDENCE_FINANCIAL + _EVIDENCE_SCIENTIFIC
    examples = []
    used = set()

    # First, add prefixed variants for variety
    for template in all_templates:
        if len(examples) >= target:
            break
        prefix = random.choice(_CONVERSATIONAL_PREFIXES)
        q = prefix + template[0].lower() + template[1:] if prefix and template else template
        if q not in used:
            used.add(q)
            examples.append(_make_example(q, "EVIDENCE"))

    # Fill remaining with rephrased variants
    rephrases = {
        "What are the symptoms of appendicitis?": [
            "How do I know if I have appendicitis?",
            "What does appendicitis feel like?",
            "Signs and symptoms of appendicitis",
        ],
        "What is the recommended treatment for type 2 diabetes?": [
            "Standard care protocol for type 2 diabetes",
            "First-line treatment for diabetes mellitus type 2",
        ],
        "What are my tenant rights if my landlord raises rent by 20%?": [
            "Is a 20% rent increase legal?",
            "Tenant protection against excessive rent hikes",
        ],
    }

    for originals in rephrases.values():
        if len(examples) >= target:
            break
        for q in originals:
            if q not in used:
                used.add(q)
                examples.append(_make_example(q, "EVIDENCE"))

    return examples[:target]


# ---------------------------------------------------------------------------
# WEATHER examples
# ---------------------------------------------------------------------------

_WEATHER_TEMPLATES = [
    "What is the weather like today?",
    "Will it rain tomorrow?",
    "What's the forecast for this weekend?",
    "How hot will it be on Thursday?",
    "Is there a storm warning for my area?",
    "What's the temperature right now?",
    "Do I need an umbrella today?",
    "What's the humidity level?",
    "Is it going to snow this week?",
    "What time does the sun set today?",
    "What's the wind speed?",
    "How's the weather in Paris?",
    "What's the weather forecast for London next week?",
    "Is there a heat wave coming?",
    "What's the UV index today?",
    "Will there be frost tonight?",
    "What's the visibility like?",
    "Is it safe to drive in this weather?",
    "What's the pollen count today?",
    "When will the rain stop?",
    "What's the weather like in Tokyo right now?",
    "Is there a tornado warning?",
    "What's the air quality index?",
    "Will it be sunny for the picnic on Saturday?",
    "What's the weather forecast for my vacation in Hawaii?",
    "Is it going to be foggy in the morning?",
    "What's the weather like at the beach?",
    "Do I need to winterize my car?",
    "What's the climate like in Iceland?",
    "When is hurricane season?",
]

_WEATHER_PREFIXES = [
    "",
    "Hey Lucy, ",
    "Can you check ",
    "Quick question: ",
    "I'm planning a trip, ",
    "Before I leave, ",
    "Do you know if ",
    "I heard on the news that ",
    "My app says it's raining but ",
]


def _generate_weather_examples(target: int = 50) -> list[dict]:
    """Generate diverse WEATHER examples."""
    examples = []
    used = set()

    for template in _WEATHER_TEMPLATES:
        if len(examples) >= target:
            break
        prefix = random.choice(_WEATHER_PREFIXES)
        q = prefix + template[0].lower() + template[1:] if prefix and template else template
        if q not in used:
            used.add(q)
            examples.append(_make_example(q, "WEATHER"))

    # Add some multilingual / variant examples
    extras = [
        "Wie ist das Wetter heute?",
        "Quel temps fait-il?",
        "¿Cómo está el clima?",
        "Che tempo fa?",
        "What's the weather forecast for tomorrow morning?",
        "Is it supposed to be windy this afternoon?",
        "Will the temperature drop below freezing tonight?",
        "What's the 5-day forecast?",
        "Is there a chance of thunderstorms?",
        "How much snow are we expecting?",
    ]

    for q in extras:
        if len(examples) >= target:
            break
        if q not in used:
            used.add(q)
            examples.append(_make_example(q, "WEATHER"))

    return examples[:target]


# ---------------------------------------------------------------------------
# TIME examples
# ---------------------------------------------------------------------------

_TIME_TEMPLATES = [
    "What time is it?",
    "What time is it in Tokyo?",
    "What timezone is Berlin in?",
    "What time does the store close?",
    "When does the train leave?",
    "What are the opening hours?",
    "What time is sunset today?",
    "How many hours behind is California?",
    "What is UTC+3?",
    "When do the markets open?",
    "What time is it in London right now?",
    "What timezone am I in?",
    "When does daylight saving time start?",
    "What time is the meeting?",
    "How late is the pharmacy open?",
    "What is the time difference between New York and Paris?",
    "When is the next bus?",
    "What time does the museum close on Sundays?",
    "What is the current time in Sydney?",
    "How many time zones are there?",
    "What time is it in India?",
    "When is the last train home?",
    "What are the business hours for the bank?",
    "What time does school start?",
    "When is the deadline?",
    "What time is sunrise tomorrow?",
    "How do I convert PST to EST?",
    "What is the time in Dubai?",
    "When does the flight depart?",
    "What time is it in São Paulo?",
]

_TIME_PREFIXES = [
    "",
    "Quick question: ",
    "Can you tell me ",
    "I need to know ",
    "Hey Lucy, ",
    "Do you know ",
    "Before I call them, ",
    "I'm scheduling a meeting, ",
    "My watch is broken, ",
]


def _generate_time_examples(target: int = 60) -> list[dict]:
    """Generate diverse TIME examples."""
    examples = []
    used = set()

    for template in _TIME_TEMPLATES:
        if len(examples) >= target:
            break
        prefix = random.choice(_TIME_PREFIXES)
        q = prefix + template[0].lower() + template[1:] if prefix and template else template
        if q not in used:
            used.add(q)
            examples.append(_make_example(q, "TIME"))

    # Add multilingual extras
    extras = [
        "Wie spät ist es?",
        "Quelle heure est-il?",
        "¿Qué hora es?",
        "Che ore sono?",
        "What time is it in Moscow right now?",
        "What timezone is New York in during summer?",
        "When does the stock market open in London?",
        "What time does the concert start?",
        "How many hours ahead is Japan?",
        "What is the time in Vancouver?",
        "When does the library close today?",
        "What time is it in Cape Town?",
    ]

    for q in extras:
        if len(examples) >= target:
            break
        if q not in used:
            used.add(q)
            examples.append(_make_example(q, "TIME"))

    return examples[:target]


# ---------------------------------------------------------------------------
# NEWS examples (also underrepresented)
# ---------------------------------------------------------------------------

_NEWS_TEMPLATES = [
    "What's the latest news?",
    "Any breaking news today?",
    "What's happening in the Middle East?",
    "Latest updates on the election",
    "News about the economy",
    "What's going on in Ukraine?",
    "Any news about the hurricane?",
    "What are the headlines?",
    "Latest developments in the trial",
    "News about climate change",
    "What's the latest on the pandemic?",
    "Any updates on the peace talks?",
    "What's happening at the border?",
    "Latest tech news",
    "News about the stock market crash",
    "What happened at the summit?",
    "Any news about the wildfires?",
    "What's the latest from the UN?",
    "News about the protest",
    "What are the latest poll results?",
    "Any updates on the infrastructure bill?",
    "What's happening in the tech industry?",
    "Latest sports news",
    "News about the drought",
    "What happened in Parliament today?",
]


def _generate_news_examples(target: int = 60) -> list[dict]:
    """Generate diverse NEWS examples."""
    examples = []
    used = set()

    for template in _NEWS_TEMPLATES:
        if len(examples) >= target:
            break
        prefix = random.choice(_CONVERSATIONAL_PREFIXES)
        q = prefix + template[0].lower() + template[1:] if prefix and template else template
        if q not in used:
            used.add(q)
            examples.append(_make_example(q, "NEWS"))

    return examples[:target]


# ---------------------------------------------------------------------------
# Also salvage correctly-labeled flagged examples
# ---------------------------------------------------------------------------

def _salvage_flagged() -> list[dict]:
    """Pull any flagged examples that were actually correctly labeled."""
    if not FLAGGED_PATH.exists():
        return []

    with open(FLAGGED_PATH) as f:
        flagged = json.load(f)

    # We want to salvage medical queries that were flagged as 'no_AUGMENTED_keywords'
    # but should actually be EVIDENCE (not AUGMENTED)
    salvageable = []
    medical_keywords = ["symptoms", "treatment", "diagnosis", "side effects", "dosage",
                        "prescribed", "medication", "drug", "vaccine", "vaccination",
                        "antibiotics", "metformin", "ibuprofen", "aspirin", "warfarin",
                        "acetaminophen", "tadalafil", "strep throat", "migraine",
                        "concussion", "appendicitis", "diabetes", "cancer", "pneumonia"]

    for ex in flagged:
        reason = ex.get("_flag_reason", "")
        query = ex["query"].lower()
        route = ex["labels"]["route"]

        # Medical queries flagged as suspicious in AUGMENTED/LOCAL should be EVIDENCE
        if any(kw in query for kw in medical_keywords):
            if route in ("AUGMENTED", "LOCAL"):
                ex_copy = {k: v for k, v in ex.items() if not k.startswith("_")}
                ex_copy["labels"] = dict(ex_copy["labels"])
                ex_copy["labels"]["route"] = "EVIDENCE"
                ex_copy["labels"]["evidence_mode"] = "required"
                ex_copy["labels"]["intent_family"] = "evidence_request"
                ex_copy["metadata"]["source"] = "salvaged_from_flagged"
                salvageable.append(ex_copy)
                continue

        # Weather queries that were wrongly flagged
        weather_keywords = ["weather", "forecast", "rain", "snow", "sunny", "temperature",
                            "humid", "storm", "wind", "cold", "hot", "wetter", "pronostico",
                            "météo", "tiempo"]
        if any(kw in query for kw in weather_keywords):
            if route == "WEATHER" and "no_WEATHER_keywords" in reason:
                # This was a false flag (e.g. foreign language weather)
                ex_copy = {k: v for k, v in ex.items() if not k.startswith("_")}
                ex_copy["metadata"]["source"] = "salvaged_from_flagged"
                salvageable.append(ex_copy)
                continue

        # News queries that were wrongly flagged
        news_keywords = ["news", "breaking", "latest", "headline", "update", "happening"]
        if any(kw in query for kw in news_keywords):
            if route == "NEWS" and "no_NEWS_keywords" in reason:
                ex_copy = {k: v for k, v in ex.items() if not k.startswith("_")}
                ex_copy["metadata"]["source"] = "salvaged_from_flagged"
                salvageable.append(ex_copy)
                continue

    return salvageable


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Loading clean data...")
    with open(CLEAN_PATH) as f:
        clean = json.load(f)
    print(f"  Clean examples: {len(clean)}")

    # Count current distribution
    from collections import Counter
    old_routes = Counter(ex["labels"]["route"] for ex in clean)

    # Generate synthetic
    print("\nGenerating synthetic examples...")
    synthetic = []
    synthetic.extend(_generate_evidence_examples(50))
    synthetic.extend(_generate_weather_examples(50))
    synthetic.extend(_generate_time_examples(60))
    synthetic.extend(_generate_news_examples(60))
    print(f"  Synthetic generated: {len(synthetic)}")

    # Salvage flagged
    print("\nSalvaging flagged examples...")
    salvaged = _salvage_flagged()
    print(f"  Salvaged: {len(salvaged)}")

    # Combine and deduplicate
    all_examples = clean + synthetic + salvaged
    seen = set()
    deduped = []
    for ex in all_examples:
        q = ex["query"].strip().lower()
        if q not in seen:
            seen.add(q)
            deduped.append(ex)

    new_routes = Counter(ex["labels"]["route"] for ex in deduped)

    print(f"\n--- BEFORE vs AFTER ---")
    print(f"{'Route':<15} {'Before':>8} {'After':>8} {'Target':>8}")
    print("-" * 45)
    targets = {"LOCAL": 300, "AUGMENTED": 150, "NEWS": 60, "TIME": 60, "WEATHER": 50, "EVIDENCE": 50, "EPHEMERAL": 30}
    for route in ["LOCAL", "AUGMENTED", "EVIDENCE", "NEWS", "TIME", "WEATHER", "EPHEMERAL"]:
        before = old_routes.get(route, 0)
        after = new_routes.get(route, 0)
        target = targets.get(route, "N/A")
        print(f"{route:<15} {before:>8} {after:>8} {str(target):>8}")

    print(f"\nTotal: {len(clean)} → {len(deduped)} (+{len(deduped) - len(clean)})")

    # Write output
    with open(OUTPUT_PATH, "w") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)

    print(f"\nWrote: {OUTPUT_PATH}")
    print("\nNext steps:")
    print("  1. Review a few synthetic examples for quality")
    print("  2. Replace comprehensive_examples.json with augmented version:")
    print(f"     cp {OUTPUT_PATH} {ROOT / 'comprehensive_examples.json'}")
    print("  3. Rebuild embeddings:")
    print("     python scripts/rebuild_embeddings.py")


if __name__ == "__main__":
    main()
