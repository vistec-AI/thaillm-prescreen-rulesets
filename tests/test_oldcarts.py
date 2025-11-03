from typing import List, Optional, Set

from helpers.loader import load_rules, load_constants
from helpers.data_model.question import question_mapper, Question
from helpers.data_model.question import (
    FreeTextQuestion,
    FreeTextWithFieldQuestion,
    NumberRangeQuestion,
    SingleSelectQuestion,
    MultiSelectQuestion,
    ImageSelectQuestion,
    ImageMultiSelectQuestion,
)
from helpers.utils import find_repo_root
from pathlib import Path


constant = load_constants()


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

                # oldcarts must have no terminate action
                assert action.action != "terminate", "oldcarts question can't have terminate"

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
            elif parsed_question.question_type in ["single_select", "image_single_select", "gender_filter", "age_filter"]:
                for opt in parsed_question.options:
                    action = opt.action

                    # oldcarts must have no terminate action
                    assert action.action != "terminate", "oldcarts question can't have terminate"

                    # update has_opd state, don't check because single select is any
                    if action.action == "opd":
                        has_opd = True

                    # check if referred action follows format
                    elif action.action == "goto":
                        assert len(action.qid) > 0, f"Action from {parsed_question.qid} has no next state"
                        for goto_q in action.qid:
                            assert len(goto_q.split("_")) == 3, \
                                f"goto action from {parsed_question.qid}, qid {goto_q} does not follow `<symptom_id>_<oldcarts_id>_<qid>` format"

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
        # base case
        if action.action == "opd":
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

            # base
            if action.action != "opd":
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
        # collect all goto targets from rules
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
