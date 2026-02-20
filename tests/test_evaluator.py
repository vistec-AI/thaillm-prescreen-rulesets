"""ConditionalEvaluator unit tests — all operators and auto-eval types.

Tests every predicate operator, age/gender filter resolution, and
conditional rule evaluation logic.  Each operator has at least one
positive and one negative case.

Operator reference (from evaluator._compare):
    eq, ne              — equality / inequality
    lt, le, gt, ge      — numeric comparisons (auto-coerces strings to float)
    between             — inclusive range check, value = [lo, hi]
    contains            — substring (str) or element (list) membership
    not_contains        — inverse of contains
    contains_any        — any of value items in answer (list or str)
    contains_all        — all of value items in answer (list or str)
    matches             — regex match (re.search)
"""

import pytest

from prescreen_rulesets.evaluator import ConditionalEvaluator
from prescreen_rulesets.models.action import (
    DepartmentRef,
    GotoAction,
    TerminateAction,
    TerminateMetadata,
)
from prescreen_rulesets.models.question import (
    ActionOption,
    AgeFilterQuestion,
    ConditionalQuestion,
    GenderQuestion,
    Predicate,
    Rule,
)


# --- Helpers to reduce boilerplate ---


def _goto(*qids):
    """Shorthand to build a GotoAction."""
    return GotoAction(action="goto", qid=list(qids))


def _terminate(dept_ids=None, reason=None):
    """Shorthand to build a TerminateAction."""
    return TerminateAction(
        action="terminate",
        reason=reason,
        metadata=TerminateMetadata(
            department=[DepartmentRef(id=d) for d in (dept_ids or [])],
        ),
    )


def _action_opt(opt_id, label, action):
    """Shorthand to build an ActionOption."""
    return ActionOption(id=opt_id, label=label, action=action)


@pytest.fixture
def evaluator():
    """Fresh ConditionalEvaluator for each test."""
    return ConditionalEvaluator()


# =====================================================================
# Predicate operator tests — one test per operator
# =====================================================================


