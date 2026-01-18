/**
 * Tests for RAG API service.
 */

import { describe, it, expect } from 'vitest';
import { queryRAG } from '@/services/rag';
import { mockFetch, mockFetchError } from '../mocks/api';
import type { RAGQueryResponse } from '@/types/types';

describe('RAG Service', () => {
    describe('queryRAG', () => {
        it('should submit a query and return response', async () => {
            const mockResponse: RAGQueryResponse = {
                status: 'success',
                data: { answer: 'There were 5 unauthorized access attempts today.' },
            };
            mockFetch(mockResponse);

            const result = await queryRAG('How many unauthorized access attempts were there today?');

            expect(result).toEqual(mockResponse);
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/rag/query'),
                expect.objectContaining({
                    method: 'POST',
                    body: JSON.stringify({ text: 'How many unauthorized access attempts were there today?' }),
                })
            );
        });

        it('should handle error responses', async () => {
            mockFetchError('Query text is required', 400);

            await expect(queryRAG('')).rejects.toThrow('Query text is required');
        });
    });
});
