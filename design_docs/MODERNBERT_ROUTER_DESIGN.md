# ModernBERT Router Design — Local Lucy V8

**Status:** Design Complete — Ready for Implementation  
**Model:** ModernBERT-base (110M params, CPU-friendly)  
**Task:** Sequence Classification (multi-label intent + route + policy)  
**Objective:** Replace fragile keyword/heuristic routing with a single forward-pass neural classifier that is inspectable, calibrated, and manifest-authorized.

---

## 1. Why ModernBERT

| Property | Value | Relevance |
|----------|-------|-----------|
| Parameters | 110M | Fits in 1GB RAM, ~20-50ms inference on modern CPU |
| Context | 8192 tokens | Handles long queries, multi-sentence prompts |
| Architecture | BERT-style encoder | Deterministic attention, no sampling hallucinations |
| License | Apache 2.0 | Compatible with Local Lucy distribution |
| Pre-training | 2024 modern corpora | Better on contemporary language than original BERT |

**Why not a generative model (LLM) for routing?**
Generative routers are slow, non-deterministic, and can hallucinate intent labels. ModernBERT is a **discriminative classifier** — it assigns probabilities over a fixed label set. No generation, no creativity, no unpredictability.

---

## 2. Label Schema (Multi-Task Classification)

The router must simultaneously predict four orthogonal properties:

### 2.1 Intent Family (8 classes)
```
background_overview     → needs_web=True,  route∈{LOCAL, AUGMENTED}
current_evidence        → needs_web=True,  route∈{LOCAL, NEWS, TIME, AUGMENTED}
clarification           → needs_web=False, route=CLARIFY
technical_explanation   → needs_web=True,  route∈{LOCAL, AUGMENTED}
creative_writing        → needs_web=False, route=LOCAL
medical_inquiry         → needs_web=True,  route=AUGMENTED, evidence=required
news_request            → needs_web=True,  route=NEWS
time_query              → needs_web=True,  route=TIME
```

### 2.2 Evidence Mode (3 classes)
```
not_required  → Default
required      → Triggered by medical, legal, conflict, source_verification keywords
uncertain     → Model confidence < 0.7, defer to heuristic fallback
```

### 2.3 Route Decision (6 classes)
```
LOCAL              → Ollama local model
LOCAL_WITH_FALLBACK→ Local first, augment if insufficient
AUGMENTED          → Direct to paid provider
NEWS               → RSS/news pipeline
TIME               → Time API
CLARIFY            → Ask user for clarification
```

### 2.4 Policy Override (4 classes)
```
none              → No override (respect evidence_mode)
disabled          → Force LOCAL regardless of other signals
fallback_only     → LOCAL first, fallback to AUGMENTED
force_augmented   → Force AUGMENTED (evidence_mode=required trumps this)
```

**Total output heads:** 4 independent classification heads on top of the [CLS] token.

---

## 3. Dataset Design

### 3.1 Training Data Sources

| Source | Quantity | Quality |
|--------|----------|---------|
| Historical `last_route.json` + `last_outcome.json` | ~500-2000 examples | Gold labels (what actually happened) |
| Synthetic expansion via templates | ~5000 examples | Silver labels (controlled diversity) |
| Human-curated edge cases | ~200 examples | Gold labels (boundary conditions) |

### 3.2 Schema for Each Example

```json
{
  "query": "tell me about the conflict in Gaza and what sources confirm each side's claims",
  "labels": {
    "intent_family": "current_evidence",
    "evidence_mode": "required",
    "route": "AUGMENTED",
    "policy_override": "none"
  },
  "metadata": {
    "source": "historical|synthetic|human",
    "confidence": 1.0,
    "language": "en",
    "query_length_chars": 87,
    "has_medical_keywords": false,
    "has_conflict_keywords": true,
    "has_time_keywords": false,
    "user_trust_level": "standard"
  }
}
```

### 3.3 Synthetic Expansion Strategy

To cover "ALL subjects" without manual labeling of every domain:

```python
# Template-based synthesis for intent_family coverage
TEMPLATES = {
    "background_overview": [
        "what is {topic}",
        "explain {topic} to me",
        "how does {topic} work",
        "overview of {topic}",
    ],
    "current_evidence": [
        "what is the latest on {topic}",
        "current status of {topic}",
        "news about {topic}",
        "evidence for {claim}",
    ],
    "medical_inquiry": [
        "is {drug} safe for {condition}",
        "side effects of {drug}",
        "treatment for {condition}",
    ],
    "time_query": [
        "what time is it in {location}",
        "current time {location}",
    ],
    # ... 50+ templates per family
}

# Slot filling with diverse vocabularies
TOPICS = ["Python", "quantum computing", "Palestine", "AI safety", "diabetes", ...]
DRUGS = ["ibuprofen", "tadalafil", "metformin", ...]
LOCATIONS = ["Tokyo", "New York", "London", ...]
```

