const express = require('express');
const router = express.Router();
const checkJwt = require('../middleware/auth');
const adminController = require('../controllers/adminController');
const vectorMatchController = require('../controllers/vectorMatchController');

// Apply JWT check middleware to all admin routes
router.use(checkJwt);

// ── Auth0 user management (existing, untouched) ──
router.get('/roles', adminController.getAllRoles);
router.get('/users', adminController.getUsers);
router.post('/users', adminController.createUser);
router.patch('/users/:id', adminController.updateUser);
router.delete('/users/:id', adminController.deleteUser);
router.get('/users/:id/roles', adminController.getUserRoles);
router.put('/users/:id/roles', adminController.updateRoles);
router.post('/users/:id/roles', adminController.assignRoles);
router.delete('/users/:id/roles', adminController.removeRoles);


// ── Vector-match face identity routes (new) ──
router.get('/identities', vectorMatchController.listIdentities);
router.get('/pending-unknowns', vectorMatchController.listPendingUnknowns);
router.get('/recent-entry-logs', vectorMatchController.listRecentEntryLogs);
router.get('/entry-logs/:id/image', vectorMatchController.getEntryLogImage);
router.post('/assign-unknown', vectorMatchController.assignUnknown);
router.post('/create-identity-from-unknown', vectorMatchController.createIdentityFromUnknown);
router.get('/entry-logs/:id/thumbnail', vectorMatchController.getEntryLogThumbnail);
router.get('/counts', vectorMatchController.getCounts);
module.exports = router;