class TestPredicateOperators:
    """Unit tests for each predicate comparison operator."""

    def test_eq(self, evaluator):
        """eq returns True when answer matches value exactly."""
        pred = Predicate(qid="q1", op="eq", value="yes")
        assert evaluator._eval_predicate(pred, {"q1": "yes"}) is True
        assert evaluator._eval_predicate(pred, {"q1": "no"}) is False

    def test_ne(self, evaluator):
        """ne returns True when answer differs from value."""
        pred = Predicate(qid="q1", op="ne", value="yes")
        assert evaluator._eval_predicate(pred, {"q1": "no"}) is True
        assert evaluator._eval_predicate(pred, {"q1": "yes"}) is False

    def test_lt(self, evaluator):
        """lt returns True when answer is strictly less than value."""
        pred = Predicate(qid="q1", op="lt", value=10)
        assert evaluator._eval_predicate(pred, {"q1": 5}) is True
        assert evaluator._eval_predicate(pred, {"q1": 10}) is False
        assert evaluator._eval_predicate(pred, {"q1": 15}) is False

    def test_le(self, evaluator):
        """le returns True when answer is less than or equal to value."""
        pred = Predicate(qid="q1", op="le", value=10)
        assert evaluator._eval_predicate(pred, {"q1": 10}) is True
        assert evaluator._eval_predicate(pred, {"q1": 5}) is True
        assert evaluator._eval_predicate(pred, {"q1": 11}) is False

    def test_gt(self, evaluator):
        """gt returns True when answer is strictly greater than value."""
        pred = Predicate(qid="q1", op="gt", value=10)
        assert evaluator._eval_predicate(pred, {"q1": 15}) is True
        assert evaluator._eval_predicate(pred, {"q1": 10}) is False
        assert evaluator._eval_predicate(pred, {"q1": 5}) is False

    def test_ge(self, evaluator):
        """ge returns True when answer is greater than or equal to value."""
        pred = Predicate(qid="q1", op="ge", value=10)
        assert evaluator._eval_predicate(pred, {"q1": 10}) is True
        assert evaluator._eval_predicate(pred, {"q1": 15}) is True
        assert evaluator._eval_predicate(pred, {"q1": 9}) is False

    def test_between(self, evaluator):
        """between returns True when answer is in [lo, hi] inclusive."""
        pred = Predicate(qid="q1", op="between", value=[5, 10])
        assert evaluator._eval_predicate(pred, {"q1": 7}) is True
        assert evaluator._eval_predicate(pred, {"q1": 5}) is True, "lo boundary"
        assert evaluator._eval_predicate(pred, {"q1": 10}) is True, "hi boundary"
        assert evaluator._eval_predicate(pred, {"q1": 4}) is False
        assert evaluator._eval_predicate(pred, {"q1": 11}) is False

    def test_contains_string(self, evaluator):
        """contains returns True when value is a substring of answer."""
        pred = Predicate(qid="q1", op="contains", value="abc")
        assert evaluator._eval_predicate(pred, {"q1": "xabcx"}) is True
        assert evaluator._eval_predicate(pred, {"q1": "xyz"}) is False

    def test_contains_list(self, evaluator):
        """contains returns True when value is an element of the answer list."""
        pred = Predicate(qid="q1", op="contains", value="a")
        assert evaluator._eval_predicate(pred, {"q1": ["a", "b", "c"]}) is True
        assert evaluator._eval_predicate(pred, {"q1": ["b", "c"]}) is False

    def test_not_contains(self, evaluator):
        """not_contains returns True when value is NOT in the answer."""
        pred = Predicate(qid="q1", op="not_contains", value="x")
        assert evaluator._eval_predicate(pred, {"q1": ["a", "b"]}) is True
        assert evaluator._eval_predicate(pred, {"q1": ["x", "b"]}) is False

    def test_contains_any(self, evaluator):
        """contains_any returns True when any of value items appear in answer."""
        pred = Predicate(qid="q1", op="contains_any", value=["a", "d"])
        assert evaluator._eval_predicate(pred, {"q1": ["a", "b", "c"]}) is True
        assert evaluator._eval_predicate(pred, {"q1": ["x", "y"]}) is False

    def test_contains_all(self, evaluator):
        """contains_all returns True when all value items appear in answer."""
        pred = Predicate(qid="q1", op="contains_all", value=["a", "b"])
        assert evaluator._eval_predicate(pred, {"q1": ["a", "b", "c"]}) is True
        assert evaluator._eval_predicate(pred, {"q1": ["a", "c"]}) is False

    def test_matches_regex(self, evaluator):
        """matches returns True when answer matches the regex pattern."""
        pred = Predicate(qid="q1", op="matches", value=r"^\d{3}-\d{4}$")
        assert evaluator._eval_predicate(pred, {"q1": "123-4567"}) is True
        assert evaluator._eval_predicate(pred, {"q1": "abc"}) is False


# =====================================================================
# Predicate edge cases
# =====================================================================


