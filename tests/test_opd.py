from typing import List, Optional, Set

from helpers.loader import load_rules, load_constants
from helpers.data_model.question import question_mapper, Question
from helpers.data_model.question import (
    AgeFilterQuestion,
    GenderQuestion,
    NumberRangeQuestion,
    SingleSelectQuestion,
    MultiSelectQuestion,
    ImageSelectQuestion,
    ImageMultiSelectQuestion,
    FreeTextQuestion,
    FreeTextWithFieldQuestion,
    ConditionalQuestion,
)


constant = load_constants()
_departments = [d["name"] for d in constant["departments"]] + ["Self-care / Observation"]
_allowed_ops = {
    "eq",
    "ne",
    "contains",
    "matches",
    "contains_any",
    "contains_all",
    "lt",
    "le",
    "gt",
    "ge",
    "between"
}


def _collect_qids_per_symptom(rules, section: str, symptom: str) -> Set[str]:
    return {q["qid"] for q in rules[section].get(symptom, [])}


def test_opd_schema_and_parsing():
    """Validate OPD schema, parsing, qid format, and per-type constraints."""
    rules = load_rules()
    symptom_list = [c["name"] for c in constant["nhso_symptoms"]]

    assert "opd" in rules and "oldcarts" in rules

    for symptom, q_list in rules["opd"].items():
        assert symptom in symptom_list, f"Bad symptom name: {symptom}"
        assert isinstance(q_list, list), "Bad schema, value under symptom must be list"

        for q_dict in q_list:
            qtype = q_dict.get("question_type")
            q_cls = question_mapper.get(qtype)
            assert q_cls is not None, f"Unknown question type: {qtype} in {symptom}"
            # parse
            try:
                question: Question = q_cls(**q_dict)
            except Exception as e:
                raise Exception(f"Failed to parse into {q_cls} for {symptom} with value:\n{q_dict}\n\nError: {str(e)}")

            # qid format
            parts = question.qid.split("_")
            assert len(parts) == 3 and "_opd_" in question.qid, f"Bad qid format {question.qid}"

            # type-specific validations
            if isinstance(question, (AgeFilterQuestion, GenderQuestion, SingleSelectQuestion)):
                assert len(question.options) > 0, f"No options for {question.qid}"
                opt_labels = [opt.label for opt in question.options]
                assert len(set(opt_labels)) == len(opt_labels), f"Duplicate option labels in {question.qid}"
                for opt in question.options:
                    if opt.action.action == "terminate":
                        for dept in opt.action.department:
                            assert dept in _departments, f"Unknown department {dept} in {question.qid}"
                    elif opt.action.action == "goto":
                        assert len(opt.action.qid) > 0, f"Empty goto in {question.qid}"
                    else:
                        raise AssertionError(f"Unknown action {opt.action.action} in {question.qid}")
            elif isinstance(question, NumberRangeQuestion):
                assert question.min_value < question.max_value, f"Invalid range in {question.qid}"
                if question.on_submit.action == "terminate":
                    assert question.on_submit.department in _departments, f"Unknown department {question.on_submit.department} in {question.qid}"
                elif question.on_submit.action == "goto":
                    assert len(question.on_submit.qid) > 0, f"Empty goto in {question.qid}"
                else:
                    raise AssertionError(f"Unknown action {question.on_submit.action} in {question.qid}")
            elif isinstance(question, ConditionalQuestion):
                # rules can be empty, but default should exist in that case
                if len(question.rules) == 0:
                    assert question.default is not None, f"Conditional {question.qid} has no rules and no default"
                # validate rules
                for rule in question.rules:
                    # when predicates
                    assert len(rule.when) > 0, f"Empty predicates in {question.qid}"
                    for pred in rule.when:
                        assert pred.op in _allowed_ops, f"Unknown op {pred.op} in {question.qid}"
                    # then action
                    if rule.then.action == "terminate":
                        for dept in rule.then.department:
                            assert dept in _departments, f"Unknown department {dept} in {question.qid}"
                    elif rule.then.action == "goto":
                        assert len(rule.then.qid) > 0, f"Empty goto in rule of {question.qid}"
                    else:
                        raise AssertionError(f"Unknown action {rule.then.action} in {question.qid}")
                # default action
                if question.default is not None:
                    if question.default.action == "terminate":
                        for dept in question.default.department:
                            assert dept in _departments, f"Unknown department {dept} in {question.qid}"
                    elif question.default.action == "goto":
                        assert len(question.default.qid) > 0, f"Empty default goto in {question.qid}"
                    else:
                        raise AssertionError(f"Unknown default action {question.default.action} in {question.qid}")
            else:
                raise AssertionError(f"Unsupported question class {type(question)} in OPD")


