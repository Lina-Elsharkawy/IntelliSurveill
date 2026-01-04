/**
 * Tests for Health API service.
 */

import { describe, it, expect, vi } from 'vitest';
import { checkHealth } from '@/services/health';
import { mockFetch } from '../mocks/api';
import type { HealthResponse } from '@/types/types';

describe('Health Service', () => {
    describe('checkHealth', () => {
        it('should return healthy status', async () => {
            const mockResponse: HealthResponse = { status: 'ok' };
            mockFetch(mockResponse);

            const result = await checkHealth();

            expect(result).toEqual(mockResponse);
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/health'),
                expect.objectContaining({ method: 'GET' })
            );
        });

        it('should return db error status', async () => {
            const mockResponse: HealthResponse = { status: 'db error', error: 'Connection refused' };
            mockFetch(mockResponse);

            const result = await checkHealth();

            expect(result.status).toBe('db error');
            expect(result.error).toBe('Connection refused');
        });
    });
});