class TestPredicateEdgeCases:
    """Edge cases for predicate evaluation."""

    def test_missing_answer_returns_false(self, evaluator):
        """Predicate returns False when the referenced qid has not been answered."""
        pred = Predicate(qid="q_missing", op="eq", value="yes")
        assert evaluator._eval_predicate(pred, {}) is False

    def test_numeric_coercion(self, evaluator):
        """Numeric operators coerce string answers to float."""
        pred = Predicate(qid="q1", op="gt", value=10)
        assert evaluator._eval_predicate(pred, {"q1": "15"}) is True

    def test_numeric_coercion_fails_gracefully(self, evaluator):
        """Non-numeric string answer returns False for numeric operators."""
        pred = Predicate(qid="q1", op="gt", value=10)
        assert evaluator._eval_predicate(pred, {"q1": "not_a_number"}) is False

    def test_field_drill_down(self, evaluator):
        """Predicate with field drills into a dict answer."""
        pred = Predicate(qid="q1", field="medication", op="eq", value="aspirin")
        answers = {"q1": {"medication": "aspirin", "dosage": "100mg"}}
        assert evaluator._eval_predicate(pred, answers) is True

    def test_field_drill_down_missing_field(self, evaluator):
        """Returns False when the specified field doesn't exist in the answer dict."""
        pred = Predicate(qid="q1", field="missing_field", op="eq", value="x")
        answers = {"q1": {"other_field": "y"}}
        assert evaluator._eval_predicate(pred, answers) is False

    def test_field_on_non_dict_answer(self, evaluator):
        """Returns False when field is specified but answer is not a dict."""
        pred = Predicate(qid="q1", field="f", op="eq", value="x")
        answers = {"q1": "plain_string"}
        assert evaluator._eval_predicate(pred, answers) is False

    def test_between_out_of_range(self, evaluator):
        """between returns False when answer is outside the range."""
        pred = Predicate(qid="q1", op="between", value=[1, 5])
        assert evaluator._eval_predicate(pred, {"q1": 0}) is False
        assert evaluator._eval_predicate(pred, {"q1": 6}) is False


# =====================================================================
# Age filter tests
# =====================================================================


class TestAgeFilter:
    """Tests for age_filter question evaluation.

    Age filter options use structured IDs like "lt_15" or "gte_15".
    The evaluator parses these conventions to determine which option
    matches the patient's age.
    """

    def _make_age_filter(self, options):
        """Build an AgeFilterQuestion from (id, label, action) tuples."""
        return AgeFilterQuestion(
            qid="test_age",
            question="Age?",
            question_type="age_filter",
            options=[_action_opt(o[0], o[1], o[2]) for o in options],
        )

    def test_lt_threshold(self, evaluator):
        """Age below threshold matches the lt option."""
        q = self._make_age_filter([
            ("lt_15", "<15", _goto("child_q")),
            ("gte_15", ">=15", _goto("adult_q")),
        ])
        action = evaluator.evaluate(q, {}, {"age": 10})
        assert isinstance(action, GotoAction), "Expected GotoAction"
        assert action.qid == ["child_q"]

    def test_gte_threshold(self, evaluator):
        """Age at or above threshold matches the gte option."""
        q = self._make_age_filter([
            ("lt_15", "<15", _goto("child_q")),
            ("gte_15", ">=15", _goto("adult_q")),
        ])
        action = evaluator.evaluate(q, {}, {"age": 20})
        assert isinstance(action, GotoAction), "Expected GotoAction"
        assert action.qid == ["adult_q"]

    def test_exact_boundary(self, evaluator):
        """Age exactly at threshold: lt_15 should NOT match, gte_15 should."""
        q = self._make_age_filter([
            ("lt_15", "<15", _goto("child_q")),
            ("gte_15", ">=15", _goto("adult_q")),
        ])
        action = evaluator.evaluate(q, {}, {"age": 15})
        assert isinstance(action, GotoAction), "Expected GotoAction"
        assert action.qid == ["adult_q"], "Age=15 should match gte_15, not lt_15"

    def test_missing_age(self, evaluator):
        """Returns None when age is not available in demographics."""
        q = self._make_age_filter([
            ("lt_15", "<15", _goto("child_q")),
            ("gte_15", ">=15", _goto("adult_q")),
        ])
        action = evaluator.evaluate(q, {}, {})
        assert action is None


# =====================================================================
# Gender filter tests
# =====================================================================


