import { apiGet, apiPost, apiDelete } from '@/lib/api';

// ── Types ──────────────────────────────────────────────────────────────────

export interface AuditLog {
    id: number;
    user_email: string;
    action: 'CREATE' | 'UPDATE' | 'DELETE' | 'LOGIN' | 'LOGOUT' | string;
    resource: string | null;
    resource_id: string | null;
    details: Record<string, any> | null;
    ip_address: string | null;
    user_agent: string | null;
    created_at: string;
}

export interface AuditLogsResponse {
    total: number;
    logs: AuditLog[];
}

export interface AuditLogFilters {
    user_email?: string;
    action?: string;
    resource?: string;
    from?: string;  // ISO date string
    to?: string;    // ISO date string
    limit?: number;
    offset?: number;
}

export interface AuditStats {
    by_action: { action: string; count: string }[];
    by_resource: { resource: string | null; count: string }[];
}

// ── Helpers ────────────────────────────────────────────────────────────────

const buildQuery = (filters: AuditLogFilters): string => {
    const params = new URLSearchParams();
    if (filters.user_email) params.set('user_email', filters.user_email);
    if (filters.action) params.set('action', filters.action);
    if (filters.resource) params.set('resource', filters.resource);
    if (filters.from) params.set('from', filters.from);
    if (filters.to) params.set('to', filters.to);
    params.set('limit', String(filters.limit ?? 100));
    params.set('offset', String(filters.offset ?? 0));
    return params.toString();
};

// ── API calls ──────────────────────────────────────────────────────────────

export async function getAuditLogs(filters: AuditLogFilters = {}): Promise<AuditLogsResponse> {
    return apiGet<AuditLogsResponse>(`/api/audit-logs?${buildQuery(filters)}`);
}

export async function getAuditLogById(id: number): Promise<AuditLog> {
    return apiGet<AuditLog>(`/api/audit-logs/${id}`);
}

export async function getAuditStats(): Promise<AuditStats> {
    return apiGet<AuditStats>('/api/audit-logs/stats');
}

/**
 * Clear all audit logs (Admin only)
 */
export async function clearAuditLogs(): Promise<{ message: string }> {
    return apiDelete<{ message: string }>('/api/audit-logs');
}

/**
 * Delete a specific audit log by ID (Admin only)
 */
export async function deleteAuditLog(id: number): Promise<{ message: string }> {
    return apiDelete<{ message: string }>(`/api/audit-logs/${id}`);
}

export async function createAuditLog(payload: Partial<AuditLog>): Promise<AuditLog> {
    return apiPost<AuditLog, Partial<AuditLog>>('/api/audit-logs', payload);
}