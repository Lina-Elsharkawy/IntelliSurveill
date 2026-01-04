/**
 * Detected People API service.
 */

import { apiGet } from '@/lib/api';
import type { DetectedPerson } from '@/types/types';

/**
 * Get all detected people.
 */
export async function getAllDetectedPeople(): Promise<DetectedPerson[]> {
    return apiGet<DetectedPerson[]>('/api/detected-people/get_people');
}

/**
 * Get a single detected person by ID.
 */
export async function getDetectedPersonById(id: number): Promise<DetectedPerson> {
    return apiGet<DetectedPerson>(`/api/detected-people/get_person/${id}`);
}
