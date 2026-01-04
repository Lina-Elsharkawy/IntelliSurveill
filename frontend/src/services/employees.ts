/**
 * Employees API service.
 */

import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api';
import type { Employee, EmployeeInput, SuccessMessage } from '@/types/types';

/**
 * Get all employees.
 */
export async function getAllEmployees(): Promise<Employee[]> {
    return apiGet<Employee[]>('/api/employees/get_all_employees');
}

/**
 * Get a single employee by ID.
 */
export async function getEmployeeById(id: number): Promise<Employee> {
    return apiGet<Employee>(`/api/employees/get_employee/${id}`);
}

/**
 * Create a new employee.
 */
export async function createEmployee(data: EmployeeInput): Promise<Employee> {
    return apiPost<Employee, EmployeeInput>('/api/employees/create_employee', data);
}

/**
 * Update an existing employee.
 */
export async function updateEmployee(id: number, data: EmployeeInput): Promise<Employee> {
    return apiPut<Employee, EmployeeInput>(`/api/employees/update_employee/${id}`, data);
}

/**
 * Delete an employee by ID.
 */
export async function deleteEmployee(id: number): Promise<SuccessMessage> {
    return apiDelete<SuccessMessage>(`/api/employees/delete_employee/${id}`);
}
