/**
 * Tests for Schedules API service.
 */

import { describe, it, expect } from 'vitest';
import { getAllSchedules, getScheduleById, createSchedule, updateSchedule, deleteSchedule } from '@/services/schedules';
import { mockFetch } from '../mocks/api';
import type { Schedule, ScheduleInput } from '@/types/types';

describe('Schedules Service', () => {
    const mockSchedule: Schedule = {
        id: 1,
        name: 'Regular Business Hours',
        access_start_time: '09:00:00',
        access_end_time: '17:00:00',
        applies_to_weekdays: true,
        applies_to_weekends: false,
        specific_dates: [],
    };

    const mockScheduleInput: ScheduleInput = {
        name: 'Regular Business Hours',
        access_start_time: '09:00:00',
        access_end_time: '17:00:00',
        applies_to_weekdays: true,
        applies_to_weekends: false,
    };

    describe('getAllSchedules', () => {
        it('should fetch all schedules', async () => {
            mockFetch([mockSchedule]);

            const result = await getAllSchedules();

            expect(result).toEqual([mockSchedule]);
        });
    });

    describe('getScheduleById', () => {
        it('should fetch schedule by ID', async () => {
            mockFetch(mockSchedule);

            const result = await getScheduleById(1);

            expect(result).toEqual(mockSchedule);
        });
    });

    describe('createSchedule', () => {
        it('should create a new schedule', async () => {
            mockFetch(mockSchedule, 201);

            const result = await createSchedule(mockScheduleInput);

            expect(result).toEqual(mockSchedule);
        });
    });

    describe('updateSchedule', () => {
        it('should update schedule by ID', async () => {
            mockFetch(mockSchedule);

            const result = await updateSchedule(1, mockScheduleInput);

            expect(result).toEqual(mockSchedule);
        });
    });

    describe('deleteSchedule', () => {
        it('should delete schedule by ID', async () => {
            mockFetch({ message: 'Schedule deleted successfully' });

            const result = await deleteSchedule(1);

            expect(result.message).toBe('Schedule deleted successfully');
        });
    });
});
