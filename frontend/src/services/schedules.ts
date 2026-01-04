/**
 * Schedules API service.
 */

import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api';
import type { Schedule, ScheduleInput, SuccessMessage } from '@/types/types';

/**
 * Get all schedules.
 */
export async function getAllSchedules(): Promise<Schedule[]> {
    return apiGet<Schedule[]>('/api/schedules/get_all_schedules');
}

/**
 * Get a single schedule by ID.
 */
export async function getScheduleById(id: number): Promise<Schedule> {
    return apiGet<Schedule>(`/api/schedules/get_schedule/${id}`);
}

/**
 * Create a new schedule.
 */
export async function createSchedule(data: ScheduleInput): Promise<Schedule> {
    return apiPost<Schedule, ScheduleInput>('/api/schedules/create_schedule', data);
}

/**
 * Update an existing schedule.
 */
export async function updateSchedule(id: number, data: ScheduleInput): Promise<Schedule> {
    return apiPut<Schedule, ScheduleInput>(`/api/schedules/update_schedule/${id}`, data);
}

/**
 * Delete a schedule by ID.
 */
export async function deleteSchedule(id: number): Promise<SuccessMessage> {
    return apiDelete<SuccessMessage>(`/api/schedules/delete_schedule/${id}`);
}
