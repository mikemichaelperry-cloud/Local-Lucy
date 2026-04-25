#!/usr/bin/env python3
"""
Extended Shadow Testing Corpus

A comprehensive set of test queries covering all routing scenarios.
Designed for 1000+ query validation runs.
"""

# Categorized test queries for systematic validation
SHADOW_CORPUS = {
    "local_math": [
        "What is 2+2?",
        "What is 15 times 7?",
        "Calculate the square root of 144",
        "What is 10% of 500?",
        "Solve for x: 2x + 5 = 13",
    ],
    "local_facts": [
        "What is the capital of France?",
        "How many days in a year?",
        "What is the tallest mountain?",
        "Who wrote Romeo and Juliet?",
        "What is the speed of light?",
    ],
    "local_procedural": [
        "How do I boil an egg?",
        "Steps to bake bread",
        "How to change a tire",
        "Recipe for pancakes",
        "How to meditate",
    ],
    "background_biography": [
        "Who was Ada Lovelace?",
        "Who was Marie Curie?",
        "Tell me about Winston Churchill",
        "Who was Isaac Newton?",
        "Who was Cleopatra?",
    ],
    "background_history": [
        "Tell me about the Roman Empire",
        "What was World War II?",
        "Explain the French Revolution",
        "What is the history of the Internet?",
        "Tell me about Ancient Egypt",
    ],
    "background_science": [
        "What is photosynthesis?",
        "Explain the theory of relativity",
        "What is quantum mechanics?",
        "How does DNA work?",
        "What is evolution?",
    ],
    "background_technology": [
        "What is machine learning?",
        "Explain blockchain",
        "What is artificial intelligence?",
        "How do computers work?",
        "What is the cloud?",
    ],
    "synthesis_explain": [
        "Explain quantum mechanics simply",
        "What is socialism in simple terms?",
        "Explain like I'm five: how does the internet work?",
        "What is capitalism explained simply?",
        "Explain general relativity simply",
    ],
    "synthesis_compare": [
        "Compare capitalism and socialism",
        "What is the difference between DNA and RNA?",
        "Compare Python and JavaScript",
        "HTTP vs HTTPS: what's the difference?",
        "Compare renewable and non-renewable energy",
    ],
    "current_news": [
        "What is the latest news about Ukraine?",
        "Breaking news today",
        "What happened today in the world?",
        "Latest updates on climate change",
        "Current events this week",
    ],
    "current_conflict": [
        "What is happening in Gaza?",
        "Current situation in Ukraine",
        "War updates today",
        "Latest conflict news",
        "What wars are happening now?",
    ],
    "medical_symptoms": [
        "What are the symptoms of flu?",
        "Signs of a heart attack",
        "Diabetes symptoms",
        "What are COVID symptoms?",
        "Signs of dehydration",
    ],
    "medical_treatment": [
        "How to treat a headache?",
        "Best way to treat a cold",
        "How to lower blood pressure naturally",
        "Treatment for anxiety",
        "How to treat a burn",
    ],
    "medical_general": [
        "What causes high blood pressure?",
        "How does the immune system work?",
        "What is cancer?",
        "How do vaccines work?",
        "What is mental health?",
    ],
    "evidence_request": [
        "What is your source for that?",
        "Where did you get this information?",
        "Cite your sources",
        "What evidence supports this?",
        "Can you verify this claim?",
    ],
    "clarify_vague": [
        "Tell me about it",
        "Explain this",
        "What about that?",
        "Tell me more",
        "What do you mean?",
    ],
    "clarify_subjective": [
        "What do you think?",
        "What is your opinion?",
        "Do you believe in God?",
        "What is the meaning of life?",
        "Is there alien life?",
    ],
    "edge_empty": [
        "",
        " ",
        "   ",
    ],
    "edge_short": [
        "Hi",
        "Hello",
        "Hey",
        "Yo",
        "OK",
    ],
    "edge_punctuation": [
        "?!",
        "...",
        "???",
        "!",
        "????????",
    ],
    "edge_long": [
        "Explain " * 50,
        "What is " * 100,
        "Tell me about " * 75,
    ],
    "edge_special_chars": [
        "What is 2+2? <script>alert('test')</script>",
        "Query with 'quotes' and \"double quotes\"",
        "Test with \n newlines \t tabs",
        "Unicode: 你好世界 🌍 émojis",
        "Math symbols: ∑ ∏ ∫ ∂ √",
    ],
    "context_referring": [
        "What about that?",
        "Tell me more about it",
        "Explain that further",
        "What else?",
        "And then what happened?",
    ],
    "multi_part": [
        "What is 2+2 and who invented math?",
        "Tell me about Paris and London",
        "Compare apples and oranges and bananas",
        "What is the weather and what time is it?",
        "Who was Einstein and what did he discover?",
    ],
}


def get_all_queries() -> list[tuple[str, str]]:
    """Get all queries as (query, category) tuples."""
    queries = []
    for category, query_list in SHADOW_CORPUS.items():
        for query in query_list:
            queries.append((query, category))
    return queries


def get_corpus_stats() -> dict:
    """Get statistics about the corpus."""
    stats = {
        "total_categories": len(SHADOW_CORPUS),
        "total_queries": sum(len(q) for q in SHADOW_CORPUS.values()),
        "categories": {cat: len(q) for cat, q in SHADOW_CORPUS.items()},
    }
    return stats


if __name__ == "__main__":
    import json
    
    stats = get_corpus_stats()
    print(json.dumps(stats, indent=2))
    
    print(f"\nTotal queries: {stats['total_queries']}")
    print(f"Categories: {stats['total_categories']}")
