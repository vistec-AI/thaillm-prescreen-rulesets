from __future__ import annotations
from typing import Any, Dict, List, Tuple


def build_oldcarts_graph(symptom: str, q_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    nodes = []
    edges = []

    # add nodes with metadata for drill-down
    for q_dict in q_list:
        data = {
            "id": q_dict["qid"],
            "label": q_dict["question"],
            "type": q_dict["question_type"],
            "raw": q_dict,
            "source": "oldcarts",
        }
        if q_dict["question_type"] in ["single_select", "image_single_select", "gender_filter", "age_filter"]:
            data["options"] = q_dict.get("options", [])
        if q_dict["question_type"] in ["multi_select", "image_multi_select"]:
            data["options"] = q_dict.get("options", [])
        if q_dict["question_type"] in ["number_range"]:
            for k in ["min_value", "max_value", "step", "default_value"]:
                if k in q_dict:
                    data[k] = q_dict.get(k)
        if q_dict["question_type"] in ["free_text_with_fields"]:
            data["fields"] = q_dict.get("fields", [])
        if q_dict["question_type"].startswith("image_"):
            img = q_dict.get("image")
            if img:
                data["image"] = f"/assets/{img}"
        nodes.append({"data": data})

    # add edges based on actions
    for q_dict in q_list:
        qtype = q_dict["question_type"]
        qid = q_dict["qid"]
        if qtype in ["free_text", "free_text_with_fields", "number_range"]:
            act = q_dict.get("on_submit", {})
            if act.get("action") == "goto":
                for tgt in act.get("qid", []):
                    edges.append({"data": {"source": qid, "target": tgt, "label": "goto"}})
            elif act.get("action") == "opd":
                edges.append({"data": {"source": qid, "target": f"{symptom}_OPD", "label": "opd"}})
        elif qtype in ["multi_select", "image_multi_select"]:
            act = q_dict.get("next", {})
            if act.get("action") == "goto":
                for tgt in act.get("qid", []):
                    edges.append({"data": {"source": qid, "target": tgt, "label": "goto"}})
            elif act.get("action") == "opd":
                edges.append({"data": {"source": qid, "target": f"{symptom}_OPD", "label": "opd"}})
        elif qtype in ["single_select", "image_single_select", "gender_filter", "age_filter"]:
            for opt in q_dict.get("options", []):
                act = opt.get("action", {})
                if act.get("action") == "goto":
                    for tgt in act.get("qid", []):
                        edges.append({"data": {"source": qid, "target": tgt, "label": opt.get("label", opt.get("id", ""))}})
                elif act.get("action") == "opd":
                    edges.append({"data": {"source": qid, "target": f"{symptom}_OPD", "label": opt.get("label", opt.get("id", ""))}})

    # add virtual OPD node
    nodes.append({"data": {"id": f"{symptom}_OPD", "label": "OPD", "type": "opd"}})
    return {"nodes": nodes, "edges": edges}


def build_opd_graph(symptom: str, q_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    nodes = []
    edges = []

    for q in q_list:
        data = {
            "id": q["qid"],
            "label": q["question"],
            "type": q["question_type"],
            "raw": q,
            "source": "opd",
        }
        if q["question_type"] in ["age_filter", "gender_filter", "single_select"]:
            data["options"] = q.get("options", [])
        if q["question_type"] in ["number_range"]:
            for k in ["min_value", "max_value", "step", "default_value"]:
                if k in q:
                    data[k] = q.get(k)
        if q["question_type"].startswith("image_"):
            img = q.get("image")
            if img:
                data["image"] = f"/assets/{img}"
        if q["question_type"] == "conditional":
            data["rules"] = q.get("rules", [])
            if q.get("default") is not None:
                data["default"] = q.get("default")
        nodes.append({"data": data})

    for q in q_list:
        qid = q["qid"]
        qt = q["question_type"]
        if qt in ["age_filter", "gender_filter", "single_select"]:
            for opt in q.get("options", []):
                act = opt.get("action", {})
                if act.get("action") == "goto":
                    for tgt in act.get("qid", []):
                        edges.append({"data": {"source": qid, "target": tgt, "label": opt.get("label", opt.get("id", ""))}})
                elif act.get("action") == "terminate":
                    depts = act.get("metadata", {}).get("department", [])
                    depts_list = depts if isinstance(depts, list) else ([depts] if depts else [])
                    for dept in depts_list:
                        edges.append({"data": {"source": qid, "target": f"{qid}_TERM_{dept}", "label": dept}})
                        nodes.append({"data": {"id": f"{qid}_TERM_{dept}", "label": dept, "type": "terminate"}})
        elif qt in ["number_range"]:
            act = q.get("on_submit", {})
            if act.get("action") == "goto":
                for tgt in act.get("qid", []):
                    edges.append({"data": {"source": qid, "target": tgt, "label": "goto"}})
            elif act.get("action") == "terminate":
                depts = act.get("metadata", {}).get("department", [])
                depts_list = depts if isinstance(depts, list) else ([depts] if depts else [])
                for dept in depts_list:
                    edges.append({"data": {"source": qid, "target": f"{qid}_TERM_{dept}", "label": dept}})
                    nodes.append({"data": {"id": f"{qid}_TERM_{dept}", "label": dept, "type": "terminate"}})
        elif qt == "conditional":
            for rule in q.get("rules", []):
                act = rule.get("then", {})
                cond = "; ".join([f"{w.get('qid')} {w.get('op')} {w.get('value')}" for w in rule.get("when", [])])
                if act.get("action") == "goto":
                    for tgt in act.get("qid", []):
                        edges.append({"data": {"source": qid, "target": tgt, "label": cond or "goto"}})
                elif act.get("action") == "terminate":
                    depts = act.get("metadata", {}).get("department", [])
                    depts_list = depts if isinstance(depts, list) else ([depts] if depts else [])
                    for dept in depts_list:
                        term_id = f"{qid}_TERM_{dept}"
                        edges.append({"data": {"source": qid, "target": term_id, "label": cond or dept}})
                        nodes.append({"data": {"id": term_id, "label": dept, "type": "terminate"}})
            if q.get("default"):
                act = q["default"]
                if act.get("action") == "goto":
                    for tgt in act.get("qid", []):
                        edges.append({"data": {"source": qid, "target": tgt, "label": "default"}})
                elif act.get("action") == "terminate":
                    depts = act.get("metadata", {}).get("department", [])
                    depts_list = depts if isinstance(depts, list) else ([depts] if depts else [])
                    for dept in depts_list:
                        term_id = f"{qid}_TERM_{dept}"
                        edges.append({"data": {"source": qid, "target": term_id, "label": "default"}})
                        nodes.append({"data": {"id": term_id, "label": dept, "type": "terminate"}})

    return {"nodes": nodes, "edges": edges}


def build_combined_graph(symptom: str, oldcarts: List[Dict[str, Any]], opd: List[Dict[str, Any]]) -> Dict[str, Any]:
    old_graph = build_oldcarts_graph(symptom, oldcarts)
    opd_graph = build_opd_graph(symptom, opd)

    # Merge nodes/edges and connect virtual OPD node to OPD entry nodes (heuristic: first OPD qid)
    nodes = old_graph["nodes"] + opd_graph["nodes"]
    edges = old_graph["edges"] + opd_graph["edges"]

    if len(opd) > 0:
        entry_qid = opd[0]["qid"]
        edges.append({"data": {"source": f"{symptom}_OPD", "target": entry_qid, "label": "-> OPD"}})

    return {"nodes": nodes, "edges": edges}


