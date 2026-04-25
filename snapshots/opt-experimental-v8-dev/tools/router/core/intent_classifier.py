#!/usr/bin/env python3
import re
from typing import Dict, List, Optional

from input_normalizer import normalize_input
from medical_query_heuristics import detect_human_medication_query, has_human_medication_topic_query
from routing_signals import (
    build_common_signal_flags,
    has_conflict_term,
    has_news_term,
    has_temporal_signal,
    is_probable_culinary_source_misrecognition,
    is_time_query,
    should_use_israel_news_region,
)

TRAVEL_DESTINATIONS = (
    "bali",
    "iran",
    "israel",
    "ukraine",
    "russia",
    "lebanon",
    "syria",
    "gaza",
    "jordan",
    "egypt",
    "turkey",
    "thailand",
    "japan",
    "greece",
)


def _has_re(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _contains_any(text: str, values: List[str]) -> bool:
    return any(v in text for v in values)


def _news_region_filter(text: str) -> Optional[str]:
    if should_use_israel_news_region(text):
        return "IL"
    mapping = {
        "world": None,
        "australia": "AU",
        "australian": "AU",
        "uk": "GB",
        "u.k.": "GB",
        "british": "GB",
        "united kingdom": "GB",
    }
    topical = has_news_term(text) or has_conflict_term(text) or _has_re(text, r"\bdevelopments?|talks?|hostilities\b")
    for key, value in mapping.items():
        if _has_re(text, rf"\b{re.escape(key)}\b") and topical:
            return value
    return None


def _strict_israeli_sources(text: str) -> bool:
    return _has_re(
        text,
        r"\b(from|only)\s+israeli\s+sources\b"
        r"|\bonly\s+sources?\s+from\s+israel\b"
        r"|\bonly\s+israeli\s+sources\b"
        r"|\bnews\s+from\s+only\s+israeli\s+sources\b",
    )


def _is_global_policy_query(text: str) -> bool:
    if _has_re(
        text,
        r"\b("
        r"climate policy|climate regulation|emissions policy|carbon policy|"
        r"ai safety|ai regulation|ai governance|technology regulation|"
        r"technology governance|tech governance|digital regulation|"
        r"financial regulation|financial policy|banking regulation|market regulation"
        r")\b",
    ):
        return True
    domain_hits = 0
    if _has_re(text, r"\b(climate|emissions|carbon)\b"):
        domain_hits += 1
    if _has_re(text, r"\b(ai|artificial intelligence|technology)\b"):
        domain_hits += 1
    if _has_re(text, r"\b(financial|banking|market)\b"):
        domain_hits += 1
    return domain_hits >= 2 and _has_re(
        text,
        r"\b(global policy|policy developments?|regulatory direction|technology regulation|financial regulation|policy interaction|how they interact|across)\b",
    )


def _prefer_domains_for_primary_doc(text: str) -> List[str]:
    domains: List[str] = []
    domain_hints = (
        ("ti.com", r"\b(ti|texas instruments|tl07\d|lm3\d{2,4})\b"),
        ("analog.com", r"\b(analog devices|analog|op07|ad\d{2,4})\b"),
        ("st.com", r"\b(stmicro|stmicroelectronics|stm32|st\.com)\b"),
        ("microchip.com", r"\b(microchip|pic16|pic18|atmega|avr)\b"),
        ("onsemi.com", r"\b(onsemi|ne\d{2,4}|lm\d{2,4})\b"),
    )
    for domain, pattern in domain_hints:
        if _has_re(text, pattern) and domain not in domains:
            domains.append(domain)
    if not domains:
        domains = [
            "ti.com",
            "analog.com",
            "st.com",
            "microchip.com",
            "onsemi.com",
            "nxp.com",
            "infineon.com",
        ]
    return domains


def _identity_variant(text: str) -> str:
    if _has_re(text, r"\b(who are you|what is your name|what's your name|whats your name)\b"):
        return "self"
    if _has_re(text, r"\b(who am i|what is my name|what's my name|whats my name|who is (mike|michael))\b"):
        return "user"
    if _has_re(
        text,
        r"\b(who is oscar|tell me about oscar|who is racheli|who is rachele|who is rachel|tell me about racheli|tell me about rachel|what is our relationship|who are we to each other)\b",
    ):
        return "relationship"
    return ""


def _is_conversational(text: str) -> bool:
    if _has_re(text, r"^\s*(not necessary|no thanks|never mind)[.!?]?\s*$"):
        return True
    if _has_re(text, r"\bshould i invest\b") and not _has_re(
        text, r"\b(data|cite|citation|citations|source|sources|current rates|price|quote)\b"
    ):
        return True
    if _has_re(text, r"^\s*(hi|hello|hey)\b") or _has_re(text, r"\bhow are you\b"):
        return True
    if _has_re(
        text,
        r"\b(i feel|what do you think about|help me decide|how should i handle|what should i do about|can we talk about|my (friend|partner|family|boss)|overthink|discipline|annoyed|burnout|lonely|motivation|why do people|ghost friends)\b",
    ):
        return True
    return False


def _is_creative_writing(text: str) -> bool:
    """
    Detect creative writing requests that should ALWAYS use local model.
    
    Creative writing (stories, poems, fiction) works best with local model because:
    - No identity preamble issues ("I'm Local Lucy...")
    - Better privacy for personal/fictional content
    - Sufficient capability for creative tasks
    - Avoids unnecessary augmentation costs/latency
    """
    # Normalize: lowercase, strip quotes
    t = text.lower().strip().replace('"', '').replace("'", "")
    
    # Primary creative writing patterns (flexible matching)
    # Pattern: action + (optional adjectives) + creative_type
    creative_patterns = [
        # "write me a [very long] story/poem/..."
        r"\bwrite me\s+(a|an)\s+([\w\s]+)?\b(story|poem|poetry|fiction|tale|narrative|fable|parable|haiku|verse)",
        # "write me [a] short story" (without explicit "a" - common colloquial)
        r"\bwrite me\s+([\w\s]+)?\b(story|poem|tale|fiction|haiku)\s+about\b",
        # "tell me a [short] story/..."
        r"\btell me\s+(a|an)\s+([\w\s]+)?\b(story|tale|fable)",
        # "create a [short] story/poem/..."
        r"\bcreate\s+(a|an)\s+([\w\s]+)?\b(story|poem|fiction|tale|scenario|scene|narrative)",
        # "make up a [short] story/..."
        r"\bmake up\s+(a|an)\s+([\w\s]+)?\b(story|tale|scenario|fable)",
        # "can/could you write [me] a [short] story/..."
        r"\b(can you|could you)\s+write\b.*\b(story|poem|fiction|poetry|tale|haiku|verse)",
        # "write a [short] story/poem/scene/..." (without "me")
        r"\bwrite\s+(a|an)\s+([\w\s]+)?\b(story|poem|tale|fiction|poetry|haiku|verse|scene|scenario)",
    ]
    
    for pattern in creative_patterns:
        if _has_re(t, pattern):
            return True
    
    # Direct story/poem requests (at start of query)
    direct_patterns = [
        r"^(write|tell|create|imagine|draft)\s+(me\s+)?(a|an)\s+([\w\s]+)?\b(story|poem|poetry|fiction|tale|haiku|verse)",
        r"^(a|an)\s+([\w\s]+)?\b(story|poem|tale|fable)\s+(about|on|regarding)",
    ]
    
    for pattern in direct_patterns:
        if _has_re(t, pattern):
            return True
    
    return False


def _is_technical_explanation(text: str) -> bool:
    if _is_current_conflict_news(text):
        return False
    technical_prompt = _has_re(
        text,
        r"\b(explain|what is|what's|whats|how does|how do|describe|tell me about|law|summarize|difference between|compare|comparison|recommend|recommended|consider|best|optimum|optimal)\b",
    )
    parameter_prompt = _has_re(
        text,
        r"\b(what|which|how|reasonable|choose|use|set)\b",
    ) and _has_re(
        text,
        r"\b(plate voltage|screen voltage|grid bias|bias|load impedance|operating point|plate dissipation|quiescent current|screen current|anode current|feedback|compensation|stability|phase margin)\b",
    )
    if not (technical_prompt or parameter_prompt):
        return False
    if _has_re(
        text,
        r"\b(ohm|voltage|current|resistor|circuit|transistor|diode|op-amp|op amp|lm317|electronics|algorithm|recursion|transformer|tube|valve|amplifier|output stage|operating point|plate|screen|anode|cathode|grid|bias|feedback|compensation|stability|phase margin|gain stage|class a|class ab1|load line|impedance)\b",
    ):
        return True
    if _has_re(text, r"\b[a-z]{1,4}\d{2,6}[a-z0-9-]*\b"):
        return True
    return False


def _has_temporal_freshness_term(text: str) -> bool:
    return has_temporal_signal(text)


def _is_primary_doc_request(text: str) -> bool:
    if _has_re(
        text,
        r"\b(datasheet|data sheet|manual|application note|app note|reference manual|pdf|tube manual|vacuum tube|valve)\b",
    ):
        return True
    if _has_re(text, r"\b[a-z]{1,4}\d{2,6}[a-z0-9-]*\b") and _has_re(text, r"\b(source|link|pdf|manual|datasheet)\b"):
        return True
    return False


def _is_travel_advisory(text: str) -> bool:
    return _has_re(
        text,
        r"\b(travel|travelling|traveling|visit|trip|tourism|tourist|safe|safety|advisory|warning|dangerous|risk|safe to travel|is it safe)\b",
    ) and _contains_any(text, list(TRAVEL_DESTINATIONS))


def _is_current_fact(text: str) -> bool:
    if _is_current_conflict_news(text):
        return True
    if _has_re(
        text,
        r"\b(in current production|current production|still in production|still made|still manufactured|currently manufactured|in production|production status|discontinued|obsolete|end of life|eol)\b",
    ) and _has_re(
        text,
        r"\b(transistor|transistors|mosfet|mosfets|igbt|igbts|diode|diodes|tube|tubes|valve|valves|bearing|bearings|relay|relays|fuse|fuses|connector|connectors|ic|ics|chip|chips|amplifier|amplifiers|op-amp|op amp)\b",
    ):
        return True
    if _has_re(text, r"\b(news|headline|headlines|breaking)\b"):
        return True
    if _has_re(
        text,
        r"\b("
        r"exchange rate|fx rate|forex|currency pair|currency conversion|"
        r"usd\s*(to|\/)\s*ils|ils\s*(to|\/)\s*usd|"
        r"convert\s+(usd|ils|eur|gbp|jpy)|"
        r"(usd|ils|eur|gbp|jpy)\s+exchange"
        r")\b",
    ):
        return True
    if _has_temporal_freshness_term(text):
        return True
    if _has_re(text, r"\b(price|stock price|weather|temperature|schedule|availability|in stock|delivery)\b"):
        return True
    if _has_re(text, r"\b(inflation rate|cpi|consumer price index)\b"):
        return True
    return False


def _is_current_conflict_news(text: str) -> bool:
    if not _has_re(
        text,
        r"\b(war|conflict|military action|ceasefire|talks?|hostilities|fighting|strikes?|offensive|tensions?|standoff)\b",
    ):
        return False
    return _has_temporal_freshness_term(text) or _has_re(text, r"\b(predict|prediction|outcome|forecast)\b")


def _is_news_query(text: str) -> bool:
    if (
        _has_re(text, r"\b(ai|artificial intelligence|genai|llm|foundation models?)\b")
        and _has_re(text, r"\b(policy|governance|regulation|safety)\b")
        and _has_re(text, r"\b(latest|current|recent|update|updates|developments?)\b")
        and not _has_re(text, r"\b(news|headline|headlines|breaking)\b")
    ):
        return False
    if has_news_term(text):
        return True
    if _is_current_conflict_news(text):
        return True
    if _has_re(
        text,
        r"\b(latest on|latest developments?|what happened|what(?:'s|s)? happening|what happening|main headlines|ceasefire|war|conflict|talks?|tensions?|standoff)\b",
    ) and _is_current_fact(text):
        return True
    if _has_re(text, r"\b(stock market|market)\b") and _has_re(text, r"\b(today|latest|recent|now)\b"):
        return True
    return False


def _is_evidence_check(text: str) -> bool:
    if _has_re(text, r"\b(verify|evidence|source|sources|citation|citations|cite|url|link)\b") and not is_probable_culinary_source_misrecognition(text):
        return True
    if _has_re(text, r"\b(wikipedia|wiki)\b"):
        return True
    if _has_re(text, r"\b(fetch|browse|search the web|search web|look up)\b"):
        return True
    if _is_primary_doc_request(text):
        return True
    if _is_travel_advisory(text):
        return True
    if _is_medical_query(text):
        return True
    return False


def _is_medical_query(text: str) -> bool:
    return has_human_medication_topic_query(text)


def _is_mixed_ambiguous(text: str) -> bool:
    if _has_re(text, r"\btravel\s+(information|info|advice)\b") and not _contains_any(text, list(TRAVEL_DESTINATIONS)):
        return True
    if _has_re(text, r"\btell me about\b") and _contains_any(text, list(TRAVEL_DESTINATIONS)):
        return True
    if _has_re(text, r"\bwhat about\b") and _contains_any(text, list(TRAVEL_DESTINATIONS)):
        return True
    return False


def _is_conceptual_inflation_query(text: str) -> bool:
    return (
        _has_re(text, r"\b(explain|what is|what's|whats|define|meaning of|tell me about)\b")
        and _has_re(text, r"\binflation\b")
        and not _has_temporal_freshness_term(text)
        and not _has_re(text, r"\b(rate|cpi|consumer price index)\b")
    )


def _is_current_product_recommendation(text: str) -> bool:
    if not _has_re(text, r"\b(recommend|recommendation|best|suggest|buy)\b"):
        return False
    if not _has_re(text, r"\b(laptop|notebook|phone|smartphone|tablet|camera|tv|monitor|headphones?|earbuds?|pc|computer)\b"):
        return False
    return _has_temporal_freshness_term(text) or _has_re(text, r"\b(current|latest|new|today|right now)\b")


def _is_unanchored_ambiguous_followup(text: str) -> bool:
    qn = re.sub(r"\s+", " ", (text or "").strip().lower())
    if len(qn.split()) > 6:
        return False
    return _has_re(
        qn,
        r"^("
        r"what about (that|this|it)( one)?|"
        r"can you check (that|this|it)|"
        r"tell me more(?: about (that|this|it))?|"
        r"more about (that|this|it)|"
        r"is it safe|"
        r"what do you mean|"
        r"can you continue|"
        r"and the other one|"
        r"which one is better|"
        r"how about now|"
        r"explain (that|this|it) again|"
        r"what should i do then|"
        r"is (that|this|it) still true"
        r")[\s.!?]*$",
    )


def _shopping_clarification(text: str) -> Optional[str]:
    if _has_re(text, r"\b(in stock|price|buy|delivery|availability|where can i get)\b") and not _has_re(
        text, r"\b(israel|israeli|tel aviv|jerusalem|haifa|nis|₪)\b"
    ):
        return "Do you want Israel local delivery?"
    return None


def _confidence(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 2)


def _legacy_plan_from_classification(result: Dict[str, object], normalized: Dict[str, object]) -> Dict[str, object]:
    intent_class = str(result["intent_class"])
    subcategory = str(result.get("subcategory") or "general")
    clarification_question = result.get("clarification_question")
    legacy: Dict[str, object] = {
        "intent": "LOCAL_KNOWLEDGE",
        "category": subcategory,
        "needs_web": False,
        "needs_citations": False,
        "min_sources": 1,
        "prefer_domains": [],
        "allow_domains_file": None,
        "region_filter": None,
        "one_clarifying_question": clarification_question,
        "confidence_policy": "normal",
        "output_mode": "CHAT",
    }

    if intent_class == "identity_personal":
        variant = str(result.get("identity_variant") or "relationship")
        legacy["intent"] = {
            "self": "IDENTITY_SELF",
            "user": "IDENTITY_USER",
        }.get(variant, "IDENTITY_RELATIONSHIP")
        legacy["category"] = "identity"
        legacy["min_sources"] = 0
    elif intent_class == "command_control":
        legacy["intent"] = "LOCAL_KNOWLEDGE"
        legacy["category"] = "command_control"
    elif intent_class == "conversational":
        legacy["intent"] = "LOCAL_CHAT"
        legacy["category"] = "conversation"
        legacy["min_sources"] = 0
        legacy["output_mode"] = "CONVERSATION"
    elif intent_class == "technical_explanation":
        legacy["intent"] = "LOCAL_KNOWLEDGE"
        legacy["category"] = subcategory
    elif intent_class == "local_knowledge":
        legacy["intent"] = "PET_FOOD" if subcategory == "pet_food" else "LOCAL_KNOWLEDGE"
        legacy["category"] = subcategory
        legacy["min_sources"] = 0 if subcategory == "pet_food" else 1
    elif intent_class == "current_fact":
        legacy["needs_web"] = True
        legacy["needs_citations"] = True
        legacy["min_sources"] = 2
        legacy["output_mode"] = "LIGHT_EVIDENCE"
        policy_global_query = _is_global_policy_query(normalized["question_text_lower"])
        if subcategory.startswith("news"):
            legacy["intent"] = "WEB_NEWS"
            if policy_global_query:
                legacy["allow_domains_file"] = "config/trust/generated/policy_global_runtime.txt"
                legacy["region_filter"] = None
            elif subcategory == "news_israel":
                legacy["allow_domains_file"] = "config/trust/generated/news_israel_runtime.txt"
                legacy["region_filter"] = "IL"
            elif subcategory == "news_israel_sources_only":
                legacy["allow_domains_file"] = "config/trust/generated/news_israel_only_runtime.txt"
                legacy["region_filter"] = "IL"
            else:
                legacy["allow_domains_file"] = "config/trust/generated/news_world_runtime.txt"
                legacy["region_filter"] = result.get("region_filter")
        elif subcategory == "shopping_local":
            legacy["intent"] = "SHOPPING_LOCAL"
        else:
            legacy["intent"] = "WEB_FACT"
            if policy_global_query:
                legacy["allow_domains_file"] = "config/trust/generated/policy_global_runtime.txt"
    elif intent_class == "evidence_check":
        legacy["needs_web"] = True
        legacy["needs_citations"] = True
        legacy["min_sources"] = 2
        legacy["output_mode"] = "LIGHT_EVIDENCE"
        policy_global_query = _is_global_policy_query(normalized["question_text_lower"])
        if subcategory == "medical":
            legacy["intent"] = "MEDICAL_INFO"
            legacy["category"] = "medical"
            legacy["output_mode"] = "VALIDATED"
            legacy["allow_domains_file"] = "config/trust/generated/medical_runtime.txt"
            if _has_re(normalized["question_text_lower"], r"\b(dog|dogs|cat|cats|pet|pets)\b"):
                legacy["allow_domains_file"] = "config/trust/generated/vet_runtime.txt"
            legacy["confidence_policy"] = "high_stakes"
        elif subcategory == "travel_advisory":
            legacy["intent"] = "WEB_FACT"
            legacy["category"] = "travel_advisory"
            legacy["allow_domains_file"] = "config/trust/generated/news_world_runtime.txt"
        elif subcategory == "primary_doc":
            legacy["intent"] = "PRIMARY_DOC"
            legacy["category"] = "electronics"
            legacy["min_sources"] = 1
            legacy["allow_domains_file"] = "config/trust/generated/engineering_runtime.txt"
            legacy["prefer_domains"] = _prefer_domains_for_primary_doc(normalized["question_text_lower"])
        elif subcategory == "reference":
            legacy["intent"] = "WEB_DOC"
            legacy["category"] = "reference"
            legacy["min_sources"] = 1
            legacy["prefer_domains"] = ["wikipedia.org"]
        elif subcategory == "url_reference":
            legacy["intent"] = "WEB_DOC"
            legacy["category"] = "reference"
            legacy["min_sources"] = 1
        else:
            legacy["intent"] = "WEB_FACT"
            if policy_global_query:
                legacy["allow_domains_file"] = "config/trust/generated/policy_global_runtime.txt"
    elif intent_class == "mixed":
        legacy["intent"] = "WEB_FACT"
        legacy["category"] = "ambiguous"
        legacy["needs_web"] = True
        legacy["needs_citations"] = True
        legacy["min_sources"] = 2
        legacy["output_mode"] = "LIGHT_EVIDENCE"
        legacy["confidence_policy"] = "uncertain"

    return legacy


def classify_question(question: str, surface: str = "cli") -> Dict[str, object]:
    normalized = normalize_input(question, surface=surface)
    q = normalized["question_text_lower"]
    medical_detector = detect_human_medication_query(q)
    medical_query = _is_medical_query(q)
    clarification_question = None
    routing_signals = build_common_signal_flags(q)
    routing_signals["medical_context"] = medical_query
    routing_signals["ambiguity_followup"] = _is_unanchored_ambiguous_followup(q)
    routing_signals["current_product_recommendation"] = _is_current_product_recommendation(q)
    routing_signals["conceptual_inflation"] = _is_conceptual_inflation_query(q)

    # Check for creative writing requests - these should ALWAYS use local model
    # to avoid identity preamble issues and unnecessary augmentation
    is_creative = _is_creative_writing(q)
    
    result: Dict[str, object] = {
        "schema_version": "phase1",
        "intent_class": "local_knowledge",
        "confidence": 0.62,
        "needs_current_info": False,
        "needs_personal_context": False,
        "style_mode": "informational",
        "mixed_intent": False,
        "candidate_routes": ["LOCAL"],
        "needs_clarification": False,
        "clarification_question": None,
        "subcategory": "general",
        "identity_variant": "",
        "medical_detector": medical_detector,
        "routing_signals": routing_signals,
        "force_local": is_creative,  # Creative writing forces local mode
    }

    if normalized["is_command_control"]:
        result.update(
            {
                "intent_class": "command_control",
                "confidence": _confidence(0.99),
                "style_mode": "directive",
                "candidate_routes": ["LOCAL"],
                "subcategory": "command_control",
            }
        )
    else:
        identity_variant = _identity_variant(q)
        if identity_variant:
            result.update(
                {
                    "intent_class": "identity_personal",
                    "confidence": _confidence(0.96),
                    "needs_personal_context": True,
                    "style_mode": "conversational",
                    "candidate_routes": ["LOCAL"],
                    "subcategory": "identity",
                    "identity_variant": identity_variant,
                }
            )
        elif _has_re(q, r"\b(dog|dogs|cat|cats|pet|pets)\b") and _has_re(
            q,
            r"\b(toxic|poison|poisonous|symptom|symptoms|vomit|vomiting|diarrhea|diarrhoea|stool|poo|poop|runny stool|runny poo|loose stool|soft stool|dose|dosage|medication|medicine|vet|veterinarian|seizure|seizures|lethargy|trouble breathing|xylitol|ibuprofen|acetaminophen|paracetamol)\b",
        ):
            result.update(
                {
                    "intent_class": "evidence_check",
                    "confidence": _confidence(0.95),
                    "needs_current_info": False,
                    "style_mode": "informational",
                    "candidate_routes": ["EVIDENCE"],
                    "subcategory": "medical",
                }
            )
        elif _is_unanchored_ambiguous_followup(q):
            result.update(
                {
                    "intent_class": "mixed",
                    "confidence": _confidence(0.38),
                    "style_mode": "informational",
                    "mixed_intent": True,
                    "candidate_routes": ["CLARIFY"],
                    "needs_current_info": False,
                    "needs_clarification": True,
                    "clarification_question": "What specific topic do you want me to continue with?",
                    "subcategory": "ambiguous_followup",
                }
            )
        elif _is_current_product_recommendation(q):
            result.update(
                {
                    "intent_class": "mixed",
                    "confidence": _confidence(0.88),
                    "needs_current_info": True,
                    "style_mode": "informational",
                    "mixed_intent": True,
                    "candidate_routes": ["EVIDENCE", "NEWS"],
                    "subcategory": "current_product_recommendation",
                }
            )
        elif _is_conceptual_inflation_query(q):
            result.update(
                {
                    "intent_class": "local_knowledge",
                    "confidence": _confidence(0.88),
                    "style_mode": "informational",
                    "candidate_routes": ["LOCAL"],
                    "subcategory": "economics_concept",
                }
            )
        elif normalized["has_url"]:
            result.update(
                {
                    "intent_class": "evidence_check",
                    "confidence": _confidence(0.95),
                    "style_mode": "informational",
                    "candidate_routes": ["EVIDENCE"],
                    "subcategory": "url_reference",
                }
            )
        elif is_time_query(q):
            # Time-of-day queries need real-time data
            result.update(
                {
                    "intent_class": "current_fact",
                    "confidence": _confidence(0.95),
                    "needs_current_info": True,
                    "style_mode": "brief",
                    "candidate_routes": ["EVIDENCE"],
                    "subcategory": "time_query",
                }
            )
        elif _is_current_fact(q) and _is_news_query(q):
            region_filter = _news_region_filter(q)
            strict_israeli_sources = _strict_israeli_sources(q)
            result.update(
                {
                    "intent_class": "current_fact",
                    "confidence": _confidence(0.95),
                    "needs_current_info": True,
                    "style_mode": "brief",
                    "candidate_routes": ["NEWS", "EVIDENCE"],
                    "subcategory": (
                        "news_israel_sources_only"
                        if strict_israeli_sources
                        else ("news_israel" if region_filter == "IL" else "news_world")
                    ),
                    "region_filter": region_filter,
                }
            )
        elif medical_query:
            result.update(
                {
                    "intent_class": "evidence_check",
                    "confidence": _confidence(max(0.97, float(medical_detector.get("confidence_score") or 0.0))),
                    "style_mode": "informational",
                    "candidate_routes": ["EVIDENCE"],
                    "subcategory": "medical",
                }
            )
        elif _is_travel_advisory(q):
            result.update(
                {
                    "intent_class": "evidence_check",
                    "confidence": _confidence(0.92),
                    "needs_current_info": True,
                    "style_mode": "informational",
                    "candidate_routes": ["EVIDENCE"],
                    "subcategory": "travel_advisory",
                }
            )
        elif _is_primary_doc_request(q):
            result.update(
                {
                    "intent_class": "evidence_check",
                    "confidence": _confidence(0.93),
                    "style_mode": "technical",
                    "candidate_routes": ["EVIDENCE"],
                    "subcategory": "primary_doc",
                }
            )
        elif _has_re(q, r"\b(wikipedia|wiki)\b"):
            result.update(
                {
                    "intent_class": "evidence_check",
                    "confidence": _confidence(0.92),
                    "style_mode": "informational",
                    "candidate_routes": ["EVIDENCE"],
                    "subcategory": "reference",
                }
            )
        elif _has_re(q, r"\b(verify|evidence|source|sources|citation|citations|cite|url|link|fetch|browse|search web|search the web|look up)\b") and not is_probable_culinary_source_misrecognition(q):
            result.update(
                {
                    "intent_class": "evidence_check",
                    "confidence": _confidence(0.87),
                    "style_mode": "informational",
                    "candidate_routes": ["EVIDENCE"],
                    "subcategory": "web_lookup",
                }
            )
        elif _has_re(q, r"\b(dog|dogs|cat|cats|pet|pets)\b") and _has_re(
            q,
            r"\b(eat|feed|give|food|treat|snack|meal|diet|tuna|fish|chicken|beef|rice|egg|eggs|bread|cheese|milk|yogurt|banana|apple)\b",
        ):
            result.update(
                {
                    "intent_class": "local_knowledge",
                    "confidence": _confidence(0.83),
                    "style_mode": "conversational",
                    "candidate_routes": ["LOCAL"],
                    "subcategory": "pet_food",
                }
            )
        elif _is_current_fact(q) and _has_re(q, r"\b(in stock|buy|delivery|availability|where can i get|local delivery)\b"):
            clarification_question = _shopping_clarification(q)
            result.update(
                {
                    "intent_class": "current_fact",
                    "confidence": _confidence(0.82 if not clarification_question else 0.58),
                    "needs_current_info": True,
                    "style_mode": "informational",
                    "candidate_routes": ["EVIDENCE"],
                    "subcategory": "shopping_local",
                    "needs_clarification": bool(clarification_question),
                    "clarification_question": clarification_question,
                }
            )
        elif _is_current_fact(q):
            result.update(
                {
                    "intent_class": "current_fact",
                    "confidence": _confidence(0.84),
                    "needs_current_info": True,
                    "style_mode": "informational",
                    "candidate_routes": ["EVIDENCE", "NEWS"],
                    "subcategory": "current_fact",
                }
            )
        elif _is_technical_explanation(q):
            result.update(
                {
                    "intent_class": "technical_explanation",
                    "confidence": _confidence(0.9),
                    "style_mode": "technical",
                    "candidate_routes": ["LOCAL"],
                    "subcategory": "technical_explanation",
                }
            )
        elif _is_conversational(q):
            result.update(
                {
                    "intent_class": "conversational",
                    "confidence": _confidence(0.86),
                    "style_mode": "conversational",
                    "candidate_routes": ["LOCAL"],
                    "subcategory": "conversation",
                }
            )
        elif _is_mixed_ambiguous(q):
            result.update(
                {
                    "intent_class": "mixed",
                    "confidence": _confidence(0.46),
                    "style_mode": "informational",
                    "mixed_intent": True,
                    "candidate_routes": ["CLARIFY", "EVIDENCE", "LOCAL"],
                    "needs_current_info": False,
                    "needs_clarification": True,
                    "clarification_question": "Do you want general information, current news, or travel safety information?",
                    "subcategory": "ambiguous_destination",
                }
            )
        else:
            result.update(
                {
                    "intent_class": "local_knowledge",
                    "confidence": _confidence(0.71),
                    "style_mode": "informational",
                    "candidate_routes": ["LOCAL"],
                    "subcategory": "general",
                }
            )

    legacy_plan = _legacy_plan_from_classification(result, normalized)
    classifier_output: Dict[str, object] = dict(result)
    classifier_output.update(normalized)
    classifier_output["legacy_plan"] = legacy_plan
    classifier_output.update(legacy_plan)
    classifier_output["clarification_question"] = result.get("clarification_question")
    return classifier_output
