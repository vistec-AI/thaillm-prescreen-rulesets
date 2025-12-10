from typing import List, Optional, Set

from pydantic import ValidationError

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
    "not_contains",
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


def _get_question_from_trees(qid: str, opd_list: List[dict], oldcarts_list: List[dict]) -> Optional[Question]:
    """Get a question by qid from either OPD or oldcarts trees."""
    for q_dict in opd_list:
        if q_dict["qid"] == qid:
            q_cls = question_mapper[q_dict["question_type"]]
            try:
                return q_cls(**q_dict)
            except ValidationError as e:
                print(f"Failed to parse\n\n{q_dict}")
                raise e
            
    for q_dict in oldcarts_list:
        if q_dict["qid"] == qid:
            q_cls = question_mapper[q_dict["question_type"]]
            try:
                return q_cls(**q_dict)
            except ValidationError as e:
                print(f"Failed to parse\n\n{q_dict}")
                raise e
    return None


def _number_range_predicates_cover_all(preds: list) -> bool:
    """
    Check if numeric predicates cover all possible values.
    
    Common patterns that cover all cases:
    - ge(X) and lt(X) - covers >=X and <X
    - gt(X) and le(X) - covers >X and <=X
    - ge(X) and le(Y) where X > Y is impossible, so just check complementary ops
    """
    ops = {pred.op for pred in preds}
    values_by_op = {}
    for pred in preds:
        if pred.op not in values_by_op:
            values_by_op[pred.op] = set()
        values_by_op[pred.op].add(pred.value)
    
    # Check for complementary patterns
    # Pattern 1: ge(X) and lt(X) - covers all
    if "ge" in ops and "lt" in ops:
        ge_values = values_by_op.get("ge", set())
        lt_values = values_by_op.get("lt", set())
        # If any ge value equals any lt value, it's a complete partition
        if ge_values & lt_values:
            return True
    
    # Pattern 2: gt(X) and le(X) - covers all
    if "gt" in ops and "le" in ops:
        gt_values = values_by_op.get("gt", set())
        le_values = values_by_op.get("le", set())
        if gt_values & le_values:
            return True
    
    # Pattern 3: ge(X) and lt(Y) where Y > X covers [X, Y), need another rule for rest
    # Pattern 4: Multiple ranges that together cover min to max
    # These are complex to verify, skip for now
    
    return False


def _conditional_needs_default(cond_q: ConditionalQuestion, opd_list: List[dict], oldcarts_list: List[dict]) -> bool:
    """
    Check if a conditional question needs a default action.
    
    Rules:
    - For single_select/image_single_select: need default if NOT all options are covered by 'eq' predicates
    - For multi_select/image_multi_select: does NOT require default (combinations are too complex to enumerate)
    - For number_range: need default unless predicates form a complete partition (e.g., >=X and <X)
    - If rules reference both types, check single_select coverage first
    - Other types (free_text, etc.) require default since they can't be enumerated
    """
    if len(cond_q.rules) == 0:
        return True  # No rules means we need a default
    
    # Collect all predicates from all rules
    all_predicates = []
    for rule in cond_q.rules:
        all_predicates.extend(rule.when)
    
    # Group predicates by referenced qid
    predicates_by_qid: dict = {}
    for pred in all_predicates:
        if pred.qid not in predicates_by_qid:
            predicates_by_qid[pred.qid] = []
        predicates_by_qid[pred.qid].append(pred)
    
    # Check each referenced question
    for ref_qid, preds in predicates_by_qid.items():
        ref_q = _get_question_from_trees(ref_qid, opd_list, oldcarts_list)
        if ref_q is None:
            return True  # Can't find referenced question, need default
        
        # Single-select style questions: check if all options are covered
        if isinstance(ref_q, (SingleSelectQuestion, ImageSelectQuestion)):
            # Collect values checked with 'eq' operator for this question
            eq_values = {pred.value for pred in preds if pred.op == "eq"}
            option_ids = {opt.id for opt in ref_q.options}
            option_labels = {opt.label for opt in ref_q.options}
            
            # Check if all option ids OR all option labels are covered
            all_ids_covered = option_ids <= eq_values
            all_labels_covered = option_labels <= eq_values
            
            if not (all_ids_covered or all_labels_covered):
                return True  # Not all options covered, need default
        
        elif isinstance(ref_q, (MultiSelectQuestion, ImageMultiSelectQuestion)):
            # Multi-select doesn't require default - continue checking other questions
            pass
        
        elif isinstance(ref_q, NumberRangeQuestion):
            # Number range: check if predicates form a complete partition
            if not _number_range_predicates_cover_all(preds):
                return True  # Not a complete partition, need default
        
        else:
            # Other types (free_text, age_filter, gender_filter, etc.)
            # These can't be fully enumerated or have complex semantics, need default
            return True
    
    # All conditions are covered
    return False


