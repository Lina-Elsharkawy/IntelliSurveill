import React, { useState, useEffect } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { apiGet, apiPost, apiDelete, apiPatch } from "@/lib/api";

import { ConflictModal } from "@/components/anomaly/ConflictModal";
import { RuleCard } from "@/components/anomaly/RuleCard";
import { AddRuleForm } from "@/components/anomaly/AddRuleForm";
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
    duplicate?: ConflictRule;
    has_duplicate?: boolean;
};

export default function AnomalyRules() {
    const [rules, setRules] = useState<any[]>([]);
    const [ruleInput, setRuleInput] = useState("");
    const [ruleType, setRuleType] = useState<"trigger" | "suppress">("trigger");
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
                
                if (result.has_conflicts || result.has_duplicate) {
                    // Format the duplicate as a conflict to reuse the same modal
                    if (result.has_duplicate && result.duplicate) {
                        if (!result.conflicts) result.conflicts = [];
                        // Ensure we don't add it twice if it's already in conflicts
                        if (!result.conflicts.some(c => c.rule_id === result.duplicate!.rule_id)) {
                            result.conflicts.push(result.duplicate);
                        }
                        result.has_conflicts = true;
                    }

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
                rule_text: text,
                rule_type: ruleType
            });

            if (result.has_conflicts || result.has_duplicate) {
                // Format the duplicate as a conflict to reuse the same modal
                if (result.has_duplicate && result.duplicate) {
                    if (!result.conflicts) result.conflicts = [];
                    // Ensure we don't add it twice if it's already in conflicts
                    if (!result.conflicts.some(c => c.rule_id === result.duplicate!.rule_id)) {
                        result.conflicts.push(result.duplicate);
                    }
                    result.has_conflicts = true;
                }

                // Show conflict modal
                setPreview(result);
                setSelectedToDeactivate(result.conflicts.map(c => c.rule_id)); // default: deactivate all
                setShowConflictModal(true);
            } else {
                // No conflicts — add directly
                await apiPost("/api/anomaly-rules", { rule_text: text, rule_type: ruleType });
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
            if (reactivatingRuleId !== null) {
                // We were reactivating an existing rule, resolve it atomically
                await apiPost("/api/anomaly-rules/resolve-and-reactivate", {
                    rule_id: reactivatingRuleId,
                    deactivate_rule_ids: selectedToDeactivate
                });
            } else {
                // We were adding a new rule, resolve it atomically
                await apiPost("/api/anomaly-rules/resolve-and-add", {
                    rule_text: ruleInput.trim(),
                    rule_type: ruleType,
                    deactivate_rule_ids: selectedToDeactivate
                });
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

                    <AddRuleForm 
                        ruleInput={ruleInput}
                        setRuleInput={setRuleInput}
                        ruleType={ruleType}
                        setRuleType={setRuleType}
                        loading={loading}
                        onAddRule={addRule}
                    />
                </div>

                {/* RIGHT PANEL */}
                <div className="right-panel">
                    <div className="right-header">
                        <span className="right-title">Anomaly Rules</span>
                        <span className="count-badge">{totalCount} rules configured</span>
                    </div>

                    <div className="rule-grid">
                        {rules.map((rule, idx) => (
                            <RuleCard 
                                key={rule.rule_id || idx}
                                rule={rule}
                                onToggle={() => toggleRule(idx)}
                                onDelete={() => deleteRule(idx)}
                            />
                        ))}
                        {rules.length === 0 && !loading && (
                            <div style={{ color: 'gray', padding: '1rem' }}>No rules found.</div>
                        )}
                    </div>
                </div>
            </div>

            {/* CONFLICT MODAL */}
            <ConflictModal
                show={showConflictModal}
                preview={preview}
                ruleInput={reactivatingRuleId !== null ? (rules.find(r => r.rule_id === reactivatingRuleId)?.rule_text || "") : ruleInput}
                isReactivating={reactivatingRuleId !== null}
                selectedToDeactivate={selectedToDeactivate}
                onToggleDeactivate={toggleDeactivate}
                onCancel={cancelConflict}
                onConfirm={confirmResolve}
            />
        </DashboardLayout>
    );
}