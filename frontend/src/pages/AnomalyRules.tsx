import React, { useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";

const INITIAL_RULES = [
    { id: 'RULE-01', name: 'Loitering Detection', desc: 'Triggers when a person remains stationary in a restricted zone for more than 30 seconds without authorization.', active: true },
    { id: 'RULE-02', name: 'Crowd Density Alert', desc: 'Activates when crowd density exceeds the maximum capacity threshold of 15 persons per monitored zone.', active: true },
    { id: 'RULE-03', name: 'Perimeter Breach', desc: 'Detects unauthorized crossing of defined perimeter boundaries during restricted access hours.', active: false },
    { id: 'RULE-04', name: 'Abandoned Object', desc: 'Identifies unattended objects left stationary for more than 2 minutes in high-traffic areas.', active: true },
    { id: 'RULE-05', name: 'Tailgating Detection', desc: 'Flags instances where multiple individuals pass through a secured checkpoint within a single authorization event.', active: false },
    { id: 'RULE-06', name: 'Facial Recognition Miss', desc: 'Alerts when an unrecognized face attempts access to Level 3 or above security clearance zones.', active: true },
];

export default function AnomalyRules() {
    const [rules, setRules] = useState(INITIAL_RULES);
    const [ruleInput, setRuleInput] = useState("");

    const activeCount = rules.filter(r => r.active).length;
    const inactiveCount = rules.length - activeCount;
    const totalCount = rules.length;

    const toggleRule = (idx: number) => {
        const newRules = [...rules];
        newRules[idx].active = !newRules[idx].active;
        setRules(newRules);
    };

    const deleteRule = (idx: number) => {
        const newRules = [...rules];
        newRules.splice(idx, 1);
        setRules(newRules);
    };

    const addRule = () => {
        const name = ruleInput.trim();
        if (!name) return;
        const newId = 'RULE-' + String(rules.length + 1).padStart(2, '0');
        setRules([{
            id: newId,
            name,
            desc: 'Custom anomaly detection rule. Configure thresholds and alert conditions in the settings panel.',
            active: true
        }, ...rules]);
        setRuleInput('');
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') addRule();
    };

    return (
        <DashboardLayout>
            <div className="anomaly-rules-page page-bg-grid">
                <div className="co tl"></div><div className="co tr"></div>
                <div className="co bl"></div><div className="co br"></div>

                {/* LEFT PANEL */}
                <div className="left-panel">
                    <h1 className="welcome-heading">Welcome <span>back</span></h1>
                    <p className="welcome-desc">
                        <strong>Anomaly Rules Engine.</strong> Define, configure and manage behavioral detection rules for your surveillance zones. Each rule triggers automated alerts when thresholds are exceeded.
                    </p>

                    <div className="stats">
                        <div className="stat">
                            <div className="stat-num">{totalCount}</div>
                            <div className="stat-label">Total Rules</div>
                        </div>
                        <div className="stat">
                            <div className="stat-num" style={{ color: 'rgb(46,213,115)' }}>{activeCount}</div>
                            <div className="stat-label">Active</div>
                        </div>
                        <div className="stat">
                            <div className="stat-num" style={{ color: 'rgba(255,100,100,0.8)' }}>{inactiveCount}</div>
                            <div className="stat-label">Inactive</div>
                        </div>
                    </div>

                    <div className="section-label">Add New Rule</div>
                    <div className="add-row">
                        <input
                            className="inp"
                            type="text"
                            placeholder="Enter anomaly rule"
                            value={ruleInput}
                            onChange={e => setRuleInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                        />
                        <div className="btn-wrapper">
                            <button className="custom-btn" onClick={addRule}>
                                <span className="btn-txt">Add</span>
                            </button>
                            <div className="dot"></div>
                        </div>
                    </div>
                </div>

                {/* RIGHT PANEL */}
                <div className="right-panel">
                    <div className="right-header">
                        <span className="right-title">Anomaly Rules</span>
                        <span className="count-badge">{totalCount} rules configured</span>
                    </div>

                    <div className="rule-grid">
                        {rules.map((rule, idx) => (
                            <div key={idx} className={`rule-card ${rule.active ? 'active-card' : 'inactive-card'}`}>
                                <div className="card-bar">
                                    <div className="card-bar-left">
                                        <span className={`pulse ${rule.active ? '' : 'red'}`}></span>
                                        <span className="card-id">{rule.id}</span>
                                    </div>
                                    <div className="card-bar-btns">
                                        <button
                                            className={`toggle-btn ${rule.active ? 'is-active' : 'is-inactive'}`}
                                            onClick={() => toggleRule(idx)}
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
                                        <button className="del-btn" onClick={() => deleteRule(idx)} title="Delete rule">
                                            <svg width="11" height="11" viewBox="0 0 14 14" fill="none">
                                                <path d="M2 3.5h10M5.5 3.5V2.5a.5.5 0 0 1 .5-.5h2a.5.5 0 0 1 .5.5v1M12 3.5l-.8 8a1 1 0 0 1-1 .9H3.8a1 1 0 0 1-1-.9L2 3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                                            </svg>
                                        </button>
                                    </div>
                                </div>
                                <div className="card-body">
                                    <div className="card-heading">{rule.name}</div>
                                    <div className="card-desc">{rule.desc}</div>

                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </DashboardLayout>
    );
}
