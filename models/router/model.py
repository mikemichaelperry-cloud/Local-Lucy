#!/usr/bin/env python3
"""ModernBERT-based multi-task router classifier."""

from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
from transformers import AutoModel, AutoTokenizer


HEAD_NAMES = ["intent", "evidence", "route", "policy"]


class RouterClassifier(nn.Module):
    """Multi-task classifier on top of ModernBERT.
    
    Four independent classification heads:
      - intent_family: 8 classes
      - evidence_mode: 3 classes  
      - route: 6 classes
      - policy_override: 4 classes
    """
    
    def __init__(self, base_model: AutoModel, config: dict[str, Any]):
        super().__init__()
        self.base_model = base_model
        hidden_size = base_model.config.hidden_size  # 768 for ModernBERT-base
        dropout_rate = config.get("dropout", 0.1)
        
        self.dropout = nn.Dropout(dropout_rate)
        
        # Independent classification heads
        self.intent_head = nn.Linear(hidden_size, config["num_intent_classes"])
        self.evidence_head = nn.Linear(hidden_size, config["num_evidence_classes"])
        self.route_head = nn.Linear(hidden_size, config["num_route_classes"])
        self.policy_head = nn.Linear(hidden_size, config["num_policy_classes"])
        
        # Initialize head weights
        for head in [self.intent_head, self.evidence_head, self.route_head, self.policy_head]:
            nn.init.xavier_uniform_(head.weight)
            nn.init.zeros_(head.bias)
    
    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> dict[str, torch.Tensor]:
        outputs = self.base_model(input_ids=input_ids, attention_mask=attention_mask)
        # Use [CLS] token representation (first position)
        cls_output = outputs.last_hidden_state[:, 0, :]
        cls_output = self.dropout(cls_output)
        
        return {
            "intent": self.intent_head(cls_output),
            "evidence": self.evidence_head(cls_output),
            "route": self.route_head(cls_output),
            "policy": self.policy_head(cls_output),
        }
    
    def save_pretrained(self, save_directory: str | Path) -> None:
        """Save model weights and config."""
        save_directory = Path(save_directory)
        save_directory.mkdir(parents=True, exist_ok=True)
        torch.save(self.state_dict(), save_directory / "pytorch_model.bin")
    
    @classmethod
    def from_checkpoint(cls, checkpoint_path: str | Path, base_model_name: str = "answerdotai/ModernBERT-base", config: dict[str, Any] | None = None) -> "RouterClassifier":
        """Load model from checkpoint."""
        checkpoint_path = Path(checkpoint_path)
        
        if config is None:
            config = {
                "num_intent_classes": 9,
                "num_evidence_classes": 3,
                "num_route_classes": 6,
                "num_policy_classes": 4,
                "dropout": 0.1,
            }
        
        base_model = AutoModel.from_pretrained(base_model_name)
        model = cls(base_model, config)
        
        state_dict = torch.load(checkpoint_path / "pytorch_model.bin", map_location="cpu")
        model.load_state_dict(state_dict)
        return model


class ModernBertRouter:
    """Production inference wrapper.
    
    Dynamically detects label dimensions from checkpoint to support
    both v1 (8 intent classes) and v2+ (9 intent classes) models.
    """
    
    # Full label vocabularies — truncated to match model output dimension
    INTENT_LABELS = [
        "local_answer", "background_overview", "current_evidence",
        "clarification", "technical_explanation", "creative_writing",
        "medical_inquiry", "news_request", "time_query"
    ]
    EVIDENCE_LABELS = ["not_required", "required", "uncertain"]
    ROUTE_LABELS = ["LOCAL", "LOCAL_WITH_FALLBACK", "AUGMENTED", "NEWS", "TIME", "CLARIFY"]
    POLICY_LABELS = ["none", "disabled", "fallback_only", "force_augmented"]
    
    def __init__(self, model_path: str, config_path: str | None = None, temperature: float = 1.0):
        self.device = torch.device("cpu")
        self.tokenizer = AutoTokenizer.from_pretrained("answerdotai/ModernBERT-base")
        
        self.model = RouterClassifier.from_checkpoint(model_path)
        self.model.eval()
        self.model.to(self.device)
        
        # Detect output dimensions from model heads
        self.intent_classes = self.INTENT_LABELS[:self.model.intent_head.out_features]
        self.evidence_classes = self.EVIDENCE_LABELS[:self.model.evidence_head.out_features]
        self.route_classes = self.ROUTE_LABELS[:self.model.route_head.out_features]
        self.policy_classes = self.POLICY_LABELS[:self.model.policy_head.out_features]
        
        self.temperature = temperature
    
    def predict(self, query: str) -> dict[str, Any]:
        """Predict routing labels for a single query.
        
        Returns dict with:
          - intent_family (str)
          - evidence_mode (str)
          - route (str)
          - policy_override (str)
          - confidence (float) — minimum confidence across all heads
          - probs (dict) — full probability distributions
        """
        inputs = self.tokenizer(
            query,
            return_tensors="pt",
            truncation=True,
            max_length=256,
            padding=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            logits = self.model(inputs["input_ids"], inputs["attention_mask"])
        
        # Apply temperature scaling
        probs = {
            head: torch.softmax(logit / self.temperature, dim=-1)[0]
            for head, logit in logits.items()
        }
        
        # Get predictions and confidences
        intent_idx = torch.argmax(probs["intent"]).item()
        evidence_idx = torch.argmax(probs["evidence"]).item()
        route_idx = torch.argmax(probs["route"]).item()
        policy_idx = torch.argmax(probs["policy"]).item()
        
        confidence = min(
            probs["intent"][intent_idx].item(),
            probs["evidence"][evidence_idx].item(),
            probs["route"][route_idx].item(),
        )
        
        return {
            "intent_family": self.intent_classes[intent_idx],
            "evidence_mode": self.evidence_classes[evidence_idx],
            "route": self.route_classes[route_idx],
            "policy_override": self.policy_classes[policy_idx],
            "confidence": round(confidence, 4),
            "probs": {
                "intent": {label: round(p, 4) for label, p in zip(self.intent_classes, probs["intent"].tolist())},
                "evidence": {label: round(p, 4) for label, p in zip(self.evidence_classes, probs["evidence"].tolist())},
                "route": {label: round(p, 4) for label, p in zip(self.route_classes, probs["route"].tolist())},
                "policy": {label: round(p, 4) for label, p in zip(self.policy_classes, probs["policy"].tolist())},
            }
        }
