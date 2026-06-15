import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";
import type { SuccessMessage } from "@/types/types";


/* -------------------- User Management -------------------- */
export interface Auth0User {
    user_id: string;
    email: string;
    name: string;
    nickname: string;
    picture: string;
    last_login: string;
    logins_count: number;
}

export interface Auth0Role {
    id: string;
    name: string;
    description: string;
}

export async function getUsers(): Promise<Auth0User[]> {
    return apiGet<Auth0User[]>("/api/admin/users");
}

export async function getAllRoles(): Promise<Auth0Role[]> {
    return apiGet<Auth0Role[]>("/api/admin/roles");
}

export async function getUserRoles(userId: string): Promise<Auth0Role[]> {
    return apiGet<Auth0Role[]>(`/api/admin/users/${encodeURIComponent(userId)}/roles`);
}

export async function assignRoles(userId: string, roleIds: string[]): Promise<any> {
    return apiPost(`/api/admin/users/${encodeURIComponent(userId)}/roles`, { roles: roleIds });
}

export async function removeRoles(userId: string, roleIds: string[]): Promise<any> {
    return apiDelete(`/api/admin/users/${encodeURIComponent(userId)}/roles`, { roles: roleIds });
}

export async function updateRoles(userId: string, data: { addRoles: string[], removeRoles: string[], oldRoleNames: string[], newRoleNames: string[] }): Promise<any> {
    const { apiPut } = await import("@/lib/api");
    return apiPut(`/api/admin/users/${encodeURIComponent(userId)}/roles`, data);
}

export async function deleteUser(userId: string, name?: string): Promise<any> {
    return apiDelete(`/api/admin/users/${encodeURIComponent(userId)}`, { name });
}

export async function createUser(email: string, password: string, name?: string): Promise<Auth0User> {
    return apiPost<Auth0User, { email: string; password: string; name?: string }>('/api/admin/users', {
        email,
        password,
        name
    });
}

export async function updateUser(userId: string, data: { email?: string; name?: string; password?: string }): Promise<Auth0User> {
    return apiPatch<Auth0User, { email?: string; name?: string; password?: string }>(`/api/admin/users/${encodeURIComponent(userId)}`, data);
}