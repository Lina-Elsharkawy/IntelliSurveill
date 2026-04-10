import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { DashboardLayout } from "@/components/DashboardLayout";
import {
    Trash2,
    Shield,
    RefreshCw,
    UserPlus,
    Mail,
    Calendar,
    Edit,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { useToast } from "@/components/ui/use-toast";
import {
    getUsers,
    getAllRoles,
    getUserRoles,
    assignRoles,
    removeRoles,
    deleteUser,
    createUser,
    updateUser,
    Auth0User,
    Auth0Role
} from "@/services/adminService";

const AdminUsers = () => {
    const { toast } = useToast();
    const [users, setUsers] = useState<Auth0User[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [allRoles, setAllRoles] = useState<Auth0Role[]>([]);
    const [selectedUser, setSelectedUser] = useState<Auth0User | null>(null);
    const [currentUserRoles, setCurrentUserRoles] = useState<Auth0Role[]>([]);
    const [roleDialogOpen, setRoleDialogOpen] = useState(false);
    const [isSavingRoles, setIsSavingRoles] = useState(false);
    const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
    const [userToDelete, setUserToDelete] = useState<Auth0User | null>(null);
    const [isDeleting, setIsDeleting] = useState(false);
    const [createDialogOpen, setCreateDialogOpen] = useState(false);
    const [updateDialogOpen, setUpdateDialogOpen] = useState(false);
    const [newUserEmail, setNewUserEmail] = useState("");
    const [newUserPassword, setNewUserPassword] = useState("");
    const [newUserName, setNewUserName] = useState("");
    const [isCreating, setIsCreating] = useState(false);
    const [isUpdating, setIsUpdating] = useState(false);
    const [updateEmail, setUpdateEmail] = useState("");
    const [updateName, setUpdateName] = useState("");
    const [updatePassword, setUpdatePassword] = useState("");
    const [userRoles, setUserRoles] = useState<Record<string, Auth0Role[]>>({});

    const fetchData = async () => {
        setIsLoading(true);
        try {
            const [usersData, rolesData] = await Promise.all([getUsers(), getAllRoles()]);
            setUsers(usersData);
            setAllRoles(rolesData);

            // Fetch roles for each user to determine admin count
            const rolesMap: Record<string, Auth0Role[]> = {};
            await Promise.all(
                usersData.map(async (user) => {
                    try {
                        const roles = await getUserRoles(user.user_id);
                        rolesMap[user.user_id] = roles;
                    } catch (error) {
                        rolesMap[user.user_id] = [];
                    }
                })
            );
            setUserRoles(rolesMap);
        } catch (error) {
            toast({
                title: "Error",
                description: "Failed to fetch users or roles.",
                variant: "destructive",
            });
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
    }, []);

    const handleManageRoles = async (user: Auth0User) => {
        setSelectedUser(user);
        setRoleDialogOpen(true);
        try {
            const roles = await getUserRoles(user.user_id);
            setCurrentUserRoles(roles);
        } catch (error) {
            toast({ title: "Error", description: "Failed to fetch user roles.", variant: "destructive" });
        }
    };

    const handleRoleToggle = (roleId: string, isChecked: boolean) => {
        if (isChecked) {
            // Single role mode: Select this one, clear others
            const role = allRoles.find(r => r.id === roleId);
            if (role) setCurrentUserRoles([role]);
        } else {
            // Allow deselecting the single role
            setCurrentUserRoles([]);
        }
    };

    const saveRoles = async () => {
        if (!selectedUser) return;
        setIsSavingRoles(true);
        try {
            const originalRoles = await getUserRoles(selectedUser.user_id);
            const originalIds = originalRoles.map(r => r.id);
            const currentIds = currentUserRoles.map(r => r.id);

            // Calculate roles to remove (all previous roles that are not the new one)
            const toAdd = currentIds.filter(id => !originalIds.includes(id));
            const toRemove = originalIds.filter(id => !currentIds.includes(id));

            // Execute remove first, then add to ensure clean state
            if (toRemove.length) await removeRoles(selectedUser.user_id, toRemove);
            if (toAdd.length) await assignRoles(selectedUser.user_id, toAdd);

            toast({ title: "Success", description: "Roles updated." });
            setRoleDialogOpen(false);
            await fetchData(); // Refresh to show updated roles
        } catch (error) {
            toast({ title: "Error", description: "Failed to update roles.", variant: "destructive" });
        } finally {
            setIsSavingRoles(false);
        }
    };

    const handleDeleteUser = async () => {
        if (!userToDelete) return;
        setIsDeleting(true);
        try {
            await deleteUser(userToDelete.user_id);
            setUsers(prev => prev.filter(u => u.user_id !== userToDelete.user_id));
            setDeleteDialogOpen(false);
            toast({ title: "Success", description: "User deleted." });
        } catch (error) {
            toast({ title: "Error", description: "Failed to delete user.", variant: "destructive" });
        } finally {
            setIsDeleting(false);
        }
    };

    const handleCreateUser = async () => {
        if (!newUserEmail || !newUserPassword) {
            toast({
                title: "Validation Error",
                description: "Email and password are required.",
                variant: "destructive"
            });
            return;
        }

        setIsCreating(true);
        try {
            console.log('Creating user:', { email: newUserEmail, name: newUserName });
            await createUser(newUserEmail, newUserPassword, newUserName || undefined);
            setCreateDialogOpen(false);
            setNewUserEmail("");
            setNewUserPassword("");
            setNewUserName("");
            await fetchData();
            toast({ title: "Success", description: "User created successfully." });
        } catch (error: any) {
            console.error('Create user error:', error);
            toast({
                title: "Error",
                description: error.message || "Failed to create user.",
                variant: "destructive"
            });
        } finally {
            setIsCreating(false);
        }
    };

    const openUpdateDialog = (user: Auth0User) => {
        setSelectedUser(user);
        setUpdateEmail(user.email);
        setUpdateName(user.name || "");
        setUpdatePassword("");
        setUpdateDialogOpen(true);
    };

    const handleUpdateUser = async () => {
        if (!selectedUser) return;

        setIsUpdating(true);
        try {
            const updateData: { email?: string; name?: string; password?: string } = {};

            if (updateEmail && updateEmail !== selectedUser.email) {
                updateData.email = updateEmail;
            }
            if (updateName && updateName !== selectedUser.name) {
                updateData.name = updateName;
            }
            if (updatePassword) {
                updateData.password = updatePassword;
            }

            if (Object.keys(updateData).length === 0) {
                toast({
                    title: "No Changes",
                    description: "No changes were made.",
                    variant: "default"
                });
                setUpdateDialogOpen(false);
                return;
            }

            console.log('Updating user:', { userId: selectedUser.user_id, updateData });
            await updateUser(selectedUser.user_id, updateData);

            toast({
                title: "Success",
                description: "User updated successfully."
            });
            setUpdateDialogOpen(false);
            await fetchData(); // Refresh the user list
        } catch (error: any) {
            console.error('Update user error:', error);
            toast({
                title: "Error",
                description: error.message || "Failed to update user.",
                variant: "destructive"
            });
        } finally {
            setIsUpdating(false);
        }
    };

    return (
        <DashboardLayout>
            <div className="min-h-screen p-8" style={{ background: "#050505", color: "#fff" }}>
                <div className="max-w-7xl mx-auto space-y-6">
                    {/* Header */}
                    <div className="flex justify-between items-center mb-8">
                        <div>
                            <div style={{ fontFamily: "'Outfit', sans-serif", fontSize: 16, fontWeight: 800, color: "rgba(46,213,115,0.6)", letterSpacing: 5, textTransform: "uppercase", marginBottom: 4 }}>System · Core</div>
                            <h1 style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: 42, fontWeight: 700, color: "#fff", letterSpacing: "-0.02em", lineHeight: 1 }}>User Management</h1>
                        </div>
                        <div className="flex gap-4">
                            {/* Animated Refresh Button */}
                            <button className="admin-btn admin-btn--refresh" onClick={fetchData} disabled={isLoading} title="Refresh Data">
                                <RefreshCw className={`admin-btn__icon ${isLoading ? 'animate-spin' : ''}`} />
                            </button>

                            {/* Animated Add User Button */}
                            <button className="admin-btn admin-btn--add" onClick={() => setCreateDialogOpen(true)} title="Add User">
                                <UserPlus className="admin-btn__icon" />
                            </button>

                        </div>
                    </div>

                    {/* Stats Cards */}
                    {/* Stats Cards */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <Card className="bg-gray-900/50 border-red-500/30">
                            <CardContent className="pt-6">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="text-sm font-medium text-gray-400">Total Admins</p>
                                        <p className="text-3xl font-bold text-red-400">
                                            {Object.values(userRoles).filter(roles =>
                                                roles.some(role => role.name.toLowerCase() === 'admin')
                                            ).length}
                                        </p>
                                    </div>
                                    <Shield className="w-12 h-12 text-red-500/20" />
                                </div>
                            </CardContent>
                        </Card>
                        <Card className="bg-gray-900/50 border-green-500/30">
                            <CardContent className="pt-6">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="text-sm font-medium text-gray-400">Total Regular Users</p>
                                        <p className="text-3xl font-bold text-green-400">
                                            {users.filter(u =>
                                                !userRoles[u.user_id]?.some(role => role.name.toLowerCase() === 'admin')
                                            ).length}
                                        </p>
                                    </div>
                                    <UserPlus className="w-12 h-12 text-green-500/20" />
                                </div>
                            </CardContent>
                        </Card>
                        <Card className="bg-gray-900/50 border-blue-500/30">
                            <CardContent className="pt-6">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="text-sm font-medium text-gray-400">Total Accounts</p>
                                        <p className="text-3xl font-bold text-blue-400">{users.length}</p>
                                    </div>
                                    <UserPlus className="w-12 h-12 text-blue-500/20" />
                                </div>
                            </CardContent>
                        </Card>
                    </div>

                    {/* Users Table */}
                    <Card className="bg-gray-900/50 border-gray-800">
                        <CardContent className="p-0">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>User</TableHead>
                                        <TableHead>Email</TableHead>
                                        <TableHead>Last Login</TableHead>
                                        <TableHead className="text-right">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {users.map((user) => (
                                        <TableRow key={user.user_id}>
                                            <TableCell className="flex items-center gap-3">
                                                <Avatar className="h-10 w-10 ring-2 ring-gray-700">
                                                    <AvatarImage src={user.picture} />
                                                    <AvatarFallback className="bg-gradient-to-br from-blue-500 to-purple-600 text-white font-bold">
                                                        {user.nickname?.charAt(0).toUpperCase()}
                                                    </AvatarFallback>
                                                </Avatar>
                                                <div className="flex items-center gap-2">
                                                    <div>
                                                        <div className="flex items-center gap-2">
                                                            <span className="font-semibold text-base">{user.name || user.nickname}</span>
                                                            {userRoles[user.user_id]?.some(role => role.name.toLowerCase() === 'admin') && (
                                                                <Badge className="bg-gradient-to-r from-red-600 to-orange-600 text-white border-0 px-2 py-0.5 flex items-center gap-1">
                                                                    <Shield className="w-3 h-3" />
                                                                    <span className="text-xs font-bold">ADMIN</span>
                                                                </Badge>
                                                            )}
                                                        </div>
                                                        <div className="text-xs text-gray-500">{user.logins_count} logins</div>
                                                    </div>
                                                </div>
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex items-center gap-2">
                                                    <Mail className="w-3 h-3 text-gray-500" />
                                                    {user.email}
                                                </div>
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex items-center gap-2 text-sm text-gray-400">
                                                    <Calendar className="w-3 h-3" />
                                                    {user.last_login ? new Date(user.last_login).toLocaleDateString() : 'Never'}
                                                </div>
                                            </TableCell>
                                            <TableCell className="text-right">
                                                <div className="flex justify-end gap-2">
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        onClick={() => openUpdateDialog(user)}
                                                        className="bg-gradient-to-r from-blue-600/20 to-cyan-600/20 border-blue-500/50 hover:from-blue-600/30 hover:to-cyan-600/30 text-blue-400 hover:text-blue-300 font-semibold"
                                                        title="Update User"
                                                    >
                                                        <Edit className="w-4 h-4 mr-1" />
                                                        Update
                                                    </Button>
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        onClick={() => handleManageRoles(user)}
                                                        className="bg-gradient-to-r from-purple-600/20 to-pink-600/20 border-purple-500/50 hover:from-purple-600/30 hover:to-pink-600/30 text-purple-400 hover:text-purple-300 font-semibold"
                                                        title="Manage Roles"
                                                    >
                                                        <Shield className="w-4 h-4 mr-1" />
                                                        Roles
                                                    </Button>
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        className="bg-gradient-to-r from-red-600/20 to-orange-600/20 border-red-500/50 hover:from-red-600/30 hover:to-orange-600/30 text-red-400 hover:text-red-300 font-semibold"
                                                        onClick={() => { setUserToDelete(user); setDeleteDialogOpen(true); }}
                                                        title="Delete User"
                                                    >
                                                        <Trash2 className="w-4 h-4 mr-1" />
                                                        Delete
                                                    </Button>
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>

                    {/* Role Management Dialog */}
                    <Dialog open={roleDialogOpen} onOpenChange={setRoleDialogOpen}>
                        <DialogContent className="bg-gray-900 text-white border-gray-800">
                            <DialogHeader>
                                <DialogTitle>Manage Roles</DialogTitle>
                                <DialogDescription className="text-gray-400">
                                    Update roles for {selectedUser?.name || selectedUser?.email}
                                </DialogDescription>
                            </DialogHeader>
                            <div className="space-y-4 py-4">
                                {allRoles.map(role => (
                                    <div key={role.id} className="flex items-center space-x-2">
                                        <Checkbox
                                            id={role.id}
                                            checked={currentUserRoles.some(r => r.id === role.id)}
                                            onCheckedChange={(checked) => handleRoleToggle(role.id, !!checked)}
                                        />
                                        <label htmlFor={role.id} className="text-sm cursor-pointer">
                                            <div className="font-semibold">{role.name}</div>
                                            <div className="text-xs text-gray-500">{role.description}</div>
                                        </label>
                                    </div>
                                ))}
                            </div>
                            <DialogFooter>
                                <Button variant="outline" onClick={() => setRoleDialogOpen(false)}>Cancel</Button>
                                <Button onClick={saveRoles} disabled={isSavingRoles}>
                                    {isSavingRoles ? 'Saving...' : 'Save'}
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>

                    {/* Create User Dialog */}
                    <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
                        <DialogContent className="bg-gray-900 text-white border-gray-800">
                            <DialogHeader>
                                <DialogTitle>Create New User</DialogTitle>
                                <DialogDescription className="text-gray-400">
                                    Add a new user to the system
                                </DialogDescription>
                            </DialogHeader>
                            <div className="space-y-4 py-4">
                                <div className="space-y-2">
                                    <Label htmlFor="name">Name (Optional)</Label>
                                    <Input
                                        id="name"
                                        value={newUserName}
                                        onChange={(e) => setNewUserName(e.target.value)}
                                        className="bg-gray-800 border-gray-700"
                                        placeholder="John Doe"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label htmlFor="email">Email *</Label>
                                    <Input
                                        id="email"
                                        type="email"
                                        value={newUserEmail}
                                        onChange={(e) => setNewUserEmail(e.target.value)}
                                        className="bg-gray-800 border-gray-700"
                                        placeholder="user@example.com"
                                        required
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label htmlFor="password">Password *</Label>
                                    <Input
                                        id="password"
                                        type="password"
                                        value={newUserPassword}
                                        onChange={(e) => setNewUserPassword(e.target.value)}
                                        className="bg-gray-800 border-gray-700"
                                        placeholder="Minimum 8 characters"
                                        required
                                    />
                                </div>
                            </div>
                            <DialogFooter>
                                <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
                                <Button onClick={handleCreateUser} disabled={isCreating}>
                                    {isCreating ? 'Creating...' : 'Create User'}
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>

                    {/* Update User Dialog */}
                    <Dialog open={updateDialogOpen} onOpenChange={setUpdateDialogOpen}>
                        <DialogContent className="bg-gray-900 text-white border-gray-800">
                            <DialogHeader>
                                <DialogTitle>Update User</DialogTitle>
                                <DialogDescription className="text-gray-400">
                                    Update user information for {selectedUser?.email}
                                </DialogDescription>
                            </DialogHeader>
                            <div className="space-y-4 py-4">
                                <div className="space-y-2">
                                    <Label htmlFor="update-name">Name</Label>
                                    <Input
                                        id="update-name"
                                        value={updateName}
                                        onChange={(e) => setUpdateName(e.target.value)}
                                        className="bg-gray-800 border-gray-700"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label htmlFor="update-email">Email</Label>
                                    <Input
                                        id="update-email"
                                        type="email"
                                        value={updateEmail}
                                        onChange={(e) => setUpdateEmail(e.target.value)}
                                        className="bg-gray-800 border-gray-700"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label htmlFor="update-password">New Password (optional)</Label>
                                    <Input
                                        id="update-password"
                                        type="password"
                                        value={updatePassword}
                                        onChange={(e) => setUpdatePassword(e.target.value)}
                                        placeholder="Leave blank to keep current password"
                                        className="bg-gray-800 border-gray-700"
                                    />
                                </div>
                            </div>
                            <DialogFooter>
                                <Button variant="outline" onClick={() => setUpdateDialogOpen(false)}>Cancel</Button>
                                <Button onClick={handleUpdateUser} disabled={isUpdating}>
                                    {isUpdating ? 'Updating...' : 'Update User'}
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>

                    {/* Delete Confirmation Dialog */}
                    <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
                        <DialogContent className="bg-gray-900 text-white border-gray-800">
                            <DialogHeader>
                                <DialogTitle>Delete User</DialogTitle>
                                <DialogDescription className="text-gray-400">
                                    Are you sure you want to delete {userToDelete?.name || userToDelete?.email}? This action cannot be undone.
                                </DialogDescription>
                            </DialogHeader>
                            <DialogFooter>
                                <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>Cancel</Button>
                                <Button variant="destructive" onClick={handleDeleteUser} disabled={isDeleting}>
                                    {isDeleting ? 'Deleting...' : 'Delete User'}
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                </div>

                <style>{`
                @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=Outfit:wght@400;500;600;700&display=swap');
                
                /* ── Animated action buttons ── */
                .admin-btn {
                    width: 50px;
                    height: 50px;
                    border-radius: 50%;
                    border: none;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    box-shadow: 0 0 20px rgba(0,0,0,0.3);
                    cursor: pointer;
                    transition: width 0.3s ease, border-radius 0.3s ease, background-color 0.3s ease;
                    overflow: hidden;
                    position: relative;
                    font-family: 'Outfit', sans-serif;
                }
                .admin-btn__icon {
                    width: 20px;
                    height: 20px;
                    flex-shrink: 0;
                    transition: width 0.3s ease, height 0.3s ease, transform 0.3s ease;
                }
                .admin-btn::before {
                    position: absolute;
                    top: -20px;
                    content: attr(title);
                    color: #fff;
                    font-size: 0;
                    transition: font-size 0.2s ease, transform 0.3s ease, opacity 0.2s ease;
                    opacity: 0;
                    white-space: nowrap;
                    font-weight: 600;
                    letter-spacing: 0.5px;
                }

                /* REFRESH button */
                .admin-btn--refresh {
                    background-color: rgb(20, 20, 20);
                }
                .admin-btn--refresh .admin-btn__icon { color: white; }
                .admin-btn--refresh:hover {
                    width: 140px;
                    border-radius: 50px;
                    background-color: rgb(46, 213, 115);
                }
                .admin-btn--refresh:hover .admin-btn__icon {
                    width: 28px;
                    height: 28px;
                    transform: translateY(60%);
                }
                .admin-btn--refresh:hover::before {
                    content: 'Refresh';
                    font-size: 13px;
                    opacity: 1;
                    transform: translateY(30px);
                }

                /* ADD button */
                .admin-btn--add {
                    background-color: rgba(46, 213, 115, 0.15);
                    border: 1.5px solid rgba(46, 213, 115, 0.5) !important;
                }
                .admin-btn--add .admin-btn__icon { color: rgb(46, 213, 115); }
                .admin-btn--add:hover {
                    width: 140px;
                    border-radius: 50px;
                    background-color: rgb(46, 213, 115);
                }
                .admin-btn--add:hover .admin-btn__icon {
                    color: white;
                    width: 28px;
                    height: 28px;
                    transform: translateY(60%);
                }
                .admin-btn--add:hover::before {
                    content: 'Add User';
                    font-size: 13px;
                    opacity: 1;
                    transform: translateY(30px);
                }

 
            `}</style>
            </div>
        </DashboardLayout>
    );
};

export default AdminUsers;