import React from "react";

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
            
            <div style={{ marginBottom: '10px' }}>
                <select
                    value={ruleType}
                    onChange={e => setRuleType(e.target.value as "trigger" | "suppress")}
                    disabled={loading}
                    style={{
                        width: '100%',
                        background: '#0d0d1a',
                        border: `1px solid ${ruleType === 'trigger' ? 'rgba(46,213,115,0.3)' : 'rgba(255,100,100,0.3)'}`,
                        borderRadius: '8px',
                        color: ruleType === 'trigger' ? 'rgb(46,213,115)' : 'rgba(255,100,100,0.9)',
                        padding: '10px 14px',
                        fontSize: '13px',
                        fontWeight: 600,
                        cursor: 'pointer',
                        outline: 'none',
                    }}
                >
                    <option value="trigger">🔔 Alert — trigger an alert when this happens</option>
                    <option value="suppress">🔕 No Alert — suppress alerts for this</option>
                </select>
            </div>
            
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
