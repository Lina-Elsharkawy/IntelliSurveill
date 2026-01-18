/**
 * Tests for Detected People API service.
 */

import { describe, it, expect } from 'vitest';
import { getAllDetectedPeople, getDetectedPersonById } from '@/services/detected-people';
import { mockFetch } from '../mocks/api';
import type { DetectedPerson } from '@/types/types';

describe('Detected People Service', () => {
    const mockDetectedPerson: DetectedPerson = {
        id: 1,
        name: 'John Doe',
        additional_info: 'Wearing safety badge',
        employee_id: 1,
        visitor: false,
        visitor_id: null,
    };

    describe('getAllDetectedPeople', () => {
        it('should fetch all detected people', async () => {
            mockFetch([mockDetectedPerson]);

            const result = await getAllDetectedPeople();

            expect(result).toEqual([mockDetectedPerson]);
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/detected-people/get_people'),
                expect.objectContaining({ method: 'GET' })
            );
        });
    });

    describe('getDetectedPersonById', () => {
        it('should fetch detected person by ID', async () => {
            mockFetch(mockDetectedPerson);

            const result = await getDetectedPersonById(1);

            expect(result).toEqual(mockDetectedPerson);
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/detected-people/get_person/1'),
                expect.any(Object)
            );
        });
    });
});
