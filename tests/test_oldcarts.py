from typing import List, Optional, Set

from helpers.loader import load_rules, load_constants
from helpers.utils import find_repo_root, load_yaml
from helpers.data_model.question import question_mapper, Question
from helpers.data_model.question import (
    FreeTextQuestion,
    FreeTextWithFieldQuestion,
    NumberRangeQuestion,
    SingleSelectQuestion,
    MultiSelectQuestion,
    ImageSelectQuestion,
    ImageMultiSelectQuestion,
    ConditionalQuestion,
)
from pathlib import Path


constant = load_constants()
# Load severity levels from local files (HF-hosted version may lack 'id' fields)
_const_dir = find_repo_root() / "v1" / "const"
_local_severity_levels = load_yaml(_const_dir / "severity_levels.yaml")
# Reference sets for validating terminate metadata
_department_ids = {d["id"] for d in constant["departments"]}
_severity_ids = {s["id"] for s in _local_severity_levels}


def _get_question_from_tree(qid: str, q_list: List[dict]) -> Optional[Question]:
    """Get a question by qid from a question list."""
    for q_dict in q_list:
        if q_dict["qid"] == qid:
            q_cls = question_mapper[q_dict["question_type"]]
            return q_cls(**q_dict)
    return None


def _number_range_predicates_cover_all(preds: list) -> bool:
    """
    Check if numeric predicates cover all possible values.
    
    Common patterns that cover all cases:
    - ge(X) and lt(X) - covers >=X and <X
    - gt(X) and le(X) - covers >X and <=X
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
        if ge_values & lt_values:
            return True
    
    # Pattern 2: gt(X) and le(X) - covers all
    if "gt" in ops and "le" in ops:
        gt_values = values_by_op.get("gt", set())
        le_values = values_by_op.get("le", set())
        if gt_values & le_values:
            return True
    
    return False


def _conditional_needs_default(cond_q: ConditionalQuestion, q_list: List[dict]) -> bool:
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
        ref_q = _get_question_from_tree(ref_qid, q_list)
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


def test_load_rules():
    """Ensure rules loader returns mapping with oldcarts and opd keys."""
    rules = load_rules()
    assert isinstance(rules, dict)
    assert all(k in rules for k in ["oldcarts", "opd"])


def test_oldcarts_schema():
    """Validate oldcarts schema, qid format, and action constraints."""
    rules = load_rules()
    symptom_list = [c["name"] for c in constant["nhso_symptoms"]]
        
    for symptom in rules["oldcarts"]:
        assert symptom in symptom_list, f"Bad symptom name: {symptom}"
        assert isinstance(rules["oldcarts"][symptom], list), "Bad schema, value under symptom must be list"

        has_opd = False # state store whether question list has opd action or not
        for q in rules["oldcarts"][symptom]:
            qtype = q["question_type"]
            q_cls = question_mapper.get(qtype)

            # test if known qtype
            assert q_cls is not None, f"Unknown question type: {qtype}"

            # test if parsable
            try:
                parsed_question: Question = q_cls(**q)
            except Exception as e:
                raise Exception(f"Failed to parse object to {q_cls} with value:\n{q}\n\nError message: {str(e)}")
            
            # check qid format
            assert len(parsed_question.qid.split("_")) == 3, \
                f"qid {parsed_question.qid} does not follow `<symptom_id>_<oldcarts_id>_<qid>` format"
            
            # check if action is valid
            if parsed_question.question_type in ["free_text", "free_text_with_fields", "number_range", "multi_select"]:
                action = parsed_question.on_submit if parsed_question.question_type != "multi_select" else parsed_question.next

                # update has_opd state
                # also check if there's only one opd action exists
                if action.action == "opd":
                    assert not has_opd, f"Only 1 OPD is allowed for symptom {symptom}"
                    has_opd = True

                # check if referred action follows format
                elif action.action == "goto":
                    for goto_q in action.qid:
                        assert len(goto_q.split("_")) == 3, \
                            f"goto action from {parsed_question.qid}, qid {goto_q} does not follow `<symptom_id>_<oldcarts_id>_<qid>` format"

                # early termination: validate department/severity IDs
                elif action.action == "terminate":
                    for dept in action.department:
                        assert dept in _department_ids, f"Unknown department {dept} in {parsed_question.qid}"
                    for sev in action.severity:
                        assert sev in _severity_ids, f"Unknown severity {sev} in {parsed_question.qid}"

            elif parsed_question.question_type in ["single_select", "image_single_select", "gender_filter", "age_filter"]:
                for opt in parsed_question.options:
                    action = opt.action

                    # update has_opd state, don't check because single select is any
                    if action.action == "opd":
                        has_opd = True

                    # check if referred action follows format
                    elif action.action == "goto":
                        assert len(action.qid) > 0, f"Action from {parsed_question.qid} has no next state"
                        for goto_q in action.qid:
                            assert len(goto_q.split("_")) == 3, \
                                f"goto action from {parsed_question.qid}, qid {goto_q} does not follow `<symptom_id>_<oldcarts_id>_<qid>` format"

                    # early termination: validate department/severity IDs
                    elif action.action == "terminate":
                        for dept in action.department:
                            assert dept in _department_ids, f"Unknown department {dept} in {parsed_question.qid}"
                        for sev in action.severity:
                            assert sev in _severity_ids, f"Unknown severity {sev} in {parsed_question.qid}"

            elif isinstance(parsed_question, ConditionalQuestion):
                # check if default action is needed based on rule coverage
                needs_default = _conditional_needs_default(parsed_question, rules["oldcarts"][symptom])
                if needs_default:
                    assert parsed_question.default is not None, f"Conditional {parsed_question.qid} has no default action (rules don't cover all cases)"

                # validate default action
                if parsed_question.default is not None:
                    if parsed_question.default.action == "opd":
                        has_opd = True
                    elif parsed_question.default.action == "terminate":
                        for dept in parsed_question.default.department:
                            assert dept in _department_ids, f"Unknown department {dept} in {parsed_question.qid} default"
                        for sev in parsed_question.default.severity:
                            assert sev in _severity_ids, f"Unknown severity {sev} in {parsed_question.qid} default"

                # validate rules
                for rule in parsed_question.rules:
                    if rule.then.action == "opd":
                        has_opd = True
                    elif rule.then.action == "goto":
                        assert len(rule.then.qid) > 0, f"Rule action from {parsed_question.qid} has no next state"
                        for goto_q in rule.then.qid:
                            assert len(goto_q.split("_")) == 3, \
                                f"goto action from {parsed_question.qid}, qid {goto_q} does not follow `<symptom_id>_<oldcarts_id>_<qid>` format"
                    elif rule.then.action == "terminate":
                        for dept in rule.then.department:
                            assert dept in _department_ids, f"Unknown department {dept} in {parsed_question.qid}"
                        for sev in rule.then.severity:
                            assert sev in _severity_ids, f"Unknown severity {sev} in {parsed_question.qid}"

        # oldcards must have at least 1 opd
        assert has_opd, f"Symptom {symptom} must have at least one OPD action"


def get_question(symptom_tree: List[Question], qid: str) -> Question:
    for q_dict in symptom_tree:
        if q_dict["qid"] == qid:
            q_cls = question_mapper[q_dict["question_type"]]
            return q_cls(**q_dict)
    raise ValueError(f"Cannot find qid {qid}")


def recursive_traverse(
    symptom_tree: List[Question], 
    question: Optional[Question] = None, 
    qid_pools: Optional[Set[str]] = None
) -> Set[str]:
    """Recursively get all qid from the symptom tree"""
    if question is None:
        q_dict = symptom_tree[0]
        q_cls = question_mapper[q_dict["question_type"]]
        question = q_cls(**q_dict)
    
    if qid_pools is None:
        qid_pools = {question.qid}

    if question.question_type  in ["free_text", "free_text_with_fields", "number_range", "multi_select",  "image_multi_select"]:
        action = question.on_submit if question.question_type not in ["multi_select", "image_multi_select"] else question.next
        # base case: opd handoff or early termination both end traversal
        if action.action in ("opd", "terminate"):
            return qid_pools

        # recursive
        next_qid = action.qid[0] # get default value as first element
        qid_pools.add(next_qid)

        return recursive_traverse(
            symptom_tree=symptom_tree,
            question=get_question(symptom_tree, next_qid),
            qid_pools=qid_pools
        )
    elif question.question_type in ["single_select", "image_single_select", "gender_filter", "age_filter"]:
        possible_paths = set()
        for opt in question.options:
            action = opt.action

            # base: opd and terminate are leaf actions, only follow goto
            if action.action == "goto":
                next_qid = action.qid[0]
                possible_paths.add(next_qid)

        # fallback
        if len(possible_paths) == 0:
            return qid_pools

        for next_qid in possible_paths:
            # recursive
            qid_pools.add(next_qid)
            qid_pools.union(recursive_traverse(
                symptom_tree=symptom_tree,
                question=get_question(symptom_tree, next_qid),
                qid_pools=qid_pools
            ))
        return qid_pools
    elif question.question_type == "conditional":
        possible_paths = set()
        # collect all goto targets from rules (opd and terminate are leaf actions)
        for rule in question.rules:
            action = rule.then
            if action.action == "goto":
                for q in action.qid:
                    possible_paths.add(q)
        # include default goto if present
        if getattr(question, "default", None) is not None:
            default_action = question.default
            if default_action.action == "goto":
                for q in default_action.qid:
                    possible_paths.add(q)

        # fallback
        if len(possible_paths) == 0:
            return qid_pools

        for next_qid in possible_paths:
            # recursive
            qid_pools.add(next_qid)
            qid_pools.union(recursive_traverse(
                symptom_tree=symptom_tree,
                question=get_question(symptom_tree, next_qid),
                qid_pools=qid_pools
            ))
        return qid_pools
    else:
        raise ValueError(f"Oldcarts shouldn't have question type {question.question_type}")


def test_trace_qids():
    """Validate whether all qids were used"""
    rules = load_rules()
    for symptom in rules["oldcarts"]:
        # iterate over all possible tree and check if there's any node missing
        qid_pools = recursive_traverse(symptom_tree=rules["oldcarts"][symptom])

        if len(qid_pools) != len(rules["oldcarts"][symptom]):
            missing_qid = set([q["qid"] for q in rules["oldcarts"][symptom]]) - qid_pools
            raise Exception(f"In symptom {symptom}, Question id {missing_qid} was never referenced.")


def test_oldcarts_unique_qids_and_prefix_consistency():
    """Ensure qids are unique per symptom and share the same prefix."""
    rules = load_rules()
    for symptom, q_list in rules["oldcarts"].items():
        all_qids = [q["qid"] for q in q_list]
        # unique qids per symptom
        assert len(set(all_qids)) == len(all_qids), f"Duplicate qid detected in symptom {symptom}"

        # prefix consistency: first segment of qid should be the same for all questions under the symptom
        prefixes = {qid.split("_")[0] for qid in all_qids}
        assert len(prefixes) == 1, f"Multiple qid prefixes found in symptom {symptom}: {prefixes}"


def test_oldcarts_all_goto_targets_exist_and_nonempty():
    """Ensure all goto target qids are non-empty and exist within the symptom."""
    rules = load_rules()
    for symptom, q_list in rules["oldcarts"].items():
        qid_set = {q["qid"] for q in q_list}
        for q_dict in q_list:
            qtype = q_dict["question_type"]
            q_cls = question_mapper.get(qtype)
            question: Question = q_cls(**q_dict)

            # collect goto targets
            goto_targets: List[str] = []
            if isinstance(question, (FreeTextQuestion, FreeTextWithFieldQuestion, NumberRangeQuestion)):
                if question.on_submit.action == "goto":
                    assert len(question.on_submit.qid) > 0, f"Goto list empty for {question.qid}"
                    goto_targets.extend(question.on_submit.qid)
            elif isinstance(question, MultiSelectQuestion):
                if question.next.action == "goto":
                    assert len(question.next.qid) > 0, f"Goto list empty for {question.qid}"
                    goto_targets.extend(question.next.qid)
            elif isinstance(question, (SingleSelectQuestion, ImageSelectQuestion)):
                for opt in question.options:
                    if opt.action.action == "goto":
                        assert len(opt.action.qid) > 0, f"Option action goto empty list at {question.qid}"
                        goto_targets.extend(opt.action.qid)
            elif isinstance(question, ConditionalQuestion):
                for rule in question.rules:
                    if rule.then.action == "goto":
                        assert len(rule.then.qid) > 0, f"Rule action goto empty list at {question.qid}"
                        goto_targets.extend(rule.then.qid)
                if question.default is not None and question.default.action == "goto":
                    assert len(question.default.qid) > 0, f"Default action goto empty list at {question.qid}"
                    goto_targets.extend(question.default.qid)

            # verify targets exist
            for tgt in goto_targets:
                assert tgt in qid_set, f"In {symptom}, goto target {tgt} from {question.qid} does not exist"


def test_oldcarts_image_assets_exist():
    """Ensure all referenced image assets exist in v1/images."""
    rules = load_rules()
    repo_root = find_repo_root()
    images_dir = Path(repo_root) / "v1" / "images"
    for symptom, q_list in rules["oldcarts"].items():
        for q_dict in q_list:
            qtype = q_dict["question_type"]
            if qtype in ["image_single_select", "image_multi_select"]:
                image_name = q_dict.get("image")
                assert image_name, f"Missing image in {symptom}:{q_dict['qid']}"
                img_path = images_dir / image_name
                assert img_path.exists(), f"Missing image asset {image_name} for {symptom}:{q_dict['qid']}"


def test_oldcarts_options_nonempty_and_unique_ids():
    """Ensure options exist and have unique ids for selectable questions."""
    rules = load_rules()
    for symptom, q_list in rules["oldcarts"].items():
        for q_dict in q_list:
            qtype = q_dict["question_type"]
            q_cls = question_mapper.get(qtype)
            question: Question = q_cls(**q_dict)

            if isinstance(question, (SingleSelectQuestion, ImageSelectQuestion)):
                assert len(question.options) > 0, f"No options defined for {question.qid}"
                opt_ids = [opt.id for opt in question.options]
                assert len(set(opt_ids)) == len(opt_ids), f"Duplicate option id in {question.qid}"
            elif isinstance(question, (MultiSelectQuestion, ImageMultiSelectQuestion)):
                assert len(question.options) > 0, f"No options defined for {question.qid}"
                opt_ids = [opt.id for opt in question.options]
                assert len(set(opt_ids)) == len(opt_ids), f"Duplicate option id in {question.qid}"


def test_oldcarts_state_values_valid():
    """Ensure oldcarts_state extracted from qid is one of allowed states."""
    rules = load_rules()
    valid_states = {"o", "l", "d", "c", "a", "r", "t", "s", "as"}
    for symptom, q_list in rules["oldcarts"].items():
        for q_dict in q_list:
            qtype = q_dict["question_type"]
            q_cls = question_mapper.get(qtype)
            question: Question = q_cls(**q_dict)
            assert question.is_oldcarts is True, f"{question.qid} should be oldcarts"
            assert question.oldcarts_state in valid_states, f"{question.qid} has invalid oldcarts state {question.oldcarts_state}"
