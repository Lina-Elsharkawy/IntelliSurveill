/**
 * Logs API service.
 */

import { apiGet } from '@/lib/api';
import type { Log } from '@/types/types';

/**
 * Get all logs.
 */
export async function getAllLogs(): Promise<Log[]> {
    return apiGet<Log[]>('/api/logs/logs');
}

/**
 * Get a single log by ID.
 */
export async function getLogById(id: number): Promise<Log> {
    return apiGet<Log>(`/api/logs/log${id}`);
}

/**
 * Get logs by camera ID.
 */
export async function getLogsByCamera(cameraId: number): Promise<Log[]> {
    return apiGet<Log[]>(`/api/logs/cameralogs/${cameraId}`);
}

/**
 * Get logs by event type.
 */
export async function getLogsByEventType(eventType: string): Promise<Log[]> {
    return apiGet<Log[]>(`/api/logs/event/${encodeURIComponent(eventType)}`);
}

/**
 * Get logs by authorization status.
 */
export async function getLogsByAuthorization(authorized: boolean): Promise<Log[]> {
    return apiGet<Log[]>(`/api/logs/authorized/${authorized}`);
}

/**
 * Get logs by location.
 */
export async function getLogsByLocation(location: string): Promise<Log[]> {
    return apiGet<Log[]>(`/api/logs/location/${encodeURIComponent(location)}`);
}

/**
 * Get logs by anomaly ID.
 */
export async function getLogsByAnomaly(anomalyId: number): Promise<Log[]> {
    return apiGet<Log[]>(`/api/logs/anomaly/${anomalyId}`);
}
