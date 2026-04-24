import React from "react";
import { PreviewResult } from "@/pages/AnomalyRules";

interface ConflictModalProps {
    show: boolean;
    preview: PreviewResult | null;
    ruleInput: string;
    isReactivating?: boolean;
    selectedToDeactivate: number[];
    onToggleDeactivate: (ruleId: number) => void;
    onCancel: () => void;
    onConfirm: () => void;
}

export function ConflictModal({
    show,
    preview,
    ruleInput,
    isReactivating,
    selectedToDeactivate,
    onToggleDeactivate,
    onCancel,
    onConfirm
}: ConflictModalProps) {
    if (!show || !preview) return null;

    return (
        <div style={{
            position: 'fixed', inset: 0,
            background: 'rgba(0,0,0,0.85)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 9999
        }}>
            <div style={{
                background: '#1a1a2e',
                border: '1px solid rgba(255,100,100,0.4)',
                borderRadius: '16px',
                padding: '32px',
                width: '100%',
                maxWidth: '560px',
                maxHeight: '80vh',
                overflowY: 'auto'
            }}>
                {/* Header */}
                <div style={{ marginBottom: '20px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                        <span style={{ fontSize: '20px' }}>⚠️</span>
                        <h2 style={{ color: 'rgba(255,100,100,0.9)', margin: 0, fontSize: '18px', fontWeight: 700 }}>
                            Rule Conflict Detected
                        </h2>
                    </div>
                    <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: '13px', margin: 0 }}>
                        Your {isReactivating ? "reactivated rule" : "new rule"} conflicts with existing active rules. Choose which ones to deactivate.
                    </p>
                </div>

                {/* New rule preview */}
                <div style={{
                    background: 'rgba(46,213,115,0.08)',
                    border: '1px solid rgba(46,213,115,0.2)',
                    borderRadius: '10px',
                    padding: '14px',
                    marginBottom: '20px'
                }}>
                    <div style={{ color: 'rgba(46,213,115,0.8)', fontSize: '11px', fontWeight: 700, marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '1px' }}>
                        {isReactivating ? "Reactivating Rule" : "New Rule"}
                    </div>
                    <div style={{ color: 'rgba(255,255,255,0.9)', fontSize: '14px' }}>{ruleInput}</div>
                    <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '12px', marginTop: '4px' }}>
                        Type: {preview.parsed.rule_type} · Event: {preview.parsed.event_type}
                    </div>
                </div>

                {/* Conflicting rules */}
                <div style={{ marginBottom: '20px' }}>
                    <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: '12px', fontWeight: 700, marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '1px' }}>
                        Conflicting Rules — select to deactivate
                    </div>
                    {preview.conflicts.map(conflict => (
                        <div
                            key={conflict.rule_id}
                            onClick={() => onToggleDeactivate(conflict.rule_id)}
                            style={{
                                background: selectedToDeactivate.includes(conflict.rule_id)
                                    ? 'rgba(255,100,100,0.1)' : 'rgba(255,255,255,0.03)',
                                border: selectedToDeactivate.includes(conflict.rule_id)
                                    ? '1px solid rgba(255,100,100,0.4)' : '1px solid rgba(255,255,255,0.08)',
                                borderRadius: '10px',
                                padding: '12px',
                                marginBottom: '8px',
                                cursor: 'pointer',
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                transition: 'all 0.2s'
                            }}
                        >
                            <div>
                                <div style={{ color: 'rgba(255,255,255,0.85)', fontSize: '13px' }}>
                                    {conflict.rule_text}
                                </div>
                                <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: '11px', marginTop: '3px' }}>
                                    RULE-{String(conflict.rule_id).padStart(2, '0')} · {conflict.rule_type} · {conflict.event_type}
                                    {conflict.has_type_conflict && (
                                        <span style={{ color: 'rgba(255,180,50,0.8)', marginLeft: '6px' }}>⚡ type conflict</span>
                                    )}
                                </div>
                            </div>
                            <div style={{
                                width: '18px', height: '18px',
                                borderRadius: '4px',
                                border: '1px solid rgba(255,100,100,0.4)',
                                background: selectedToDeactivate.includes(conflict.rule_id) ? 'rgba(255,100,100,0.6)' : 'transparent',
                                flexShrink: 0
                            }} />
                        </div>
                    ))}
                </div>

                {/* Actions */}
                <div style={{ display: 'flex', gap: '10px' }}>
                    <button
                        onClick={onCancel}
                        style={{
                            flex: 1, padding: '12px',
                            background: 'transparent',
                            border: '1px solid rgba(255,255,255,0.15)',
                            borderRadius: '8px',
                            color: 'rgba(255,255,255,0.6)',
                            cursor: 'pointer', fontSize: '14px'
                        }}
                    >
                        Cancel
                    </button>
                    <button
                        onClick={onConfirm}
                        disabled={selectedToDeactivate.length === 0}
                        style={{
                            flex: 1, padding: '12px',
                            background: selectedToDeactivate.length > 0
                                ? 'rgba(255,100,100,0.2)' : 'rgba(255,255,255,0.05)',
                            border: '1px solid rgba(255,100,100,0.3)',
                            borderRadius: '8px',
                            color: selectedToDeactivate.length > 0
                                ? 'rgba(255,100,100,0.9)' : 'rgba(255,255,255,0.2)',
                            cursor: selectedToDeactivate.length > 0 ? 'pointer' : 'not-allowed',
                            fontSize: '14px', fontWeight: 600
                        }}
                    >
                        Deactivate & {isReactivating ? "Reactivate" : "Add"} ({selectedToDeactivate.length})
                    </button>
                </div>
            </div>
        </div>
    );
}
