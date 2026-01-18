/**
 * Tests for Cameras API service.
 */

import { describe, it, expect } from 'vitest';
import { getAllCameras, getCameraById, createCamera, updateCamera, deleteCamera } from '@/services/cameras';
import { mockFetch, mockFetchError } from '../mocks/api';
import type { Camera, CameraInput } from '@/types/types';

describe('Cameras Service', () => {
    const mockCamera: Camera = {
        id: 1,
        name: 'Main Entrance Camera',
        location: 'Building A - Main Lobby',
        lab_id: 1,
    };

    const mockCameraInput: CameraInput = {
        name: 'Main Entrance Camera',
        location: 'Building A - Main Lobby',
        lab_id: 1,
    };

    describe('getAllCameras', () => {
        it('should fetch all cameras', async () => {
            mockFetch([mockCamera]);

            const result = await getAllCameras();

            expect(result).toEqual([mockCamera]);
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/cameras/get_all_cameras'),
                expect.objectContaining({ method: 'GET' })
            );
        });
    });

    describe('getCameraById', () => {
        it('should fetch camera by ID', async () => {
            mockFetch(mockCamera);

            const result = await getCameraById(1);

            expect(result).toEqual(mockCamera);
        });
    });

    describe('createCamera', () => {
        it('should create a new camera', async () => {
            mockFetch(mockCamera, 201);

            const result = await createCamera(mockCameraInput);

            expect(result).toEqual(mockCamera);
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/cameras/create_camera'),
                expect.objectContaining({
                    method: 'POST',
                    body: JSON.stringify(mockCameraInput),
                })
            );
        });
    });

    describe('updateCamera', () => {
        it('should update camera by ID', async () => {
            mockFetch(mockCamera);

            const result = await updateCamera(1, mockCameraInput);

            expect(result).toEqual(mockCamera);
            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/cameras/update_camera/1'),
                expect.objectContaining({ method: 'PUT' })
            );
        });
    });

    describe('deleteCamera', () => {
        it('should delete camera by ID', async () => {
            mockFetch({ message: 'Camera deleted successfully' });

            const result = await deleteCamera(1);

            expect(result.message).toBe('Camera deleted successfully');
        });
    });
});
