"""ConditionalEvaluator — resolves auto-evaluated question types.

Three question types are never shown to the user.  The engine calls
:meth:`evaluate` to determine their action based on demographics and
prior answers:

  - **gender_filter**: matches the patient's gender against option IDs
  - **age_filter**: matches the patient's age against option ID thresholds
  - **conditional**: evaluates predicate rules against prior answers

Returns the resolved ``Action`` or ``None`` if no rule matched (and no
default is set).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from prescreen_rulesets.models.action import Action
from prescreen_rulesets.models.question import (
    AgeFilterQuestion,
    ConditionalQuestion,
    GenderQuestion,
    Predicate,
    Question,
)

logger = logging.getLogger(__name__)


class ConditionalEvaluator:
    """Evaluates auto-resolved question types against session context."""

    def evaluate(
        self,
        question: Question,
        answers: dict[str, Any],
        demographics: dict[str, Any],
    ) -> Action | None:
        """Dispatch to the appropriate evaluator based on question_type.

        Args:
            question: the auto-eval question to resolve
            answers: dict of prior answers keyed by qid (each value is the
                     raw answer, not the {value, answered_at} wrapper)
            demographics: patient demographics dict (keys: gender, age, etc.)

        Returns:
            The resolved Action, or None if no rule matched.
        """
        qt = question.question_type
        if qt == "conditional":
            return self._eval_conditional(question, answers)
        elif qt == "age_filter":
            return self._eval_age_filter(question, demographics.get("age"))
        elif qt == "gender_filter":
            return self._eval_gender_filter(question, demographics.get("gender", ""))
        else:
            logger.warning("evaluate() called with non-auto type: %s", qt)
            return None

    # ------------------------------------------------------------------
    # Type-specific evaluators
    # ------------------------------------------------------------------

    def _eval_conditional(
        self, q: ConditionalQuestion, answers: dict[str, Any]
    ) -> Action | None:
        """Evaluate conditional rules in order; first match wins.

        Each rule has a list of ``when`` predicates that are AND-ed together.
        If all predicates in a rule pass, that rule's ``then`` action fires.
        If no rule matches, falls back to ``q.default``.
        """
        for rule in q.rules:
            if all(self._eval_predicate(pred, answers) for pred in rule.when):
                return rule.then
        return q.default

    def _eval_age_filter(
        self, q: AgeFilterQuestion, age: int | float | None
    ) -> Action | None:
        """Match patient age against age_filter option thresholds.

        Age filter options use IDs like "lt_15" or "gte_15".  The convention
        is ``{operator}_{threshold}``, but we parse the common patterns:
          - "lt_N"  → age < N
          - "gte_N" → age >= N
          - "le_N"  → age <= N
          - "gt_N"  → age > N

        Falls back to matching option labels if no ID convention matches.
        """
        if age is None:
            logger.warning("age_filter question %s: age is None", q.qid)
            return None

        age_num = float(age)

        for opt in q.options:
            opt_id = opt.id.lower()

            # Try parsing structured ID: "lt_15", "gte_15", "le_15", "gt_15"
            match = re.match(r"^(lt|lte|le|gt|gte|ge)_(\d+(?:\.\d+)?)$", opt_id)
            if match:
                op, threshold_str = match.groups()
                threshold = float(threshold_str)
                matched = False
                if op in ("lt",):
                    matched = age_num < threshold
                elif op in ("le", "lte"):
                    matched = age_num <= threshold
                elif op in ("gt",):
                    matched = age_num > threshold
                elif op in ("ge", "gte"):
                    matched = age_num >= threshold

                if matched:
                    return opt.action
                continue

            # Fallback: try parsing label for patterns like "<15", ">=15"
            label = opt.label.strip()
            label_match = re.match(r"^([<>]=?)\s*(\d+(?:\.\d+)?)$", label)
            if label_match:
                op_str, threshold_str = label_match.groups()
                threshold = float(threshold_str)
                matched = False
                if op_str == "<":
                    matched = age_num < threshold
                elif op_str == "<=":
                    matched = age_num <= threshold
                elif op_str == ">":
                    matched = age_num > threshold
                elif op_str == ">=":
                    matched = age_num >= threshold
                if matched:
                    return opt.action

        # No option matched — return the last option as fallback
        # (age filters are typically binary: "<15" vs ">=15")
        logger.warning("age_filter %s: no option matched age=%s, using last option", q.qid, age)
        return q.options[-1].action if q.options else None

    def _eval_gender_filter(
        self, q: GenderQuestion, gender: str
    ) -> Action | None:
        """Match patient gender against gender_filter option IDs.

        Gender filter options have IDs like "male", "female".  The engine
        matches the patient's gender string (case-insensitive) against
        option IDs and labels.
        """
        gender_lower = gender.lower().strip()

        for opt in q.options:
            if opt.id.lower() == gender_lower or opt.label.lower() == gender_lower:
                return opt.action

        # No exact match — log and return None
        logger.warning("gender_filter %s: no option matched gender=%r", q.qid, gender)
        return None

    # ------------------------------------------------------------------
    # Predicate evaluation
    # ------------------------------------------------------------------

    def _eval_predicate(self, pred: Predicate, answers: dict[str, Any]) -> bool:
        """Evaluate a single predicate against the answers dict.

        If the referenced qid has not been answered yet, the predicate
        evaluates to False (the rule won't match).
        """
        # Get the raw answer for the referenced qid
        answer = answers.get(pred.qid)
        if answer is None:
            return False

        # If the predicate references a sub-field (for free_text_with_fields),
        # drill into the answer dict
        if pred.field is not None:
            if isinstance(answer, dict):
                answer = answer.get(pred.field)
            else:
                return False

        return self._compare(pred.op, answer, pred.value)

    @staticmethod
    def _compare(op: str, answer: Any, value: Any) -> bool:
        """Apply an operator to an answer and an expected value.

        Handles type coercion for numeric comparisons (answers from YAML
        or user input may be strings).
        """
        if op == "eq":
            return answer == value

        if op == "ne":
            return answer != value

        # --- Numeric comparisons ---
        if op in ("lt", "le", "gt", "ge", "between"):
            try:
                ans_num = float(answer)
            except (TypeError, ValueError):
                return False

            if op == "lt":
                return ans_num < float(value)
            if op == "le":
                return ans_num <= float(value)
            if op == "gt":
                return ans_num > float(value)
            if op == "ge":
                return ans_num >= float(value)
            if op == "between":
                # value is expected to be [min, max]
                lo, hi = float(value[0]), float(value[1])
                return lo <= ans_num <= hi

        # --- Collection / string membership ---
        if op == "contains":
            # Works for both "X in list" and "substring in string"
            if isinstance(answer, list):
                return value in answer
            return str(value) in str(answer)

        if op == "not_contains":
            if isinstance(answer, list):
                return value not in answer
            return str(value) not in str(answer)

        if op == "contains_any":
            # value is a list; true if answer contains any of them
            if isinstance(answer, list):
                return any(v in answer for v in value)
            ans_str = str(answer)
            return any(str(v) in ans_str for v in value)

        if op == "contains_all":
            # value is a list; true if answer contains all of them
            if isinstance(answer, list):
                return all(v in answer for v in value)
            ans_str = str(answer)
            return all(str(v) in ans_str for v in value)

        if op == "matches":
            # Regex match against the answer string
            return bool(re.search(str(value), str(answer)))

        logger.warning("Unknown predicate operator: %s", op)
        return False