class TestGenderFilter:
    """Tests for gender_filter question evaluation.

    Gender filter options have IDs like "male" and "female".  The evaluator
    matches the patient's gender string (case-insensitive) against option
    IDs and labels.
    """

    def _make_gender_filter(self):
        """Build a standard gender filter with male/female options."""
        return GenderQuestion(
            qid="test_gender",
            question="Gender?",
            question_type="gender_filter",
            options=[
                _action_opt("male", "Male", _goto("male_q")),
                _action_opt("female", "Female", _goto("female_q")),
            ],
        )

    def test_male(self, evaluator):
        """Male gender matches the male option."""
        q = self._make_gender_filter()
        action = evaluator.evaluate(q, {}, {"gender": "male"})
        assert isinstance(action, GotoAction), "Expected GotoAction"
        assert action.qid == ["male_q"]

    def test_female(self, evaluator):
        """Female gender matches the female option."""
        q = self._make_gender_filter()
        action = evaluator.evaluate(q, {}, {"gender": "female"})
        assert isinstance(action, GotoAction), "Expected GotoAction"
        assert action.qid == ["female_q"]

    def test_case_insensitive(self, evaluator):
        """Gender matching is case-insensitive (e.g. 'Male' matches 'male')."""
        q = self._make_gender_filter()
        action = evaluator.evaluate(q, {}, {"gender": "Male"})
        assert isinstance(action, GotoAction), "Expected GotoAction"
        assert action.qid == ["male_q"]

    def test_no_match(self, evaluator):
        """Returns None when gender doesn't match any option."""
        q = self._make_gender_filter()
        action = evaluator.evaluate(q, {}, {"gender": "other"})
        assert action is None


# =====================================================================
# Conditional question tests
# =====================================================================


class TestConditional:
    """Tests for conditional question evaluation.

    Conditional questions have ordered rules with predicate lists.
    All predicates in a rule are AND-ed.  First matching rule wins.
    Falls back to default if no rule matches.
    """

    def test_first_rule_wins(self, evaluator):
        """When multiple rules match, the first one fires."""
        q = ConditionalQuestion(
            qid="cond1",
            question="conditional",
            question_type="conditional",
            rules=[
                Rule(
                    when=[Predicate(qid="q1", op="eq", value="yes")],
                    then=_goto("first"),
                ),
                Rule(
                    when=[Predicate(qid="q1", op="eq", value="yes")],
                    then=_goto("second"),
                ),
            ],
        )
        action = evaluator.evaluate(q, {"q1": "yes"}, {})
        assert isinstance(action, GotoAction), "Expected GotoAction"
        assert action.qid == ["first"], "First matching rule should win"

    def test_fallback_to_default(self, evaluator):
        """Falls back to default action when no rule matches."""
        q = ConditionalQuestion(
            qid="cond1",
            question="conditional",
            question_type="conditional",
            rules=[
                Rule(
                    when=[Predicate(qid="q1", op="eq", value="yes")],
                    then=_goto("matched"),
                ),
            ],
            default=_goto("default_target"),
        )
        action = evaluator.evaluate(q, {"q1": "no"}, {})
        assert isinstance(action, GotoAction), "Expected GotoAction"
        assert action.qid == ["default_target"]

    def test_no_match_no_default(self, evaluator):
        """Returns None when no rule matches and no default is set."""
        q = ConditionalQuestion(
            qid="cond1",
            question="conditional",
            question_type="conditional",
            rules=[
                Rule(
                    when=[Predicate(qid="q1", op="eq", value="yes")],
                    then=_goto("matched"),
                ),
            ],
            default=None,
        )
        action = evaluator.evaluate(q, {"q1": "no"}, {})
        assert action is None

    def test_multiple_predicates_and(self, evaluator):
        """All predicates in a rule must match (AND logic)."""
        q = ConditionalQuestion(
            qid="cond1",
            question="conditional",
            question_type="conditional",
            rules=[
                Rule(
                    when=[
                        Predicate(qid="q1", op="eq", value="yes"),
                        Predicate(qid="q2", op="gt", value=5),
                    ],
                    then=_goto("both_match"),
                ),
            ],
            default=_goto("fallback"),
        )
        # Both predicates match
        action = evaluator.evaluate(q, {"q1": "yes", "q2": 10}, {})
        assert isinstance(action, GotoAction)
        assert action.qid == ["both_match"]

        # Only first predicate matches — should fall through to default
        action = evaluator.evaluate(q, {"q1": "yes", "q2": 3}, {})
        assert isinstance(action, GotoAction)
        assert action.qid == ["fallback"]
