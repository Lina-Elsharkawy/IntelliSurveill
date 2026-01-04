/**
 * Tests for Labs API service.
 */

import { describe, it, expect } from 'vitest';
import { getAllLabs, getLabById, createLab, updateLab, deleteLab } from '@/services/labs';
import { mockFetch } from '../mocks/api';
import type { Lab, LabInput } from '@/types/types';

describe('Labs Service', () => {
    const mockLab: Lab = {
        id: 1,
        name: 'AI Research Lab',
    };

    const mockLabInput: LabInput = {
        name: 'AI Research Lab',
    };

    describe('getAllLabs', () => {
        it('should fetch all labs', async () => {
            mockFetch([mockLab]);

            const result = await getAllLabs();

            expect(result).toEqual([mockLab]);
        });
    });

    describe('getLabById', () => {
        it('should fetch lab by ID', async () => {
            mockFetch(mockLab);

            const result = await getLabById(1);

            expect(result).toEqual(mockLab);
        });
    });

    describe('createLab', () => {
        it('should create a new lab', async () => {
            mockFetch(mockLab, 201);

            const result = await createLab(mockLabInput);

            expect(result).toEqual(mockLab);
        });
    });

    describe('updateLab', () => {
        it('should update lab by ID', async () => {
            mockFetch(mockLab);

            const result = await updateLab(1, mockLabInput);

            expect(result).toEqual(mockLab);
        });
    });

    describe('deleteLab', () => {
        it('should delete lab by ID', async () => {
            mockFetch({ message: 'Lab deleted successfully' });

            const result = await deleteLab(1);

            expect(result.message).toBe('Lab deleted successfully');
        });
    });
});
