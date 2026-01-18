/**
 * Cameras API service.
 */

import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api';
import type { Camera, CameraInput, SuccessMessage } from '@/types/types';

/**
 * Get all cameras.
 */
export async function getAllCameras(): Promise<Camera[]> {
    return apiGet<Camera[]>('/api/cameras/get_all_cameras');
}

/**
 * Get a single camera by ID.
 */
export async function getCameraById(id: number): Promise<Camera> {
    return apiGet<Camera>(`/api/cameras/get_camera/${id}`);
}

/**
 * Create a new camera.
 */
export async function createCamera(data: CameraInput): Promise<Camera> {
    return apiPost<Camera, CameraInput>('/api/cameras/create_camera', data);
}

/**
 * Update an existing camera.
 */
export async function updateCamera(id: number, data: CameraInput): Promise<Camera> {
    return apiPut<Camera, CameraInput>(`/api/cameras/update_camera/${id}`, data);
}

/**
 * Delete a camera by ID.
 */
export async function deleteCamera(id: number): Promise<SuccessMessage> {
    return apiDelete<SuccessMessage>(`/api/cameras/delete_camera/${id}`);
}
