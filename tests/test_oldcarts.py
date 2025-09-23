from typing import List, Optional, Set

from helpers.loader import load_rules, load_constants
from helpers.data_model.question import question_mapper, Question


constant = load_constants()


def test_load_rules():
    rules = load_rules()
    assert isinstance(rules, dict)
    assert all(k in rules for k in ["oldcarts", "opd"])


def test_oldcarts_schema():
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

    if question.question_type  in ["free_text", "free_text_with_fields", "number_range", "multi_select"]:
        action = question.on_submit if question.question_type != "multi_select" else question.next
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
