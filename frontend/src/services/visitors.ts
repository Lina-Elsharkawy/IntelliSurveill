/**
 * Visitors API service.
 */

import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api';
import type { Visitor, VisitorInput, SuccessMessage } from '@/types/types';

/**
 * Get all visitors.
 */
export async function getAllVisitors(): Promise<Visitor[]> {
    return apiGet<Visitor[]>('/api/visitors/get_all_visitors');
}

/**
 * Get a single visitor by ID.
 */
export async function getVisitorById(id: number): Promise<Visitor> {
    return apiGet<Visitor>(`/api/visitors/get_visitor/${id}`);
}

/**
 * Create a new visitor.
 */
export async function createVisitor(data: VisitorInput): Promise<Visitor> {
    return apiPost<Visitor, VisitorInput>('/api/visitors/create_visitor', data);
}

/**
 * Update an existing visitor.
 */
export async function updateVisitor(id: number, data: Partial<VisitorInput>): Promise<Visitor> {
    return apiPut<Visitor, Partial<VisitorInput>>(`/api/visitors/update_visitor/${id}`, data);
}

/**
 * Delete a visitor by ID.
 */
export async function deleteVisitor(id: number): Promise<SuccessMessage> {
    return apiDelete<SuccessMessage>(`/api/visitors/delete_visitor/${id}`);
}
