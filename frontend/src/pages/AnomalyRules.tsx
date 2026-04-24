import React, { useState, useEffect } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { apiGet, apiPost, apiDelete, apiPatch } from "@/lib/api";

import { ConflictModal } from "@/components/anomaly/ConflictModal";

export type ConflictRule = {
    rule_id: number;
    rule_text: string;
    rule_type: string;
    event_type: string;
    location: string;
    has_type_conflict: boolean;
};

export type PreviewResult = {
    parsed: any;
    conflicts: ConflictRule[];
    has_conflicts: boolean;
};

export default function AnomalyRules() {
    const [rules, setRules] = useState<any[]>([]);
    const [ruleInput, setRuleInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [reactivatingRuleId, setReactivatingRuleId] = useState<number | null>(null);

    // Conflict state
    const [preview, setPreview] = useState<PreviewResult | null>(null);
    const [showConflictModal, setShowConflictModal] = useState(false);
    const [selectedToDeactivate, setSelectedToDeactivate] = useState<number[]>([]);

    const activeCount = rules.filter(r => r.active).length;
    const inactiveCount = rules.length - activeCount;
    const totalCount = rules.length;

    const fetchRules = async () => {
        try {
            const data = await apiGet("/api/anomaly-rules");
            setRules(Array.isArray(data) ? data : []);
        } catch (e) {
            console.error("Error fetching rules:", e);
        }
    };

    useEffect(() => { fetchRules(); }, []);

    const toggleRule = async (idx: number) => {
        const rule = rules[idx];
        try {
            if (rule.active) {
                // Deactivate directly — no conflict check needed
                await apiPatch(`/api/anomaly-rules/${rule.rule_id}/deactivate`, {});
                await fetchRules();
            } else {
                // Reactivating — check for conflicts first
                const result = await apiPost<PreviewResult>(`/api/anomaly-rules/reactivate-preview/${rule.rule_id}`, {});
                if (result.has_conflicts) {
                    // Reuse same conflict modal
                    setPreview({
                        parsed: result.parsed,
                        conflicts: result.conflicts,
                        has_conflicts: true
                    });
                    setReactivatingRuleId(rule.rule_id);  // track which rule we're reactivating
                    setSelectedToDeactivate(result.conflicts.map((c: ConflictRule) => c.rule_id));
                    setShowConflictModal(true);
                } else {
                    await apiPatch(`/api/anomaly-rules/${rule.rule_id}/reactivate`, {});
                    await fetchRules();
                }
            }
        } catch (e) {
            console.error("Error toggling rule:", e);
        }
    };

    const deleteRule = async (idx: number) => {
        const rule = rules[idx];
        try {
            await apiDelete(`/api/anomaly-rules/${rule.rule_id}`);
            await fetchRules();
        } catch (e) {
            console.error("Error deleting rule:", e);
        }
    };

    // Step 1: preview before adding
    const addRule = async () => {
        const text = ruleInput.trim();
        if (!text) return;
        setLoading(true);
        try {
            const result = await apiPost<PreviewResult>("/api/anomaly-rules/preview", {
                rule_text: text
            });

            if (result.has_conflicts) {
                // Show conflict modal
                setPreview(result);
                setSelectedToDeactivate(result.conflicts.map(c => c.rule_id)); // default: deactivate all
                setShowConflictModal(true);
            } else {
                // No conflicts — add directly
                await apiPost("/api/anomaly-rules", { rule_text: text });
                setRuleInput('');
                await fetchRules();
            }
        } catch (e) {
            console.error("Error adding rule:", e);
        }
        setLoading(false);
    };
    const confirmResolve = async () => {
        if (!preview) return;
        setLoading(true);
        try {
            // Deactivate selected conflicting rules first
            for (const id of selectedToDeactivate) {
                await apiPatch(`/api/anomaly-rules/${id}/deactivate`, {});
            }

            if (reactivatingRuleId !== null) {
                // We were reactivating an existing rule
                await apiPatch(`/api/anomaly-rules/${reactivatingRuleId}/reactivate`, {});
            } else {
                // We were adding a new rule
                await apiPost("/api/anomaly-rules", { rule_text: ruleInput.trim() });
                setRuleInput('');
            }

            setShowConflictModal(false);
            setPreview(null);
            setSelectedToDeactivate([]);
            setReactivatingRuleId(null);
            await fetchRules();
        } catch (e) {
            console.error("Error resolving conflict:", e);
        }
        setLoading(false);
    };

    const cancelConflict = () => {
        setShowConflictModal(false);
        setPreview(null);
        setSelectedToDeactivate([]);
        setReactivatingRuleId(null);
    };

    const toggleDeactivate = (ruleId: number) => {
        setSelectedToDeactivate(prev =>
            prev.includes(ruleId)
                ? prev.filter(id => id !== ruleId)
                : [...prev, ruleId]
        );
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
                            disabled={loading}
                        />
                        <div className="btn-wrapper">
                            <button className="custom-btn" onClick={addRule} disabled={loading}>
                                <span className="btn-txt">{loading ? '...' : 'Add'}</span>
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
                            <div key={rule.rule_id || idx} className={`rule-card ${rule.active ? 'active-card' : 'inactive-card'}`}>
                                <div className="card-bar">
                                    <div className="card-bar-left">
                                        <span className={`pulse ${rule.active ? '' : 'red'}`}></span>
                                        <span className="card-id">RULE-{String(rule.rule_id).padStart(2, '0')}</span>
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
                                    <div className="card-heading">{rule.rule_text}</div>
                                    <div className="card-desc">
                                        Type: {rule.rule_type} · Event: {rule.event_type || '—'}
                                    </div>
                                </div>
                            </div>
                        ))}
                        {rules.length === 0 && !loading && (
                            <div style={{ color: 'gray', padding: '1rem' }}>No rules found.</div>
                        )}
                    </div>
                </div>
            </div>

            {/* CONFLICT MODAL */}
            {/* CONFLICT MODAL */}
            <ConflictModal
                show={showConflictModal}
                preview={preview}
                ruleInput={ruleInput}
                selectedToDeactivate={selectedToDeactivate}
                onToggleDeactivate={toggleDeactivate}
                onCancel={cancelConflict}
                onConfirm={confirmResolve}
            />
        </DashboardLayout>
    );
}