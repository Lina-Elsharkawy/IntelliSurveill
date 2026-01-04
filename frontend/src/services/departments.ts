/**
 * Departments API service.
 */

import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api';
import type { Department, DepartmentInput, SuccessMessage } from '@/types/types';

/**
 * Get all departments.
 */
export async function getAllDepartments(): Promise<Department[]> {
    return apiGet<Department[]>('/api/departments/get_all_departments');
}

/**
 * Get a single department by ID.
 */
export async function getDepartmentById(id: number): Promise<Department> {
    return apiGet<Department>(`/api/departments/get_department/${id}`);
}

/**
 * Create a new department.
 */
export async function createDepartment(data: DepartmentInput): Promise<Department> {
    return apiPost<Department, DepartmentInput>('/api/departments/create_department', data);
}

/**
 * Update an existing department.
 */
export async function updateDepartment(id: number, data: DepartmentInput): Promise<Department> {
    return apiPut<Department, DepartmentInput>(`/api/departments/update_department/${id}`, data);
}

/**
 * Delete a department by ID.
 */
export async function deleteDepartment(id: number): Promise<SuccessMessage> {
    return apiDelete<SuccessMessage>(`/api/departments/delete_department/${id}`);
}
