import React from "react";

interface RuleCardProps {
    rule: {
        rule_id: number;
        rule_text: string;
        rule_type: string;
        event_type: string;
        active: boolean;
    };
    onToggle: () => void;
    onDelete: () => void;
}

export function RuleCard({ rule, onToggle, onDelete }: RuleCardProps) {
    return (
        <div className={`rule-card ${rule.active ? 'active-card' : 'inactive-card'}`}>
            <div className="card-bar">
                <div className="card-bar-left">
                    <span className={`pulse ${rule.active ? '' : 'red'}`}></span>
                    <span className="card-id">RULE-{String(rule.rule_id).padStart(2, '0')}</span>
                </div>
                <div className="card-bar-btns">
                    <button
                        className={`toggle-btn ${rule.active ? 'is-active' : 'is-inactive'}`}
                        onClick={onToggle}
                    >
                        <span className={`toggle-icon ${rule.active ? 'tick' : 'cross'}`}>
                            {rule.active ? (
                                <svg width="9" height="9" viewBox="0 0 12 12" fill="none">
                                    <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                            ) : (
                                <svg width="9" height="9" viewBox="0 0 12 12" fill="none">
                                    <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                                </svg>
                            )}
                        </span>
                        {rule.active ? 'Active' : 'Inactive'}
                    </button>
                    <button className="del-btn" onClick={onDelete} title="Delete rule">
                        <svg width="11" height="11" viewBox="0 0 14 14" fill="none">
                            <path d="M2 3.5h10M5.5 3.5V2.5a.5.5 0 0 1 .5-.5h2a.5.5 0 0 1 .5.5v1M12 3.5l-.8 8a1 1 0 0 1-1 .9H3.8a1 1 0 0 1-1-.9L2 3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                    </button>
                </div>
            </div>
            <div className="card-body">
                <div className="card-heading">{rule.rule_text}</div>
                <div className="card-desc">
                    Type: {rule.rule_type} · Event: {rule.event_type || '—'}
                </div>
            </div>
        </div>
    );
}
