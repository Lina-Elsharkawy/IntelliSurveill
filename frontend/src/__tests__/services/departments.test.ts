/**
 * Tests for Departments API service.
 */

import { describe, it, expect } from 'vitest';
import { getAllDepartments, getDepartmentById, createDepartment, updateDepartment, deleteDepartment } from '@/services/departments';
import { mockFetch } from '../mocks/api';
import type { Department, DepartmentInput } from '@/types/types';

describe('Departments Service', () => {
    const mockDepartment: Department = {
        id: 1,
        name: 'Computer Science',
    };

    const mockDepartmentInput: DepartmentInput = {
        name: 'Computer Science',
    };

    describe('getAllDepartments', () => {
        it('should fetch all departments', async () => {
            mockFetch([mockDepartment]);

            const result = await getAllDepartments();

            expect(result).toEqual([mockDepartment]);
        });
    });

    describe('getDepartmentById', () => {
        it('should fetch department by ID', async () => {
            mockFetch(mockDepartment);

            const result = await getDepartmentById(1);

            expect(result).toEqual(mockDepartment);
        });
    });

    describe('createDepartment', () => {
        it('should create a new department', async () => {
            mockFetch(mockDepartment, 201);

            const result = await createDepartment(mockDepartmentInput);

            expect(result).toEqual(mockDepartment);
        });
    });

    describe('updateDepartment', () => {
        it('should update department by ID', async () => {
            mockFetch(mockDepartment);

            const result = await updateDepartment(1, mockDepartmentInput);

            expect(result).toEqual(mockDepartment);
        });
    });

    describe('deleteDepartment', () => {
        it('should delete department by ID', async () => {
            mockFetch({ message: 'Department deleted successfully' });

            const result = await deleteDepartment(1);

            expect(result.message).toBe('Department deleted successfully');
        });
    });
});
