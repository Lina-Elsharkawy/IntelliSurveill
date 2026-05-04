import React from "react";
import { PreviewResult } from "@/services/anomalyRulesService";

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

    const isDuplicateOnly = preview.has_duplicate && preview.conflicts.length === 1 && preview.conflicts[0].rule_id === preview.duplicate?.rule_id;
    const hasBoth = preview.has_duplicate && preview.conflicts.length > 1;

    const title = isDuplicateOnly ? "Duplication Alert" : (hasBoth ? "Conflict & Duplication Detected" : "Rule Conflict Detected");
    
    // Theme colors
    const themeColor = isDuplicateOnly ? "rgba(255,180,50,1)" : "rgba(255,100,100,1)";
    const themeBg = isDuplicateOnly ? "rgba(255,180,50,0.1)" : "rgba(255,100,100,0.1)";
    const themeBorder = isDuplicateOnly ? "rgba(255,180,50,0.3)" : "rgba(255,100,100,0.3)";

    return (
        <div style={{
            position: 'fixed', inset: 0,
            background: 'rgba(0,0,0,0.7)',
            backdropFilter: 'blur(8px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 9999,
            padding: '20px'
        }}>
            <div style={{
                background: '#12121a',
                border: `1px solid ${themeBorder}`,
                boxShadow: `0 20px 40px -10px rgba(0,0,0,0.8), 0 0 20px 0 ${themeBg} inset`,
                borderRadius: '20px',
                padding: '32px',
                width: '100%',
                maxWidth: '600px',
                maxHeight: '85vh',
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden'
            }}>
                {/* Header */}
                <div style={{ marginBottom: '24px', flexShrink: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                        {isDuplicateOnly ? (
                            <div style={{ background: themeBg, padding: '8px', borderRadius: '12px' }}>
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={themeColor} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                                </svg>
                            </div>
                        ) : (
                            <div style={{ background: themeBg, padding: '8px', borderRadius: '12px' }}>
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={themeColor} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                                    <line x1="12" y1="9" x2="12" y2="13"></line>
                                    <line x1="12" y1="17" x2="12.01" y2="17"></line>
                                </svg>
                            </div>
                        )}
                        <h2 style={{ color: themeColor, margin: 0, fontSize: '20px', fontWeight: 700, fontFamily: 'Montserrat, sans-serif' }}>
                            {title}
                        </h2>
                    </div>
                    <p style={{ color: 'rgba(255,255,255,0.6)', fontSize: '14px', margin: '0 0 0 44px', lineHeight: 1.5 }}>
                        {isDuplicateOnly 
                            ? `Your ${isReactivating ? "reactivated rule" : "new rule"} is an exact duplicate of an existing active rule. Choose if you want to replace it or cancel.`
                            : `Your ${isReactivating ? "reactivated rule" : "new rule"} conflicts with existing active rules. Choose which ones to deactivate.`}
                    </p>
                </div>

                <div style={{ overflowY: 'auto', flex: 1, paddingRight: '4px', margin: '0 -4px 0 0' }}>
                    {/* New rule preview */}
                    <div style={{
                        background: 'rgba(46,213,115,0.06)',
                        border: '1px solid rgba(46,213,115,0.2)',
                        borderRadius: '12px',
                        padding: '16px',
                        marginBottom: '24px',
                        position: 'relative',
                        overflow: 'hidden'
                    }}>
                        <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: '4px', background: 'rgba(46,213,115,0.6)' }} />
                        <div style={{ color: 'rgba(46,213,115,0.9)', fontSize: '11px', fontWeight: 700, marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '1.5px', fontFamily: 'Montserrat, sans-serif' }}>
                            {isReactivating ? "Reactivating Rule" : "New Rule"}
                        </div>
                        <div style={{ color: '#fff', fontSize: '15px', fontWeight: 500, marginBottom: '6px' }}>{ruleInput}</div>
                        <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '13px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                            <span style={{ background: 'rgba(255,255,255,0.1)', padding: '2px 8px', borderRadius: '4px' }}>{preview.parsed.rule_type}</span>
                            <span>•</span>
                            <span>{preview.parsed.event_type}</span>
                        </div>
                    </div>

                    {/* Conflicting rules */}
                    <div style={{ marginBottom: '8px' }}>
                        <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: '12px', fontWeight: 700, marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '1px', fontFamily: 'Montserrat, sans-serif' }}>
                            {isDuplicateOnly ? "Duplicate Active Rule" : "Conflicting Rules — select to deactivate"}
                        </div>
                        {preview.conflicts.map(conflict => (
                            <div
                                key={conflict.rule_id}
                                onClick={() => onToggleDeactivate(conflict.rule_id)}
                                style={{
                                    background: selectedToDeactivate.includes(conflict.rule_id)
                                        ? themeBg : 'rgba(255,255,255,0.02)',
                                    border: `1px solid ${selectedToDeactivate.includes(conflict.rule_id)
                                        ? themeBorder : 'rgba(255,255,255,0.06)'}`,
                                    borderRadius: '12px',
                                    padding: '16px',
                                    marginBottom: '10px',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center',
                                    transition: 'all 0.2s ease-in-out',
                                    transform: selectedToDeactivate.includes(conflict.rule_id) ? 'scale(1.01)' : 'scale(1)'
                                }}
                            >
                                <div>
                                    <div style={{ color: 'rgba(255,255,255,0.9)', fontSize: '14px', fontWeight: 500 }}>
                                        {conflict.rule_text}
                                    </div>
                                    <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '12px', marginTop: '6px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                                        <span style={{ fontFamily: 'monospace', color: 'rgba(255,255,255,0.6)' }}>RULE-{String(conflict.rule_id).padStart(2, '0')}</span>
                                        <span>•</span>
                                        <span>{conflict.rule_type}</span>
                                        <span>•</span>
                                        <span>{conflict.event_type}</span>
                                        {conflict.has_type_conflict && (
                                            <span style={{ color: 'rgba(255,180,50,0.9)', background: 'rgba(255,180,50,0.1)', padding: '2px 6px', borderRadius: '4px', fontSize: '10px', marginLeft: '4px', fontWeight: 600 }}>
                                                ⚡ TYPE CONFLICT
                                            </span>
                                        )}
                                    </div>
                                </div>
                                <div style={{
                                    width: '22px', height: '22px',
                                    borderRadius: '6px',
                                    border: `2px solid ${selectedToDeactivate.includes(conflict.rule_id) ? themeColor : 'rgba(255,255,255,0.2)'}`,
                                    background: selectedToDeactivate.includes(conflict.rule_id) ? themeColor : 'transparent',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    flexShrink: 0,
                                    transition: 'all 0.2s'
                                }}>
                                    {selectedToDeactivate.includes(conflict.rule_id) && (
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#000" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                                            <polyline points="20 6 9 17 4 12"></polyline>
                                        </svg>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Actions */}
                <div style={{ display: 'flex', gap: '12px', marginTop: '24px', flexShrink: 0 }}>
                    <button
                        onClick={onCancel}
                        style={{
                            flex: 1, padding: '14px',
                            background: 'rgba(255,255,255,0.05)',
                            border: '1px solid rgba(255,255,255,0.1)',
                            borderRadius: '10px',
                            color: 'rgba(255,255,255,0.8)',
                            cursor: 'pointer', fontSize: '14px', fontWeight: 600,
                            fontFamily: 'Montserrat, sans-serif',
                            transition: 'all 0.2s'
                        }}
                        onMouseOver={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.1)'}
                        onMouseOut={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
                    >
                        Cancel
                    </button>
                    <button
                        onClick={onConfirm}
                        disabled={selectedToDeactivate.length === 0}
                        style={{
                            flex: 2, padding: '14px',
                            background: selectedToDeactivate.length > 0
                                ? themeBg : 'rgba(255,255,255,0.05)',
                            border: `1px solid ${selectedToDeactivate.length > 0 ? themeBorder : 'rgba(255,255,255,0.1)'}`,
                            borderRadius: '10px',
                            color: selectedToDeactivate.length > 0
                                ? themeColor : 'rgba(255,255,255,0.3)',
                            cursor: selectedToDeactivate.length > 0 ? 'pointer' : 'not-allowed',
                            fontSize: '14px', fontWeight: 700,
                            fontFamily: 'Montserrat, sans-serif',
                            transition: 'all 0.2s'
                        }}
                        onMouseOver={(e) => { if(selectedToDeactivate.length > 0) e.currentTarget.style.background = isDuplicateOnly ? 'rgba(255,180,50,0.15)' : 'rgba(255,100,100,0.15)' }}
                        onMouseOut={(e) => { if(selectedToDeactivate.length > 0) e.currentTarget.style.background = themeBg }}
                    >
                        {isDuplicateOnly ? "Replace Duplicate" : `Deactivate & ${isReactivating ? "Reactivate" : "Add"} (${selectedToDeactivate.length})`}
                    </button>
                </div>
            </div>
        </div>
    );
}
