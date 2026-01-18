/**
 * Anomalies API service.
 */

import { apiGet, apiDelete } from '@/lib/api';
import type { Anomaly, SuccessMessage } from '@/types/types';

/**
 * Get all anomalies.
 */
export async function getAllAnomalies(): Promise<Anomaly[]> {
  return apiGet<Anomaly[]>('/api/anomalies/get_all_anomalies');
}

/**
 * Get a single anomaly by ID.
 */
export async function getAnomalyById(id: number): Promise<Anomaly> {
  return apiGet<Anomaly>(`/api/anomalies/get_anomaly/${id}`);
}

/**
 * Delete an anomaly by ID.
 */
export async function deleteAnomaly(id: number): Promise<SuccessMessage> {
  return apiDelete<SuccessMessage>(`/api/anomalies/delete_anomaly/${id}`);
}
