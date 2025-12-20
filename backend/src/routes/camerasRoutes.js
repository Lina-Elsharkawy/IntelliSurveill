const express = require('express');
const router = express.Router();
const camerasController = require('../controllers/CameraControllers');
// Route to get all cameras
router.get('/get_all_cameras', camerasController.getCameras);
// Route to get a single camera by ID
router.get('/get_camera/:id', camerasController.getCameraById);
// Route to create a new camera
router.post('/create_camera', camerasController.createCamera);
// Route to update an existing camera
router.put('/update_camera/:id', camerasController.updateCamera);
// Route to delete a camera
router.delete('/delete_camera/:id', camerasController.deleteCamera);
module.exports = router;


