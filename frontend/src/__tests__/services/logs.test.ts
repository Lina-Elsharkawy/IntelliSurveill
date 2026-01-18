/**
 * Tests for Logs API service.
 */

import { describe, it, expect } from 'vitest';
import {
    getAllLogs,
    getLogById,
    getLogsByCamera,
    getLogsByEventType,
    getLogsByAuthorization,
    getLogsByLocation,
    getLogsByAnomaly,
} from '@/services/logs';
import { mockFetch } from '../mocks/api';
import type { Log } from '@/types/types';

describe('Logs Service', () => {
    const mockLog: Log = {
        id: 1,
        timestamp: '2025-12-20T10:30:00Z',
        detected_id: 1,
        camera_id: 1,
        anomaly_id: null,
        authorized: true,
        confidence_score: 0.95,
        event_type: 'entry',
        location: 'Building A - Main Lobby',
        device_status: 'active',
        image_video_ref: 's3://bucket/videos/entry_12345.mp4',
        processing_time: 0.234,
        model_version: 'v2.1.0',
    };

    describe('getAllLogs', () => {
        it('should fetch all logs', async () => {
            mockFetch([mockLog]);

            const result = await getAllLogs();

            expect(result).toEqual([mockLog]);
        });
    });

    describe('getLogById', () => {
        it('should fetch log by ID', async () => {
            mockFetch(mockLog);

            const result = await getLogById(1);

            expect(result).toEqual(mockLog);
        });
    });

    describe('getLogsByCamera', () => {
        it('should fetch logs by camera ID', async () => {
            mockFetch([mockLog]);

            const result = await getLogsByCamera(1);

            expect(result).toEqual([mockLog]);
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/logs/cameralogs/1'),
                expect.any(Object)
            );
        });
    });

    describe('getLogsByEventType', () => {
        it('should fetch logs by event type', async () => {
            mockFetch([mockLog]);

            const result = await getLogsByEventType('entry');

            expect(result).toEqual([mockLog]);
        });
    });

    describe('getLogsByAuthorization', () => {
        it('should fetch logs by authorization status', async () => {
            mockFetch([mockLog]);

            const result = await getLogsByAuthorization(true);

            expect(result).toEqual([mockLog]);
        });
    });

    describe('getLogsByLocation', () => {
        it('should fetch logs by location', async () => {
            mockFetch([mockLog]);

            const result = await getLogsByLocation('Building A - Main Lobby');

            expect(result).toEqual([mockLog]);
        });
    });

    describe('getLogsByAnomaly', () => {
        it('should fetch logs by anomaly ID', async () => {
            mockFetch([mockLog]);

            const result = await getLogsByAnomaly(1);

            expect(result).toEqual([mockLog]);
        });
    });
});
