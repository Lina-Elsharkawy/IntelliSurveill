/**
 * Tests for Employees API service.
 */

import { describe, it, expect } from 'vitest';
import { getAllEmployees, getEmployeeById, createEmployee, updateEmployee, deleteEmployee } from '@/services/employees';
import { mockFetch } from '../mocks/api';
import type { Employee, EmployeeInput } from '@/types/types';

describe('Employees Service', () => {
    const mockEmployee: Employee = {
        id: 1,
        name: 'John Doe',
        department_id: 1,
    };

    const mockEmployeeInput: EmployeeInput = {
        name: 'John Doe',
        department_id: 1,
    };

    describe('getAllEmployees', () => {
        it('should fetch all employees', async () => {
            mockFetch([mockEmployee]);

            const result = await getAllEmployees();

            expect(result).toEqual([mockEmployee]);
        });
    });

    describe('getEmployeeById', () => {
        it('should fetch employee by ID', async () => {
            mockFetch(mockEmployee);

            const result = await getEmployeeById(1);

            expect(result).toEqual(mockEmployee);
        });
    });

    describe('createEmployee', () => {
        it('should create a new employee', async () => {
            mockFetch(mockEmployee, 201);

            const result = await createEmployee(mockEmployeeInput);

            expect(result).toEqual(mockEmployee);
        });
    });

    describe('updateEmployee', () => {
        it('should update employee by ID', async () => {
            mockFetch(mockEmployee);

            const result = await updateEmployee(1, mockEmployeeInput);

            expect(result).toEqual(mockEmployee);
        });
    });

    describe('deleteEmployee', () => {
        it('should delete employee by ID', async () => {
            mockFetch({ message: 'Employee deleted successfully' });

            const result = await deleteEmployee(1);

            expect(result.message).toBe('Employee deleted successfully');
        });
    });
});
