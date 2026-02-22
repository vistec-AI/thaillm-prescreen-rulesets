"use client";

import ActionEditor, { type ActionObj } from "./ActionEditor";
import PredicateEditor, { type PredicateObj } from "./PredicateEditor";

/** Shape of a single rule in the conditional question's `rules` array. */
export interface RuleObj {
  when?: PredicateObj[];
  then?: ActionObj;
}

interface Props {
  rules: RuleObj[];
  defaultAction: ActionObj | null;
  onChange: (rules: RuleObj[], defaultAction: ActionObj | null) => void;
  disabled?: boolean;
  source?: string;
}

/**
 * Edits the full `rules[]` array + optional `default` action for a
 * conditional question type.
 *
 * Each rule has a `when` array of predicates (all must match) and a `then`
 * action. Rules are evaluated top-to-bottom — first match wins — so order
 * matters and the editor provides move up/down buttons.
 */
export default function RulesEditor({
  rules,
  defaultAction,
  onChange,
  disabled,
  source,
}: Props) {
  // --- Rule-level operations ---

  const updateRule = (index: number, updated: RuleObj) => {
    const newRules = rules.map((r, i) => (i === index ? updated : r));
    onChange(newRules, defaultAction);
  };

  const addRule = () => {
    const newRule: RuleObj = {
      when: [{ qid: "", op: "eq", value: "" }],
      then: { action: "goto", qid: [] },
    };
    onChange([...rules, newRule], defaultAction);
  };

  const removeRule = (index: number) => {
    onChange(rules.filter((_, i) => i !== index), defaultAction);
  };

  const moveRule = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= rules.length) return;
    const newRules = [...rules];
    [newRules[index], newRules[target]] = [newRules[target], newRules[index]];
    onChange(newRules, defaultAction);
  };

  // --- Predicate operations within a rule ---

  const updatePredicate = (ruleIndex: number, predIndex: number, pred: PredicateObj) => {
    const rule = rules[ruleIndex];
    const newWhen = (rule.when || []).map((p, i) => (i === predIndex ? pred : p));
    updateRule(ruleIndex, { ...rule, when: newWhen });
  };

  const addPredicate = (ruleIndex: number) => {
    const rule = rules[ruleIndex];
    const newWhen = [...(rule.when || []), { qid: "", op: "eq", value: "" }];
    updateRule(ruleIndex, { ...rule, when: newWhen });
  };

  const removePredicate = (ruleIndex: number, predIndex: number) => {
    const rule = rules[ruleIndex];
    const newWhen = (rule.when || []).filter((_, i) => i !== predIndex);
    updateRule(ruleIndex, { ...rule, when: newWhen });
  };

  // --- Rule action ---

  const updateRuleAction = (ruleIndex: number, action: ActionObj) => {
    updateRule(ruleIndex, { ...rules[ruleIndex], then: action });
  };

  // --- Default action toggle ---

  const handleDefaultToggle = (checked: boolean) => {
    if (checked) {
      onChange(rules, { action: "goto", qid: [] });
    } else {
      onChange(rules, null);
    }
  };

  return (
    <div className="space-y-1.5">
      <label className="text-xs font-semibold block">Rules</label>

      {rules.map((rule, ruleIdx) => (
        <div
          key={ruleIdx}
          className="border border-gray-200 rounded p-1.5 bg-gray-50"
        >
          {/* Rule header with index and move/remove controls */}
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] font-semibold text-gray-600">
              Rule {ruleIdx + 1}
            </span>
            <div className="flex items-center gap-0.5">
              <button
                type="button"
                className="text-gray-400 hover:text-gray-600 text-xs px-1 disabled:opacity-30"
                onClick={() => moveRule(ruleIdx, -1)}
                disabled={disabled || ruleIdx === 0}
                title="Move up"
              >
                ↑
              </button>
              <button
                type="button"
                className="text-gray-400 hover:text-gray-600 text-xs px-1 disabled:opacity-30"
                onClick={() => moveRule(ruleIdx, 1)}
                disabled={disabled || ruleIdx === rules.length - 1}
                title="Move down"
              >
                ↓
              </button>
              <button
                type="button"
                className="text-red-400 hover:text-red-600 text-sm px-1 disabled:opacity-30"
                onClick={() => removeRule(ruleIdx)}
                disabled={disabled}
                title="Remove rule"
              >
                &times;
              </button>
            </div>
          </div>

          {/* When: list of predicates (all must match) */}
          <div className="mb-1">
            <label className="text-[11px] text-gray-500 block mb-0.5">
              When (all must match):
            </label>
            <div className="space-y-1">
              {(rule.when || []).map((pred, predIdx) => (
                <PredicateEditor
                  key={predIdx}
                  value={pred}
                  onChange={(p) => updatePredicate(ruleIdx, predIdx, p)}
                  onRemove={() => removePredicate(ruleIdx, predIdx)}
                  disabled={disabled}
                />
              ))}
            </div>
            <button
              type="button"
              className="mt-1 px-2 py-0.5 text-xs bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50"
              onClick={() => addPredicate(ruleIdx)}
              disabled={disabled}
            >
              + Add Condition
            </button>
          </div>

          {/* Then: action editor */}
          <div>
            <label className="text-[11px] font-semibold block mb-0.5">Then</label>
            {rule.then ? (
              <ActionEditor
                value={rule.then}
                onChange={(a) => updateRuleAction(ruleIdx, a)}
                disabled={disabled}
                source={source}
              />
            ) : (
              <ActionEditor
                value={{ action: "goto", qid: [] }}
                onChange={(a) => updateRuleAction(ruleIdx, a)}
                disabled={disabled}
                source={source}
              />
            )}
          </div>
        </div>
      ))}

      {/* Add rule button */}
      <button
        type="button"
        className="w-full border border-dashed border-gray-300 rounded py-1 text-xs text-gray-500 hover:border-blue-400 hover:text-blue-600 disabled:opacity-30"
        onClick={addRule}
        disabled={disabled}
      >
        + Add Rule
      </button>

      {/* Default action section */}
      <div className="mt-1.5">
        <label className="text-xs font-semibold flex items-center gap-1.5 mb-0.5">
          <input
            type="checkbox"
            checked={defaultAction !== null}
            onChange={(e) => handleDefaultToggle(e.target.checked)}
            disabled={disabled}
          />
          Has default action
        </label>
        {defaultAction && (
          <ActionEditor
            value={defaultAction}
            onChange={(a) => onChange(rules, a)}
            disabled={disabled}
            source={source}
          />
        )}
      </div>
    </div>
  );
}
