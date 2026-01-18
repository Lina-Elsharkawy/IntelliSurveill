/**
 * Labs API service.
 */

import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api';
import type { Lab, LabInput, SuccessMessage } from '@/types/types';

/**
 * Get all labs.
 */
export async function getAllLabs(): Promise<Lab[]> {
    return apiGet<Lab[]>('/api/labs/get_all_labs');
}

/**
 * Get a single lab by ID.
 */
export async function getLabById(id: number): Promise<Lab> {
    return apiGet<Lab>(`/api/labs/get_lab/${id}`);
}

/**
 * Create a new lab.
 */
export async function createLab(data: LabInput): Promise<Lab> {
    return apiPost<Lab, LabInput>('/api/labs/create_lab', data);
}

/**
 * Update an existing lab.
 */
export async function updateLab(id: number, data: LabInput): Promise<Lab> {
    return apiPut<Lab, LabInput>(`/api/labs/update_lab/${id}`, data);
}

/**
 * Delete a lab by ID.
 */
export async function deleteLab(id: number): Promise<SuccessMessage> {
    return apiDelete<SuccessMessage>(`/api/labs/delete_lab/${id}`);
}