**Policy-augmented synthesis:** For each base template, generate variants with explicit policy cues:
```
"what is Python"                    → intent=background, policy=none
"what is Python (brief, offline)"   → intent=background, policy=disabled
"what is Python? Provide sources."  → intent=background, evidence=required
```

### 3.4 Class Balance Target

| Intent Family | Target % | Rationale |
|---------------|----------|-----------|
| background_overview | 25% | Most common query type |
| current_evidence | 20% | News, real-time facts |
| clarification | 10% | Ambiguous/short queries |
| technical_explanation | 15% | Code, science, how-to |
| creative_writing | 10% | Stories, poems, scenarios |
| medical_inquiry | 5% | High-stakes, needs evidence |
| news_request | 10% | RSS-specific |
| time_query | 5% | Simple but distinct |

---

## 4. Model Architecture

```
Input: query_text (tokenized by ModernBERT tokenizer)
       ↓
ModernBERT-base encoder
       ↓
[CLS] pooled representation (768-dim)
       ↓
┌─────────────┬─────────────┬─────────────┬─────────────┐
│ Intent Head │ Evidence Head│ Route Head  │ Policy Head │
│  Linear(768,│  Linear(768,│  Linear(768,│  Linear(768,│
│    8)       │    3)       │    6)       │    4)       │
│  + Softmax  │  + Softmax  │  + Softmax  │  + Softmax  │
└─────────────┴─────────────┴─────────────┴─────────────┘
```

**Loss function:** Sum of 4 independent cross-entropy losses, weighted by class frequency (inverse frequency weighting for rare classes like `medical_inquiry`).

```python
def compute_loss(logits, labels):
    total_loss = 0.0
    for head_name, head_logits in logits.items():
        weights = CLASS_WEIGHTS[head_name]  # inverse frequency
        loss = F.cross_entropy(head_logits, labels[head_name], weight=weights)
        total_loss += loss
    return total_loss
```

---

## 5. Training Pipeline

### 5.1 Directory Structure

```
lucy-v8/
├── models/
│   └── router/
│       ├── train.py              # Training script
│       ├── inference.py          # Inference script
│       ├── dataset.py            # Dataset loading & synthesis
│       ├── config.yaml           # Hyperparameters
│       ├── data/
│       │   ├── raw/              # Historical + human labels
│       │   ├── synthetic/        # Generated examples
│       │   └── processed/        # Tokenized train/val/test splits
│       ├── checkpoints/          # Saved model states
│       └── shadow_logs/          # Shadow mode divergence logs
```

### 5.2 Hyperparameters (config.yaml)

```yaml
model:
  base_model: "answerdotai/ModernBERT-base"
  max_length: 256
  dropout: 0.1

training:
  batch_size: 32
  epochs: 10
  learning_rate: 2.0e-5
  weight_decay: 0.01
  warmup_ratio: 0.1
  label_smoothing: 0.05
  gradient_accumulation_steps: 2
  
data:
  train_split: 0.7
  val_split: 0.15
  test_split: 0.15
  synthetic_ratio: 0.6  # 60% synthetic, 40% real/human
  
calibration:
  method: "temperature_scaling"
  val_temperature_search_range: [0.5, 3.0]
```

### 5.3 Training Script (train.py)

