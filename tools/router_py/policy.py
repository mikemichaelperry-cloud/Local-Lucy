#!/usr/bin/env python3
"""
Router policy functions - Python port of shell implementations.
Deterministic policy decisions with no side effects.
"""

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
    
    # Medical/health keywords
    medical_keywords = [
        "symptom", "symptoms", "diagnosis", "treatment", "treat", "medication",
        "disease", "condition", "prescription", "drug", "vaccine",
        "vaccination", "pregnancy", "pregnant", "cancer", "diabetes",
        "heart attack", "stroke", "infection", "virus", "bacteria",
        "pain", "headache", "injury", "emergency", "hospital", "doctor", "medicine",
        # Medications and interactions
        "tadalafil", "cialis", "viagra", "sildenafil", "interaction", "interact",
        "grapefruit", "side effect", "contraindication", "dosage", "dose",
        "amoxicillin", "aspirin", "metformin", "insulin", "ibuprofen", "warfarin",
        "atorvastatin", "lipitor", "omeprazole", "pharmacy", "pharmacist"
    ]
    
    for keyword in medical_keywords:
        if keyword in normalized:
            return True, "medical_context"
    
    # Live conflict/geopolitics keywords
    conflict_keywords = [
        "breaking news", "latest news", "latest updates", "current conflict", "war in",
        "ongoing war", "live updates", "just happened", "today in",
        "current situation", "latest development"
    ]
    
    for keyword in conflict_keywords:
        if keyword in normalized:
            return True, "conflict_live"
    
    # Source verification requests
    source_keywords = [
        "source", "cite", "citation", "reference", "evidence",
        "where did you get", "how do you know", "prove that",
        "verify", "fact check"
    ]
    
    for keyword in source_keywords:
        if keyword in normalized:
            return True, "source_request"
    
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
