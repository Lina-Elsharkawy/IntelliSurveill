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
    Auth0User,
    Auth0Role
} from "@/services/adminService";
import { CreateUserDialog } from "@/components/admin/users/CreateUserDialog";
import { UpdateUserDialog } from "@/components/admin/users/UpdateUserDialog";
import { ManageRolesDialog } from "@/components/admin/users/ManageRolesDialog";
import { DeleteUserDialog } from "@/components/admin/users/DeleteUserDialog";

const AdminUsers = () => {
    const { toast } = useToast();
    const [users, setUsers] = useState<Auth0User[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [allRoles, setAllRoles] = useState<Auth0Role[]>([]);
    const [selectedUser, setSelectedUser] = useState<Auth0User | null>(null);
    const [roleDialogOpen, setRoleDialogOpen] = useState(false);
    const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
    const [userToDelete, setUserToDelete] = useState<Auth0User | null>(null);
    const [createDialogOpen, setCreateDialogOpen] = useState(false);
    const [updateDialogOpen, setUpdateDialogOpen] = useState(false);
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

    const handleManageRoles = (user: Auth0User) => {
        setSelectedUser(user);
        setRoleDialogOpen(true);
    };



    const openUpdateDialog = (user: Auth0User) => {
        setSelectedUser(user);
        setUpdateDialogOpen(true);
    };

    return (
        <DashboardLayout>
            <div className="admin-users-page min-h-screen p-8" style={{ background: "#050505", color: "#fff" }}>
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
                    <ManageRolesDialog
                        isOpen={roleDialogOpen}
                        onOpenChange={setRoleDialogOpen}
                        user={selectedUser}
                        allRoles={allRoles}
                        onSuccess={fetchData}
                    />

                    <CreateUserDialog
                        isOpen={createDialogOpen}
                        onOpenChange={setCreateDialogOpen}
                        onSuccess={fetchData}
                    />

                    <UpdateUserDialog
                        isOpen={updateDialogOpen}
                        onOpenChange={setUpdateDialogOpen}
                        user={selectedUser}
                        onSuccess={fetchData}
                    />

                    <DeleteUserDialog
                        isOpen={deleteDialogOpen}
                        onOpenChange={setDeleteDialogOpen}
                        user={userToDelete}
                        onSuccess={(deletedId) => {
                            setUsers(prev => prev.filter(u => u.user_id !== deletedId));
                        }}
                    />
                </div>
            </div>
        </DashboardLayout>
    );
};

export default AdminUsers;