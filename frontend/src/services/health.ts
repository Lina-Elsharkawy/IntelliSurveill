/**
 * Health check API service.
 */

import { apiGetPublic } from '@/lib/api';
import type { HealthResponse } from '@/types/types';

/**
 * Check the health of the backend server and database.
 */
export async function checkHealth(): Promise<HealthResponse> {
    return apiGetPublic<HealthResponse>('/health');
}
