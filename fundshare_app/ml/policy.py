"""
FUNDShare-MFS Trust & Risk Policy Engine
Decouples operational risk actions and velocity thresholds from ML scoring models.
Reads configurable policy bands from config/risk_policy.yaml.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from django.conf import settings

try:
    BASE_DIR = Path(settings.BASE_DIR)
except Exception:
    BASE_DIR = Path(__file__).resolve().parent.parent.parent

DEFAULT_CONFIG_PATH = BASE_DIR / 'config' / 'risk_policy.yaml'

DEFAULT_POLICY_DICT: Dict[str, Any] = {
    'version': '1.0',
    'bands': {
        'allow_threshold': 0.35,
        'step_up_threshold': 0.70,
    },
    'actions': {
        'low': 'ALLOW',
        'medium': 'STEP_UP_PIN',
        'high': 'FLAG_FOR_REVIEW',
    },
    'risk_tiers': {
        'low': 'LOW',
        'medium': 'MEDIUM',
        'high': 'HIGH',
    },
    'velocity_rules': {
        'max_txns_per_hour': 5,
        'amount_spike_ratio': 3.5,
        'off_peak_hours': [1, 2, 3, 4],
        'zscore_threshold': 3.5,
    },
}


def _simple_yaml_parse(text: str) -> Dict[str, Any]:
    """
    Lightweight, dependency-free parser for standard key-value and nested dict YAML files.
    Ensures config/risk_policy.yaml can be read even without external PyYAML.
    """
    result: Dict[str, Any] = {}
    current_section: Optional[str] = None

    for line in text.splitlines():
        # Remove comments and trailing whitespace
        clean_line = re.sub(r'#.*$', '', line).rstrip()
        if not clean_line.strip():
            continue

        indent = len(clean_line) - len(clean_line.lstrip())
        content = clean_line.strip()

        if indent == 0 and content.endswith(':'):
            current_section = content[:-1].strip()
            result[current_section] = {}
            continue

        if ':' in content:
            key, val = content.split(':', 1)
            key = key.strip()
            val = val.strip()

            # Parse value type
            parsed_val: Any = val
            if val == '' or val is None:
                parsed_val = {}
            elif val.startswith('[') and val.endswith(']'):
                items = [item.strip() for item in val[1:-1].split(',') if item.strip()]
                parsed_items = []
                for it in items:
                    try:
                        parsed_items.append(int(it))
                    except ValueError:
                        try:
                            parsed_items.append(float(it))
                        except ValueError:
                            parsed_items.append(it.strip("'\""))
                parsed_val = parsed_items
            elif val.lower() in ('true', 'yes'):
                parsed_val = True
            elif val.lower() in ('false', 'no'):
                parsed_val = False
            else:
                try:
                    parsed_val = int(val)
                except ValueError:
                    try:
                        parsed_val = float(val)
                    except ValueError:
                        parsed_val = val.strip("'\"")

            if indent > 0 and current_section:
                if not isinstance(result.get(current_section), dict):
                    result[current_section] = {}
                result[current_section][key] = parsed_val
            else:
                result[key] = parsed_val

    return result


class RiskPolicyEngine:
    """
    Evaluates ML continuous risk scores and transaction features against externalized risk policy.
    Maps scores to operational actions:
      - ALLOW: score < 0.35
      - STEP_UP_PIN: 0.35 <= score < 0.70
      - FLAG_FOR_REVIEW: score >= 0.70 (auto-hold)
    Enforces hard velocity rules (max 5 txns/hr, amount spike ratio > 3.5x).
    """

    _instance: Optional[RiskPolicyEngine] = None
    _lock: RLock = RLock()

    def __init__(self, config_path: Optional[Path | str] = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.policy: Dict[str, Any] = self._load_policy()

    def _load_policy(self) -> Dict[str, Any]:
        """Loads policy from YAML with PyYAML or built-in parser, falling back to defaults."""
        if not self.config_path.exists():
            logger.warning("Risk policy file %s not found; using internal defaults.", self.config_path)
            return dict(DEFAULT_POLICY_DICT)

        try:
            content = self.config_path.read_text(encoding='utf-8')
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(content)
            except ImportError:
                data = _simple_yaml_parse(content)

            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.exception("Error parsing risk policy file %s (%s); using defaults.", self.config_path, e)

        return dict(DEFAULT_POLICY_DICT)

    def reload(self) -> None:
        """Reloads policy from disk."""
        self.policy = self._load_policy()

    @classmethod
    def get_instance(cls, config_path: Optional[Path | str] = None) -> RiskPolicyEngine:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config_path)
            return cls._instance

    def evaluate(self, risk_score: float, features: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Evaluates risk score and features against policy rules.

        Returns:
            {
                "action": "ALLOW" | "STEP_UP_PIN" | "FLAG_FOR_REVIEW",
                "risk_tier": "LOW" | "MEDIUM" | "HIGH",
                "risk_score": float,
                "reasons": list[str],
                "hard_rules_triggered": list[str],
                "is_hold": bool,
                "step_up_required": bool,
            }
        """
        features = features or {}
        score = float(risk_score)
        bands = self.policy.get('bands', DEFAULT_POLICY_DICT['bands'])
        actions = self.policy.get('actions', DEFAULT_POLICY_DICT['actions'])
        tiers = self.policy.get('risk_tiers', DEFAULT_POLICY_DICT['risk_tiers'])
        velocity_cfg = self.policy.get('velocity_rules', DEFAULT_POLICY_DICT['velocity_rules'])

        allow_thresh = float(bands.get('allow_threshold', 0.35))
        step_up_thresh = float(bands.get('step_up_threshold', 0.70))

        reasons: List[str] = []
        hard_rules_triggered: List[str] = []

        # 1. Base score band evaluation
        if score < allow_thresh:
            action = actions.get('low', 'ALLOW')
            risk_tier = tiers.get('low', 'LOW')
            reasons.append(f"Risk score ({score:.2f}) is within normal parameters (< {allow_thresh:.2f}).")
        elif score < step_up_thresh:
            action = actions.get('medium', 'STEP_UP_PIN')
            risk_tier = tiers.get('medium', 'MEDIUM')
            reasons.append(f"Moderate risk score ({score:.2f}). Requires step-up PIN verification.")
        else:
            action = actions.get('high', 'FLAG_FOR_REVIEW')
            risk_tier = tiers.get('high', 'HIGH')
            reasons.append(f"High risk score ({score:.2f} >= {step_up_thresh:.2f}). Flagged for review and auto-hold.")

        # 2. Hard velocity & safety rules (escalations)
        # Rule A: Transaction Velocity (max txns/hr)
        max_txns_hr = float(velocity_cfg.get('max_txns_per_hour', 5))
        txns_1h = float(features.get('txns_per_hour') or features.get('velocity_1h') or 0)
        if txns_1h > max_txns_hr:
            hard_rules_triggered.append("VELOCITY_LIMIT_EXCEEDED")
            reasons.append(f"Velocity alert: {int(txns_1h)} transactions in 1 hour exceeds limit ({int(max_txns_hr)}/hr).")
            # Escalate
            if action == actions.get('low', 'ALLOW'):
                action = actions.get('medium', 'STEP_UP_PIN')
                risk_tier = tiers.get('medium', 'MEDIUM')
            elif action == actions.get('medium', 'STEP_UP_PIN'):
                action = actions.get('high', 'FLAG_FOR_REVIEW')
                risk_tier = tiers.get('high', 'HIGH')

        # Rule B: Amount Spike Ratio (> 3.5x)
        max_spike_ratio = float(velocity_cfg.get('amount_spike_ratio', 3.5))
        u_ratio = float(features.get('user_ratio') or 1.0)
        c_ratio = float(features.get('category_ratio') or 1.0)
        spike_ratio = max(u_ratio, c_ratio)
        if spike_ratio > max_spike_ratio:
            hard_rules_triggered.append("AMOUNT_SPIKE_RATIO")
            reasons.append(f"Amount spike: Transaction amount is {spike_ratio:.1f}× baseline (> {max_spike_ratio:.1f}× limit).")
            # Spike ratio escalates directly to FLAG_FOR_REVIEW
            action = actions.get('high', 'FLAG_FOR_REVIEW')
            risk_tier = tiers.get('high', 'HIGH')

        # Rule C: Statistical 3.5-Sigma Outlier
        z_thresh = float(velocity_cfg.get('zscore_threshold', 3.5))
        u_z = float(features.get('user_zscore') or 0.0)
        c_z = float(features.get('category_zscore') or 0.0)
        max_z = max(u_z, c_z)
        if max_z >= z_thresh:
            hard_rules_triggered.append("STATISTICAL_OUTLIER")
            reasons.append(f"Statistical deviation: Spending is {max_z:.1f}σ above baseline (threshold: {z_thresh:.1f}σ).")
            if action == actions.get('low', 'ALLOW'):
                action = actions.get('medium', 'STEP_UP_PIN')
                risk_tier = tiers.get('medium', 'MEDIUM')

        # Rule D: Off-Peak Hours
        off_peak_hours = velocity_cfg.get('off_peak_hours', [1, 2, 3, 4])
        hour = features.get('hour')
        if hour is not None and hour in off_peak_hours:
            hard_rules_triggered.append("OFF_PEAK_HOUR")
            reasons.append(f"Off-peak timing: Transaction occurred during night hours ({int(hour):02d}:00).")

        # 3. Incorporate top contributing factors if provided
        top_contributions = features.get('top_contributions')
        if top_contributions and isinstance(top_contributions, list):
            for item in top_contributions:
                if isinstance(item, dict) and 'description' in item:
                    reasons.append(f"Top factor: {item['description']}")
                elif isinstance(item, str):
                    reasons.append(f"Top factor: {item}")

        return {
            'action': action,
            'risk_tier': risk_tier,
            'risk_score': round(score, 4),
            'reasons': reasons,
            'hard_rules_triggered': hard_rules_triggered,
            'is_hold': action == actions.get('high', 'FLAG_FOR_REVIEW'),
            'step_up_required': action == actions.get('medium', 'STEP_UP_PIN'),
        }
