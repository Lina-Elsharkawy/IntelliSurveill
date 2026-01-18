/**
 * Global test setup file for Vitest.
 */

import { vi, beforeEach, afterEach } from 'vitest';

// Mock localStorage
const localStorageMock = {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
};

Object.defineProperty(globalThis, 'localStorage', {
    value: localStorageMock,
});

// Reset mocks before each test
beforeEach(() => {
    vi.clearAllMocks();
    // Set default token for authenticated tests
    localStorageMock.getItem.mockReturnValue('test-jwt-token');
});

afterEach(() => {
    vi.restoreAllMocks();
});

// Mock fetch globally
globalThis.fetch = vi.fn();