```python
#!/usr/bin/env python3
"""Train the ModernBERT router classifier."""

import json
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from transformers import ModernBertTokenizer, ModernBertModel, get_linear_schedule_with_warmup
from sklearn.metrics import classification_report, confusion_matrix

from dataset import RouterDataset, load_and_balance_data
from model import RouterClassifier


def train():
    config = load_config("config.yaml")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # Load tokenizer and model
    tokenizer = ModernBertTokenizer.from_pretrained(config.model.base_model)
    base_model = ModernBertModel.from_pretrained(config.model.base_model)
    model = RouterClassifier(base_model, config.model)
    model.to(device)
    
    # Load data
    train_data, val_data, test_data = load_and_balance_data(config.data)
    train_dataset = RouterDataset(train_data, tokenizer, config.model.max_length)
    val_dataset = RouterDataset(val_data, tokenizer, config.model.max_length)
    
    train_loader = DataLoader(train_dataset, batch_size=config.training.batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=config.training.batch_size)
    
    # Optimizer and scheduler
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.training.learning_rate, weight_decay=config.training.weight_decay)
    total_steps = len(train_loader) * config.training.epochs // config.training.gradient_accumulation_steps
    scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=int(total_steps * config.training.warmup_ratio), num_training_steps=total_steps)
    
    # Training loop
    best_val_loss = float('inf')
    for epoch in range(config.training.epochs):
        model.train()
        total_loss = 0.0
        for step, batch in enumerate(train_loader):
            optimizer.zero_grad()
            outputs = model(**{k: v.to(device) for k, v in batch.items()})
            loss = compute_loss(outputs, batch['labels'])
            loss.backward()
            
            if (step + 1) % config.training.gradient_accumulation_steps == 0:
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
            
            total_loss += loss.item()
        
        # Validation
        val_metrics = evaluate(model, val_loader, device)
        print(f"Epoch {epoch+1}: train_loss={total_loss/len(train_loader):.4f}, val_loss={val_metrics['loss']:.4f}")
        
        if val_metrics['loss'] < best_val_loss:
            best_val_loss = val_metrics['loss']
            torch.save(model.state_dict(), "checkpoints/best.pt")
    
    # Test evaluation
    test_metrics = evaluate(model, test_loader, device)
    print("\nTest Results:")
    print(json.dumps(test_metrics, indent=2))
    
    # Calibration (temperature scaling)
    optimal_temperature = calibrate_temperature(model, val_loader, device, config.calibration)
    print(f"\nOptimal temperature: {optimal_temperature:.3f}")
    save_config({**config, "calibration_temperature": optimal_temperature})


def evaluate(model, dataloader, device):
    model.eval()
    all_preds = {head: [] for head in HEAD_NAMES}
    all_labels = {head: [] for head in HEAD_NAMES}
    total_loss = 0.0
    
    with torch.no_grad():
        for batch in dataloader:
            outputs = model(**{k: v.to(device) for k, v in batch.items()})
            loss = compute_loss(outputs, batch['labels'])
            total_loss += loss.item()
            
            for head in HEAD_NAMES:
                preds = torch.argmax(outputs[head], dim=-1).cpu().numpy()
                all_preds[head].extend(preds)
                all_labels[head].extend(batch['labels'][head].cpu().numpy())
    
    metrics = {"loss": total_loss / len(dataloader)}
    for head in HEAD_NAMES:
        metrics[head] = classification_report(all_labels[head], all_preds[head], output_dict=True)
    return metrics


if __name__ == "__main__":
    train()
```

---

## 6. Inference Pipeline

### 6.1 Fast CPU Inference

```python
class ModernBertRouter:
    """Production router using ModernBERT classifier."""
    
    def __init__(self, model_path: str, temperature: float = 1.0):
        self.device = torch.device("cpu")
        self.tokenizer = ModernBertTokenizer.from_pretrained("answerdotai/ModernBERT-base")
        self.model = RouterClassifier.from_checkpoint(model_path)
        self.model.eval()
        self.model.to(self.device)
        self.temperature = temperature
    
    def predict(self, query: str) -> RoutingDecision:
        inputs = self.tokenizer(query, return_tensors="pt", truncation=True, max_length=256)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            logits = self.model(**inputs)
        
        # Apply temperature scaling for calibrated confidence
        probs = {
            head: torch.softmax(logit / self.temperature, dim=-1)[0]
            for head, logit in logits.items()
        }
        
        intent_idx = torch.argmax(probs["intent"]).item()
        evidence_idx = torch.argmax(probs["evidence"]).item()
        route_idx = torch.argmax(probs["route"]).item()
        policy_idx = torch.argmax(probs["policy"]).item()
        
        confidence = min(
            probs["intent"][intent_idx].item(),
            probs["evidence"][evidence_idx].item(),
            probs["route"][route_idx].item(),
        )
        
        decision = RoutingDecision(
            intent_family=INTENT_CLASSES[intent_idx],
            evidence_mode=EVIDENCE_CLASSES[evidence_idx],
            route=ROUTE_CLASSES[route_idx],
            policy_override=POLICY_CLASSES[policy_idx],
            confidence=confidence,
            model="modernbert-router",
        )
        
        # Low confidence → fall back to legacy keyword router
        if confidence < 0.75:
            decision.fallback_reason = "low_confidence"
            decision.fallback_to_legacy = True
        
        return decision
```

### 6.2 Batch Inference for Shadow Mode

```python
def shadow_compare(queries: list[str], legacy_router, modern_router) -> ShadowReport:
    """Run both routers and log divergence."""
    report = ShadowReport()
    for query in queries:
        legacy = legacy_router.select_route(query)
        modern = modern_router.predict(query)
        
        divergence = (
            legacy.route != modern.route or
            legacy.evidence_mode != modern.evidence_mode
        )
        
        report.add_comparison(query, legacy, modern, divergence)
    
    report.divergence_rate = report.divergence_count / len(queries)
    return report
```

---

## 7. Shadow Mode Deployment Plan

### Phase 1: Parallel Execution (Week 1)
- ModernBERT router predicts on every query
- Result logged but NOT used for actual routing
- Legacy router makes the real decision
- Divergence dashboard tracks `route`, `evidence_mode`, `intent_family` mismatches

