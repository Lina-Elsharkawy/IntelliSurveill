/**
 * Anomaly Configuration API service.
 * Handles updating anomaly detection settings via Kafka.
 */

import { apiPost } from '@/lib/api';
import type { AnomalyConfig, AnomalyConfigResponse } from '@/types/types';

/**
 * Update anomaly detection configuration.
 * This sends the configuration to Kafka for real-time updates.
 * 
 * @param config - The anomaly detection configuration
 * @returns Promise with the updated configuration and timestamp
 */
export async function updateAnomalyConfig(config: AnomalyConfig): Promise<AnomalyConfigResponse> {
    return apiPost<AnomalyConfigResponse, AnomalyConfig>('/api/anomalies/config', config);
}
