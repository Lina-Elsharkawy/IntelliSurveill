/**
 * RAG (Retrieval-Augmented Generation) API service.
 */

import { apiPost } from '@/lib/api';
import type { RAGQueryRequest, RAGQueryResponse } from '@/types/types';

/**
 * Submit a natural language query to the RAG system.
 */
export async function queryRAG(text: string): Promise<RAGQueryResponse> {
    return apiPost<RAGQueryResponse, RAGQueryRequest>('/api/rag/query', { text });
}
