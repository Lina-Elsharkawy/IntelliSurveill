/**
 * Centralized API client for backend communication.
 * Handles authentication, error handling, and provides typed HTTP helpers.
 * 
 * In development, requests to /api are proxied by Vite to the backend.
 * In production, set VITE_API_BASE_URL to the actual backend URL.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

/**
 * Gets the JWT token from localStorage.
 * @throws Error if user is not authenticated
 */
function getAuthToken(): string {
    const token = localStorage.getItem('access_token');
    if (!token) {
        throw new Error('User is not authenticated');
    }
    return token;
}

/**
 * Creates headers with Authorization bearer token.
 */
function getAuthHeaders(): HeadersInit {
    return {
        'Authorization': `Bearer ${getAuthToken()}`,
        'Content-Type': 'application/json',
    };
}

/**
 * Handles API response and throws on error.
 */
async function handleResponse<T>(response: Response): Promise<T> {
    if (response.status === 401) {
        window.dispatchEvent(new Event('auth:unauthorized'));
        throw new Error('Unauthorized');
    }
    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `Request failed with status ${response.status}`);
    }
    return response.json();
}

/**
 * GET request helper.
 */
export async function apiGet<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'GET',
        headers: getAuthHeaders(),
    });
    return handleResponse<T>(response);
}

/**
 * POST request helper.
 */
export async function apiPost<T, B = unknown>(endpoint: string, body: B): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify(body),
    });
    return handleResponse<T>(response);
}

/**
 * PUT request helper.
 */
export async function apiPut<T, B = unknown>(endpoint: string, body: B): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify(body),
    });
    return handleResponse<T>(response);
}

/**
 * DELETE request helper.
 */
export async function apiDelete<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
    });
    return handleResponse<T>(response);
}

/**
 * GET request without authentication (for public endpoints like health check).
 */
export async function apiGetPublic<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
    });
    return handleResponse<T>(response);
}
