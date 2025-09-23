from typing import List, Optional, Set

from helpers.loader import load_rules, load_constants
from helpers.data_model.question import question_mapper, Question


constant = load_constants()
_departments = [d["name"] for d in constant["departments"]] + ["Self-care / Observation"] # add special case for self care


def test_opd_schema():
    rules = load_rules()
    symptom_list = [c["name"] for c in constant["nhso_symptoms"]]
        
    for symptom in rules["opd"]:
        assert symptom in symptom_list, f"Bad symptom name: {symptom}"
        assert isinstance(rules["opd"][symptom], list), "Bad schema, value under symptom must be list"

        for q_dict in rules["opd"][symptom]:
            qtype = q_dict["question_type"]
            q_cls = question_mapper.get(qtype)

            # test if known qtype
            assert q_cls is not None, f"Unknown question type: {qtype}"

            # test if parsable
            try:
                question: Question = q_cls(**q_dict)
            except Exception as e:
                raise Exception(f"Failed to parse object to {q_cls} with value:\n{q_dict}\n\nError message: {str(e)}")
            
            # check qid format
            assert len(question.qid.split("_")) == 3 and "_opd_" in question.qid, \
                f"qid {question.qid} does not follow `<symptom_id>_opd_<qid>` format"
            
            # validate each question
            if question.question_type in ["age_filter", "gender_filter", "single_select"]:
                for opt in question.options:
                    # check termination
                    if opt.action.action == "terminate":
                        assert opt.action.department in _departments, f"Error parsing {question.qid} Unknown department {opt.action.department}"
                    # check if question id exists
                    elif opt.action.action == "goto":
                        pass
                    else:
                        raise Exception(f"Error parsing {question.qid} Unknown action {opt.action}")
            elif question.question_type in ["number_range"]:
                # check termination
                if question.on_submit.action == "terminate":
                    assert question.on_submit.department in _departments, f"Error parsing {question.qid} Unknown department {question.on_submit.department}"
                # check if question id exists
                elif question.on_submit.action == "goto":
                    pass
                else:
                    raise Exception(f"Error parsing {question.qid} Unknown action {opt.action}")
            elif question.question_type in ["conditional"]:
                for rule in question.rules:
                    # check termination
                    if rule.then.action == "terminate":
                        assert rule.then.department in _departments, f"Error parsing {question.qid} Unknown department {rule.then.department}"
                    elif rule.then.action == "goto":
                        pass
                    else:
                        raise Exception(f"Error parsing {question.qid} Unknown action {opt.action}")
                        

            else:
                raise Exception(f"Error parsing {question.qid} Type check {question.question_type} is not supported")
