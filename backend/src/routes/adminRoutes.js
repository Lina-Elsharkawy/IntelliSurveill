const express = require('express');
const router = express.Router();
const checkJwt = require('../middleware/auth');
const adminController = require('../controllers/adminController');

// Apply JWT check middleware
router.use(checkJwt);

// Static routes first (no parameters)
router.get('/roles', adminController.getAllRoles);

// /users routes - non-parameterized first
router.get('/users', adminController.getUsers);
router.post('/users', adminController.createUser);

// /users/:id routes (parameterized)
router.patch('/users/:id', adminController.updateUser);
router.delete('/users/:id', adminController.deleteUser);

// /users/:id/roles routes
router.get('/users/:id/roles', adminController.getUserRoles);
router.post('/users/:id/roles', adminController.assignRoles);
router.delete('/users/:id/roles', adminController.removeRoles);

module.exports = router;