def _get_opd_question(symptom_tree: List[dict], qid: str) -> Question:
    for q_dict in symptom_tree:
        if q_dict["qid"] == qid:
            q_cls = question_mapper[q_dict["question_type"]]
            try:
                return q_cls(**q_dict)
            except ValidationError as e:
                print(f"Failed to parse\n\n{q_dict}")
                raise e
    raise ValueError(f"Cannot find OPD qid {qid}")


def _opd_goto_targets(question: Question) -> Set[str]:
    targets: Set[str] = set()
    if isinstance(question, (AgeFilterQuestion, GenderQuestion, SingleSelectQuestion)):
        for opt in question.options:
            if opt.action.action == "goto":
                targets.update(opt.action.qid)
    elif isinstance(question, NumberRangeQuestion):
        if question.on_submit.action == "goto":
            targets.update(question.on_submit.qid)
    elif isinstance(question, ConditionalQuestion):
        for rule in question.rules:
            if rule.then.action == "goto":
                targets.update(rule.then.qid)
        if question.default is not None and question.default.action == "goto":
            targets.update(question.default.qid)
    return targets


def _traverse_opd_reachable(symptom_tree: List[dict]) -> Set[str]:
    if len(symptom_tree) == 0:
        return set()
    # start from the first node in the list
    root_q_dict = symptom_tree[0]
    q_cls = question_mapper[root_q_dict["question_type"]]
    try:
        root: Question = q_cls(**root_q_dict)
    except ValidationError as e:
        print(f"Failed to parse\n\n{root_q_dict}")
        raise e
    
    visited: Set[str] = {root.qid}
    stack: List[str] = [root.qid]

    while stack:
        current_qid = stack.pop()
        current_q = _get_opd_question(symptom_tree, current_qid)
        for nxt in _opd_goto_targets(current_q):
            if nxt not in visited:
                visited.add(nxt)
                stack.append(nxt)
    return visited


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
                # check if default action is needed based on rule coverage
                oldcarts_list = rules["oldcarts"].get(symptom, [])
                needs_default = _conditional_needs_default(question, q_list, oldcarts_list)
                if needs_default:
                    assert question.default is not None, f"Conditional {question.qid} has no default action (rules don't cover all cases)"
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
            try:
                question: Question = q_cls(**q_dict)
            except ValidationError as e:
                print(f"Failed to parse\n\n{q_dict}")
                raise e
            

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


def test_opd_all_questions_reachable_from_entry():
    """Ensure there are no unreachable OPD questions (except the first node which has no incoming edge by design)."""
    rules = load_rules()
    for symptom, q_list in rules["opd"].items():
        if len(q_list) == 0:
            continue
        all_qids = {q["qid"] for q in q_list}
        reachable = _traverse_opd_reachable(q_list)
        unreachable = all_qids - reachable
        assert len(unreachable) == 0, f"In OPD {symptom}, unreachable qids: {sorted(unreachable)}"


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
            try:
                question: ConditionalQuestion = q_cls(**q_dict)
            except ValidationError as e:
                print(f"Failed to parse\n\n{q_dict}")
                raise e
            
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
            try:
                oldcarts_map[qd["qid"]] = q_cls(**qd)
            except ValidationError as e:
                print(f"Failed to parse\n\n{qd}")
                raise e

        opd_map = {}
        for qd in opd_list:
            q_cls = question_mapper[qd["question_type"]]
            opd_map[qd["qid"]] = q_cls(**qd)

        # validate each conditional in OPD
        for qd in opd_list:
            if qd["question_type"] != "conditional":
                continue
            q_cls = question_mapper["conditional"]

            try:
                cond_q: ConditionalQuestion = q_cls(**qd)
            except ValidationError as e:
                print(f"Failed to parse\n\n{qd}")
                raise e

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
                        assert pred.op in {"contains", "not_contains", "contains_any", "contains_all"}, f"Invalid op {pred.op} for multi-select {ref_q.qid} in {cond_q.qid}"
                        valid = {*(opt.id for opt in ref_q.options), *(opt.label for opt in ref_q.options)}
                        if pred.op == "contains":
                            if isinstance(pred.value, list):
                                assert len(pred.value) > 0, f"Empty list value for contains on {ref_q.qid} in {cond_q.qid}"
                                assert all(v in valid for v in pred.value), f"Some values {pred.value} not in options for {ref_q.qid} in {cond_q.qid}"
                            else:
                                assert isinstance(pred.value, str), f"Value must be str or list for contains on {ref_q.qid} in {cond_q.qid}"
                                assert pred.value in valid, f"Value {pred.value} not in options for {ref_q.qid} in {cond_q.qid}"
                        elif pred.op == "not_contains":
                            if isinstance(pred.value, list):
                                assert len(pred.value) > 0, f"Empty list value for not_contains on {ref_q.qid} in {cond_q.qid}"
                                assert all(v in valid for v in pred.value), f"Some values {pred.value} not in options for {ref_q.qid} in {cond_q.qid}"
                            else:
                                assert isinstance(pred.value, str), f"Value must be str or list for not_contains on {ref_q.qid} in {cond_q.qid}"
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