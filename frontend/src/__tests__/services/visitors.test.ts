/**
 * Tests for Visitors API service.
 */

import { describe, it, expect } from 'vitest';
import { getAllVisitors, getVisitorById, createVisitor, updateVisitor, deleteVisitor } from '@/services/visitors';
import { mockFetch } from '../mocks/api';
import type { Visitor, VisitorInput } from '@/types/types';

describe('Visitors Service', () => {
    const mockVisitor: Visitor = {
        id: 1,
        name: 'Jane Smith',
        visit_date: '2025-12-20T10:00:00Z',
        purpose: 'Lab tour',
        contact_info: 'jane.smith@example.com',
    };

    const mockVisitorInput: VisitorInput = {
        name: 'Jane Smith',
        visit_date: '2025-12-20T10:00:00Z',
        purpose: 'Lab tour',
        contact_info: 'jane.smith@example.com',
    };

    describe('getAllVisitors', () => {
        it('should fetch all visitors', async () => {
            mockFetch([mockVisitor]);

            const result = await getAllVisitors();

            expect(result).toEqual([mockVisitor]);
        });
    });

    describe('getVisitorById', () => {
        it('should fetch visitor by ID', async () => {
            mockFetch(mockVisitor);

            const result = await getVisitorById(1);

            expect(result).toEqual(mockVisitor);
        });
    });

    describe('createVisitor', () => {
        it('should create a new visitor', async () => {
            mockFetch(mockVisitor, 201);

            const result = await createVisitor(mockVisitorInput);

            expect(result).toEqual(mockVisitor);
        });
    });

    describe('updateVisitor', () => {
        it('should update visitor by ID', async () => {
            mockFetch(mockVisitor);

            const result = await updateVisitor(1, mockVisitorInput);

            expect(result).toEqual(mockVisitor);
        });
    });

    describe('deleteVisitor', () => {
        it('should delete visitor by ID', async () => {
            mockFetch({ message: 'Visitor deleted successfully' });

            const result = await deleteVisitor(1);

            expect(result.message).toBe('Visitor deleted successfully');
        });
    });
});
