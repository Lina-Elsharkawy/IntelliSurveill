/**
 * Tests for Anomalies API service.
 */

import { describe, it, expect, vi } from 'vitest';
import { getAllAnomalies, getAnomalyById, deleteAnomaly } from '@/services/anomalies';
import { mockFetch, mockFetchError } from '../mocks/api';
import type { Anomaly } from '@/types/types';

describe('Anomalies Service', () => {
    const mockAnomaly: Anomaly = {
        id: 1,
        description: 'Unauthorized access attempt',
        severity_level: 'high',
    };

    describe('getAllAnomalies', () => {
        it('should fetch all anomalies', async () => {
            const mockData = [mockAnomaly];
            mockFetch(mockData);

            const result = await getAllAnomalies();

            expect(result).toEqual(mockData);
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/anomalies/get_all_anomalies'),
                expect.objectContaining({ method: 'GET' })
            );
        });

        it('should throw error on failure', async () => {
            mockFetchError('Server error');

            await expect(getAllAnomalies()).rejects.toThrow('Server error');
        });
    });

    describe('getAnomalyById', () => {
        it('should fetch anomaly by ID', async () => {
            mockFetch(mockAnomaly);

            const result = await getAnomalyById(1);

            expect(result).toEqual(mockAnomaly);
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/anomalies/get_anomaly/1'),
                expect.any(Object)
            );
        });
    });

    describe('deleteAnomaly', () => {
        it('should delete anomaly by ID', async () => {
            mockFetch({ message: 'Anomaly deleted successfully' });

            const result = await deleteAnomaly(1);

            expect(result.message).toBe('Anomaly deleted successfully');
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/anomalies/delete_anomaly/1'),
                expect.objectContaining({ method: 'DELETE' })
            );
        });
    });
});