def test_opd_unique_qids_and_prefix_consistency():
    """Ensure OPD qids are unique per symptom and share the same prefix."""
    rules = load_rules()
    for symptom, q_list in rules["opd"].items():
        qids = [q["qid"] for q in q_list]
        assert len(set(qids)) == len(qids), f"Duplicate qid in OPD {symptom}"
        prefixes = {qid.split("_")[0] for qid in qids}
        assert len(prefixes) == 1, f"Multiple qid prefixes in OPD {symptom}: {prefixes}"


def test_opd_goto_targets_exist_within_opd():
    """Ensure all goto targets in OPD refer to existing OPD qids in the symptom."""
    rules = load_rules()
    for symptom, q_list in rules["opd"].items():
        opd_qids = _collect_qids_per_symptom(rules, "opd", symptom)
        for q_dict in q_list:
            q_cls = question_mapper[q_dict["question_type"]]
            question: Question = q_cls(**q_dict)

            targets: List[str] = []
            if isinstance(question, (AgeFilterQuestion, GenderQuestion, SingleSelectQuestion)):
                for opt in question.options:
                    if opt.action.action == "goto":
                        targets.extend(opt.action.qid)
            elif isinstance(question, NumberRangeQuestion):
                if question.on_submit.action == "goto":
                    targets.extend(question.on_submit.qid)
            elif isinstance(question, ConditionalQuestion):
                for rule in question.rules:
                    if rule.then.action == "goto":
                        targets.extend(rule.then.qid)
                if question.default is not None and question.default.action == "goto":
                    targets.extend(question.default.qid)

            for tgt in targets:
                assert tgt in opd_qids, f"In {symptom}, goto target {tgt} from {question.qid} does not exist in OPD"


def test_opd_predicates_reference_existing_oldcarts_or_opd_qids():
    """Ensure OPD conditional predicates reference existing qids in OPD/oldcarts."""
    rules = load_rules()
    for symptom, q_list in rules["opd"].items():
        opd_qids = _collect_qids_per_symptom(rules, "opd", symptom)
        oldcarts_qids = _collect_qids_per_symptom(rules, "oldcarts", symptom)
        known_qids = opd_qids.union(oldcarts_qids)

        for q_dict in q_list:
            if q_dict["question_type"] != "conditional":
                continue
            q_cls = question_mapper["conditional"]
            question: ConditionalQuestion = q_cls(**q_dict)
            for rule in question.rules:
                for pred in rule.when:
                    assert pred.qid in known_qids, f"Predicate {pred.qid} in {question.qid} not found in OPD or oldcarts for {symptom}"


