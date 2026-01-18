/**
 * Mock utilities for API testing.
 */

import { vi } from 'vitest';

/**
 * Creates a mock successful JSON response.
 */
export function mockJsonResponse<T>(data: T, status = 200): Response {
    return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => data,
    } as Response;
}

/**
 * Creates a mock error response.
 */
export function mockErrorResponse(error: string, status = 500): Response {
    return {
        ok: false,
        status,
        json: async () => ({ error }),
    } as Response;
}

/**
 * Helper to mock fetch for a single call.
 */
export function mockFetch<T>(data: T, status = 200) {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        mockJsonResponse(data, status)
    );
}

/**
 * Helper to mock fetch error.
 */
export function mockFetchError(error: string, status = 500) {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        mockErrorResponse(error, status)
    );
}
