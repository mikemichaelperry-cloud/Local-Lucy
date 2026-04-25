#!/usr/bin/env python3
import argparse
import json
import re


def norm(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("\u2019", "'").replace("\u2018", "'")
    t = re.sub(r"[^a-z0-9\s'-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def has_re(text: str, pat: str) -> bool:
    return re.search(pat, text, flags=re.IGNORECASE) is not None


def detect_pet(text: str) -> str:
    if has_re(text, r"\b(cat|cats|kitten|kittens)\b"):
        return "cat"
    if has_re(text, r"\b(dog|dogs|puppy|puppies)\b"):
        return "dog"
    if has_re(text, r"\b(pet|pets)\b"):
        return "pet"
    return ""


def detect_food_category(text: str) -> str:
    if has_re(text, r"\b(best food|best diet|main diet|regular diet|regular food|what food)\b"):
        return "diet_advice"
    if has_re(text, r"\b(tuna|tinned tuna|canned tuna)\b"):
        return "tuna"
    if has_re(text, r"\b(cheeseburger|double cheeseburger|burger|hamburger)\b"):
        return "burger"
    if has_re(text, r"\b(pizza|fries|french fries|hot dog|sausage|bacon)\b"):
        return "processed_human_food"
    if has_re(text, r"\b(cheese|milk|ice cream|yogurt)\b"):
        return "dairy"
    if has_re(text, r"\b(chicken|beef|turkey|rice|egg|eggs|apple|banana|carrot)\b"):
        return "plain_food"
    return "unknown_food"


def detect_tuna_packing(text: str) -> str:
    if has_re(text, r"\b(brine|salt|salty|sodium)\b"):
        return "brine"
    if has_re(text, r"\b(olive oil|in oil|oily|oil-packed|oil packed)\b"):
        return "oil"
    if has_re(text, r"\b(in water|water-packed|water packed|plain water)\b"):
        return "water"
    return "unspecified"


def is_high_risk_medical(text: str) -> bool:
    return has_re(
        text,
        r"\b(vomit|vomiting|diarrhea|diarrhoea|lethargy|seizure|seizures|trouble breathing|"
        r"breathing|collapse|collapsed|emergency|urgent|poison|poisoning|xylitol|"
        r"chocolate|grapes|raisins|onion|garlic|ibuprofen|acetaminophen|paracetamol)\b",
    )


def has_pet_food_intent(text: str) -> bool:
    if not has_re(text, r"\b(can|could|should|safe|unsafe|healthy|good|bad|okay|ok|eat|feed|give|best|main|regular)\b"):
        return False
    if has_re(text, r"\b(eat|feed|give|food|treat|snack|meal|diet)\b"):
        return True
    # Cover common short safety phrasing such as:
    # "Is tuna in olive oil okay for my dog?"
    if has_re(text, r"\b(okay|ok|safe|healthy|good|bad)\s+for\b"):
        return True
    if has_re(text, r"\bis\s+.+\s+(okay|ok|safe|healthy|good|bad)\b"):
        return True
    if has_re(text, r"\b(best food|best diet|main diet|regular diet|regular food|what food)\b"):
        return True
    return False


def build_answer(qn: str, pet: str, category: str, tuna_pack: str) -> str:
    subject = pet if pet else "pet"
    lines = []
    if category == "tuna":
        lines.append(f"Tinned/canned tuna is not a healthy regular food for your {subject}.")
        if tuna_pack == "brine":
            lines.append("Avoid tuna in brine because high sodium can be harmful.")
        elif tuna_pack == "oil":
            lines.append("Avoid tuna packed in oil (including olive oil) because extra fat can trigger stomach upset or pancreatitis risk.")
        elif tuna_pack == "water":
            lines.append("If given at all, use only plain tuna in water without added salt and keep it as a tiny occasional treat.")
        else:
            lines.append("If offered at all, keep portions tiny and occasional, and avoid salted or oily variants.")
        lines.append("Use complete dog/cat-formulated food for regular meals.")
        lines.append("Conservative sources: vcahospitals.com, akc.org, petmd.com.")
        return "\n".join(lines)

    if category == "diet_advice":
        lines.append(f"The best regular food for your {subject} is a complete and balanced pet food made for their species and life stage.")
        lines.append("Choose food labeled for growth, adult maintenance, or senior needs as appropriate, and use your vet's advice if your pet has allergies or medical conditions.")
        lines.append("Avoid making fatty, salty, or heavily seasoned human food the main diet.")
        lines.append("Conservative sources: vcahospitals.com, akc.org, petmd.com.")
        return "\n".join(lines)

    if category == "burger":
        lines.append(f"A double cheeseburger is not a good meal choice for your {subject}.")
        lines.append("It is typically too high in fat and salt, and common toppings/seasonings (like onion or garlic) can be unsafe.")
        lines.append("If a bite was already eaten, monitor for vomiting, diarrhea, or lethargy and call your vet if symptoms appear.")
        lines.append("Use plain, unseasoned pet-safe food instead.")
        lines.append("Conservative sources: vcahospitals.com, akc.org, petmd.com.")
        return "\n".join(lines)

    if category == "processed_human_food":
        lines.append(f"Processed human food is generally a poor choice for your {subject}.")
        lines.append("These foods are often high in fat, salt, and seasoning that can upset digestion.")
        lines.append("Prefer plain pet-formulated food and reserve human food for rare tiny treats.")
        lines.append("Conservative sources: vcahospitals.com, akc.org, petmd.com.")
        return "\n".join(lines)

    if category == "dairy":
        lines.append(f"Most {subject}s can have trouble with dairy.")
        lines.append("Small amounts may be tolerated by some pets, but dairy can cause stomach upset.")
        lines.append("If you try any dairy, keep it tiny and stop if GI symptoms appear.")
        lines.append("Conservative sources: vcahospitals.com, petmd.com.")
        return "\n".join(lines)

    if category == "plain_food":
        lines.append(f"Some plain foods can be okay for your {subject} in small amounts.")
        lines.append("Keep food plain, unseasoned, and treat-sized; avoid salt, oils, sauces, onion, and garlic.")
        lines.append("Pet-formulated complete food should remain the main diet.")
        lines.append("Conservative sources: vcahospitals.com, petmd.com.")
        return "\n".join(lines)

    lines.append(f"I cannot verify that food as safe for your {subject} from this quick classifier.")
    lines.append("Use plain pet-formulated food by default and avoid seasoned/fatty/salty human foods.")
    lines.append("If any unusual symptoms appear, contact your veterinarian.")
    lines.append("Conservative sources: vcahospitals.com, akc.org, petmd.com.")
    return "\n".join(lines)


def classify(question: str) -> dict:
    qn = norm(question)
    pet = detect_pet(qn)
    if not pet:
        return {"matched": False, "reason": "no_pet_signal", "answer": ""}
    if not has_pet_food_intent(qn):
        return {"matched": False, "reason": "no_food_intent_signal", "answer": ""}
    if is_high_risk_medical(qn):
        return {"matched": False, "reason": "high_risk_medical_signal", "answer": ""}

    category = detect_food_category(qn)
    tuna_pack = detect_tuna_packing(qn) if category == "tuna" else ""
    answer = build_answer(qn, pet, category, tuna_pack)
    return {
        "matched": True,
        "reason": "knowledge_pet_food",
        "food_category": category,
        "tuna_packing": tuna_pack,
        "answer": answer,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default="")
    args = ap.parse_args()
    print(json.dumps(classify(args.question), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