def test_opd_conditional_predicate_semantics():
    """Validate conditional predicates use ops/values compatible with referenced question types."""
    rules = load_rules()
    for symptom, opd_list in rules["opd"].items():
        # build qid -> Question maps for both trees
        oldcarts_map = {}
        for qd in rules["oldcarts"].get(symptom, []):
            q_cls = question_mapper[qd["question_type"]]
            oldcarts_map[qd["qid"]] = q_cls(**qd)

        opd_map = {}
        for qd in opd_list:
            q_cls = question_mapper[qd["question_type"]]
            opd_map[qd["qid"]] = q_cls(**qd)

        # validate each conditional in OPD
        for qd in opd_list:
            if qd["question_type"] != "conditional":
                continue
            q_cls = question_mapper["conditional"]
            cond_q: ConditionalQuestion = q_cls(**qd)

            for rule in cond_q.rules:
                for pred in rule.when:
                    ref_q = opd_map.get(pred.qid) or oldcarts_map.get(pred.qid)
                    assert ref_q is not None, f"Referenced qid {pred.qid} not found for {cond_q.qid}"

                    # Age filter supports numeric comparisons and equality against options
                    if isinstance(ref_q, AgeFilterQuestion):
                        if pred.op in {"eq", "ne"}:
                            assert isinstance(pred.value, str), f"Value must be str for age_filter eq/ne on {ref_q.qid} in {cond_q.qid}"
                            valid = {*(opt.id for opt in ref_q.options), *(opt.label for opt in ref_q.options)}
                            assert pred.value in valid, f"Value {pred.value} not in options for {ref_q.qid} in {cond_q.qid}"
                        elif pred.op in {"lt", "le", "gt", "ge"}:
                            assert isinstance(pred.value, (int, float)), f"Numeric value required for age_filter {pred.op} on {ref_q.qid} in {cond_q.qid}"
                        else:
                            raise AssertionError(f"Invalid op {pred.op} for age_filter {ref_q.qid} in {cond_q.qid}")

                    # Single-choice style questions (no numeric comparisons)
                    elif isinstance(ref_q, (SingleSelectQuestion, ImageSelectQuestion, GenderQuestion)):
                        assert pred.op in {"eq", "ne"}, f"Invalid op {pred.op} for single-select {ref_q.qid} in {cond_q.qid}"
                        assert isinstance(pred.value, str), f"Value must be str for single-select {ref_q.qid} in {cond_q.qid}"
                        valid = {*(opt.id for opt in ref_q.options), *(opt.label for opt in ref_q.options)}
                        assert pred.value in valid, f"Value {pred.value} not in options for {ref_q.qid} in {cond_q.qid}"

                    # Multi-select style questions
                    elif isinstance(ref_q, (MultiSelectQuestion, ImageMultiSelectQuestion)):
                        assert pred.op in {"contains", "contains_any", "contains_all"}, f"Invalid op {pred.op} for multi-select {ref_q.qid} in {cond_q.qid}"
                        valid = {*(opt.id for opt in ref_q.options), *(opt.label for opt in ref_q.options)}
                        if pred.op == "contains":
                            if isinstance(pred.value, list):
                                assert len(pred.value) > 0, f"Empty list value for contains on {ref_q.qid} in {cond_q.qid}"
                                assert all(v in valid for v in pred.value), f"Some values {pred.value} not in options for {ref_q.qid} in {cond_q.qid}"
                            else:
                                assert isinstance(pred.value, str), f"Value must be str or list for contains on {ref_q.qid} in {cond_q.qid}"
                                assert pred.value in valid, f"Value {pred.value} not in options for {ref_q.qid} in {cond_q.qid}"
                        elif pred.op == "contains_any":
                            assert isinstance(pred.value, list) and len(pred.value) > 0, f"contains_any expects non-empty list on {ref_q.qid} in {cond_q.qid}"
                            assert any(v in valid for v in pred.value), f"None of values {pred.value} in options for {ref_q.qid} in {cond_q.qid}"
                        elif pred.op == "contains_all":
                            assert isinstance(pred.value, list) and len(pred.value) > 0, f"contains_all expects non-empty list on {ref_q.qid} in {cond_q.qid}"
                            assert all(v in valid for v in pred.value), f"Some values {pred.value} not in options for {ref_q.qid} in {cond_q.qid}"

                    # Numeric range questions
                    elif isinstance(ref_q, NumberRangeQuestion):
                        assert pred.op in {"lt", "le", "gt", "ge", "between", "eq", "ne"}, f"Invalid op {pred.op} for number-range {ref_q.qid} in {cond_q.qid}"
                        def _in_bounds(x: float) -> bool:
                            return ref_q.min_value <= float(x) <= ref_q.max_value
                        if pred.op == "between":
                            assert isinstance(pred.value, (list, tuple)) and len(pred.value) == 2, f"between expects [min,max] for {ref_q.qid} in {cond_q.qid}"
                            a, b = pred.value
                            for v in (a, b):
                                assert isinstance(v, (int, float)), f"between values must be numeric for {ref_q.qid} in {cond_q.qid}"
                                assert _in_bounds(v), f"between value {v} out of bounds for {ref_q.qid} in {cond_q.qid}"
                            assert a <= b, f"between range invalid (min>max) for {ref_q.qid} in {cond_q.qid}"
                        else:
                            assert isinstance(pred.value, (int, float)), f"Numeric op expects number for {ref_q.qid} in {cond_q.qid}"
                            assert _in_bounds(pred.value), f"Value {pred.value} out of bounds for {ref_q.qid} in {cond_q.qid}"

                    # Free text questions
                    elif isinstance(ref_q, FreeTextQuestion):
                        assert pred.op in {"eq", "ne", "contains", "matches"}, f"Invalid op {pred.op} for free_text {ref_q.qid} in {cond_q.qid}"
                        assert isinstance(pred.value, str), f"Value must be str for free_text {ref_q.qid} in {cond_q.qid}"

                    # Free text with fields questions
                    elif isinstance(ref_q, FreeTextWithFieldQuestion):
                        assert pred.op in {"eq", "ne", "contains", "matches"}, f"Invalid op {pred.op} for free_text_with_fields {ref_q.qid} in {cond_q.qid}"
                        assert isinstance(pred.value, str), f"Value must be str for free_text_with_fields {ref_q.qid} in {cond_q.qid}"
                        assert pred.field is not None, f"Field must be specified for free_text_with_fields {ref_q.qid} in {cond_q.qid}"
                        field_ids = {f.id for f in ref_q.fields}
                        assert pred.field in field_ids, f"Unknown field {pred.field} for {ref_q.qid} in {cond_q.qid}"

                    # Conditional questions should not be used as predicate sources
                    elif isinstance(ref_q, ConditionalQuestion):
                        raise AssertionError(f"Predicate references conditional question {ref_q.qid} in {cond_q.qid}")

                    else:
                        raise AssertionError(f"Unhandled referenced question type {type(ref_q)} for {pred.qid} in {cond_q.qid}")