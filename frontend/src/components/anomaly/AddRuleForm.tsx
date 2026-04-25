import React from "react";
import { RuleTypeToggle } from "./RuleTypeToggle";

interface AddRuleFormProps {
    ruleInput: string;
    setRuleInput: (val: string) => void;
    ruleType: "trigger" | "suppress";
    setRuleType: (val: "trigger" | "suppress") => void;
    loading: boolean;
    onAddRule: () => void;
}

export function AddRuleForm({
    ruleInput,
    setRuleInput,
    ruleType,
    setRuleType,
    loading,
    onAddRule
}: AddRuleFormProps) {
    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') onAddRule();
    };

    return (
        <div className="add-rule-section">
            <div className="section-label">Add New Rule</div>
            
            <div className="add-row">
                <input
                    className="inp"
                    type="text"
                    placeholder="Enter anomaly rule"
                    value={ruleInput}
                    onChange={e => setRuleInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    disabled={loading}
                />
                <RuleTypeToggle ruleType={ruleType} setRuleType={setRuleType} disabled={loading} />
                <div className="btn-wrapper">
                    <button className="custom-btn" onClick={onAddRule} disabled={loading}>
                        <span className="btn-txt">{loading ? '...' : 'Add'}</span>
                    </button>
                    <div className="dot"></div>
                </div>
            </div>
        </div>
    );
}