### Phase 2: Confidence-Gated Cutover (Week 2)
- If ModernBERT confidence > 0.90: use ModernBERT decision
- If confidence 0.75-0.90: use ModernBERT but flag for review
- If confidence < 0.75: fall back to legacy router

### Phase 3: Full Cutover (Week 3+)
- Remove legacy router once divergence < 1% and no high-confidence errors for 7 days

---

## 8. Calibration

### 8.1 Temperature Scaling

```python
def calibrate_temperature(model, val_loader, device, config):
    """Find optimal temperature T such that model confidence matches accuracy."""
    best_t = 1.0
    best_ece = float('inf')
    
    for t in torch.linspace(config.val_temperature_search_range[0], 
                            config.val_temperature_search_range[1], 50):
        ece = compute_expected_calibration_error(model, val_loader, device, temperature=t)
        if ece < best_ece:
            best_ece = ece
            best_t = t.item()
    
    return best_t
```

### 8.2 Expected Calibration Error (ECE)

```python
def compute_ece(confidences: np.ndarray, accuracies: np.ndarray, n_bins: int = 10) -> float:
    """Lower ECE = better calibrated model."""
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        mask = (confidences >= bin_boundaries[i]) & (confidences < bin_boundaries[i+1])
        if mask.sum() == 0:
            continue
        avg_confidence = confidences[mask].mean()
        avg_accuracy = accuracies[mask].mean()
        ece += mask.sum() * abs(avg_confidence - avg_accuracy)
    return ece / len(confidences)
```

**Target ECE:** < 0.05 (well-calibrated). If ECE > 0.10, the model is overconfident and needs more calibration data.

---

## 9. Mode Selection Logic (The Critical Path)

The ModernBERT router does not replace `select_route()` — it replaces `classify_intent()` and `requires_evidence_mode()`. The deterministic policy logic (`disabled` overrides everything, `evidence_mode=required` forces AUGMENTED) remains in code. This preserves manifest authorization and prevents the model from being "too creative" with routing.

```python
def modern_select_route(query: str, policy: str, router: ModernBertRouter) -> RoutingDecision:
    """Hybrid: ModernBERT for intent + evidence, code for policy enforcement."""
    
    # Step 1: Neural classification
    prediction = router.predict(query)
    
    # Step 2: Policy enforcement (deterministic, never learned)
    if policy == "disabled":
        return _make_local_decision(prediction.intent_family)
    
    # Step 3: Evidence mode override (deterministic)
    if prediction.evidence_mode == "required":
        return _make_augmented_decision(prediction.intent_family, prefer_paid=True)
    
    # Step 4: Intent-specific routing (deterministic mapping from intent to route)
    if prediction.intent_family == "time_query":
        return _make_time_decision(query)
    if prediction.intent_family == "news_request":
        return _make_news_decision(query)
    if prediction.intent_family == "clarification":
        return _make_clarify_decision(query)
    
    # Step 5: Policy-aware fallback
    if prediction.intent_family in ("background_overview", "technical_explanation"):
        if policy == "direct_allowed":
            return _make_augmented_decision(prediction.intent_family, prefer_paid=False)
        else:
            return _make_local_with_fallback(prediction.intent_family)
    
    # Step 6: Default local
    return _make_local_decision(prediction.intent_family)
```

**Key principle:** ModernBERT decides *what the user is asking*. Code decides *what to do about it*. This separation prevents the model from learning bad habits (like always routing to AUGMENTED because it gets better feedback scores).

---

## 10. Files to Create (Next Session)

| File | Purpose |
|------|---------|
| `models/router/dataset.py` | Load historical data, generate synthetic examples, tokenize |
| `models/router/model.py` | `RouterClassifier` — ModernBERT + 4 classification heads |
| `models/router/train.py` | Training loop with validation, checkpointing, calibration |
| `models/router/inference.py` | `ModernBertRouter.predict()` for production use |
| `models/router/shadow.py` | Parallel execution + divergence logging |
| `models/router/export_data.py` | Script to extract labeled data from `state/last_route.json` |
| `models/router/config.yaml` | Hyperparameters and class definitions |
| `models/router/requirements.txt` | `transformers`, `torch`, `datasets`, `scikit-learn` |

---

## 11. Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Intent accuracy | > 95% | Per-class F1 on held-out test set |
| Evidence trigger recall | > 98% | Must not miss medical/conflict evidence requirements |
| Route accuracy | > 93% | Match legacy router on historical queries |
| Inference latency | < 50ms | CPU-only, batch_size=1 |
| Model size | < 500MB | After quantization (INT8) |
| Shadow divergence | < 2% | First week of parallel execution |
| Calibration ECE | < 0.05 | On validation set |

---

*End of Design Document*
