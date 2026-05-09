import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { DashboardLayout } from "@/components/DashboardLayout";
import {
    Users,
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
            <div className="admin-users-page w-full space-y-6">
                {/* Header */}
                <div className="flex justify-between items-center mb-8 mt-2">
                    <div>
                        <h1 style={{ fontFamily: "'Montserrat', sans-serif", fontSize: 36, fontWeight: 700, color: "#fff", lineHeight: 1.1 }}>
                            User Management
                        </h1>
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

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <Card className="shadow-card border-border bg-gradient-to-br from-card to-card/80 overflow-hidden relative">
                        <div className="absolute top-0 right-0 p-4 opacity-10">
                            <Shield className="w-16 h-16" />
                        </div>
                        <CardContent className="pt-6">
                            <div className="flex flex-col">
                                <span className="text-sm font-medium text-muted-foreground mb-1">Total Admins</span>
                                <span className="text-3xl font-bold text-red-500">
                                    {Object.values(userRoles).filter(roles =>
                                        roles.some(role => role.name.toLowerCase() === 'admin')
                                    ).length}
                                </span>
                            </div>
                        </CardContent>
                    </Card>

                    <Card className="shadow-card border-border bg-gradient-to-br from-card to-card/80 overflow-hidden relative">
                        <div className="absolute top-0 right-0 p-4 opacity-10">
                            <Users className="w-16 h-16" />
                        </div>
                        <CardContent className="pt-6">
                            <div className="flex flex-col">
                                <span className="text-sm font-medium text-muted-foreground mb-1">Regular Users</span>
                                <span className="text-3xl font-bold text-green-500">
                                    {users.filter(u =>
                                        !userRoles[u.user_id]?.some(role => role.name.toLowerCase() === 'admin')
                                    ).length}
                                </span>
                            </div>
                        </CardContent>
                    </Card>

                    <Card className="shadow-card border-border bg-gradient-to-br from-card to-card/80 overflow-hidden relative">
                        <div className="absolute top-0 right-0 p-4 opacity-10">
                            <UserPlus className="w-16 h-16" />
                        </div>
                        <CardContent className="pt-6">
                            <div className="flex flex-col">
                                <span className="text-sm font-medium text-muted-foreground mb-1">Total Accounts</span>
                                <span className="text-3xl font-bold text-blue-500">{users.length}</span>
                            </div>
                        </CardContent>
                    </Card>
                </div>

                {/* Users Table */}
                <Card className="shadow-card border-border bg-card">
                    <CardContent className="p-0">
                        <Table>
                            <TableHeader className="bg-secondary/30">
                                <TableRow className="border-border hover:bg-transparent">
                                    <TableHead className="text-foreground font-semibold">User</TableHead>
                                    <TableHead className="text-foreground font-semibold">Email</TableHead>
                                    <TableHead className="text-foreground font-semibold">Last Login</TableHead>
                                    <TableHead className="text-right text-foreground font-semibold pr-6">Actions</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {users.map((user) => (
                                    <TableRow key={user.user_id} className="border-border hover:bg-secondary/20 transition-colors">
                                        <TableCell className="py-4">
                                            <div className="flex items-center gap-3">
                                                <Avatar className="h-10 w-10 ring-2 ring-border shadow-sm">
                                                    <AvatarImage src={user.picture} />
                                                    <AvatarFallback className="bg-gradient-to-br from-primary to-primary/60 text-white font-bold">
                                                        {user.nickname?.charAt(0).toUpperCase()}
                                                    </AvatarFallback>
                                                </Avatar>
                                                <div className="flex flex-col">
                                                    <div className="flex items-center gap-2">
                                                        <span className="font-semibold text-foreground">{user.name || user.nickname}</span>
                                                        {userRoles[user.user_id]?.some(role => role.name.toLowerCase() === 'admin') && (
                                                            <Badge className="bg-red-500/10 text-red-500 border-red-500/20 px-2 py-0.5 flex items-center gap-1 hover:bg-red-500/20 transition-colors">
                                                                <Shield className="w-3 h-3" />
                                                                <span className="text-[10px] font-bold tracking-wider">ADMIN</span>
                                                            </Badge>
                                                        )}
                                                    </div>
                                                    <span className="text-xs text-muted-foreground">{user.logins_count} total logins</span>
                                                </div>
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                                <Mail className="w-3.5 h-3.5 text-primary/60" />
                                                {user.email}
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                                <Calendar className="w-3.5 h-3.5 text-primary/60" />
                                                {user.last_login ? new Date(user.last_login).toLocaleDateString() : 'Never'}
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-right pr-6">
                                            <div className="flex justify-end gap-2">
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    onClick={() => openUpdateDialog(user)}
                                                    className="border-blue-500/20 text-blue-400 hover:bg-blue-500/10 hover:border-blue-500/40 transition-all"
                                                    title="Update User"
                                                >
                                                    <Edit className="w-3.5 h-3.5 mr-1.5" />
                                                    Edit
                                                </Button>
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    onClick={() => handleManageRoles(user)}
                                                    className="border-indigo-500/20 text-indigo-400 hover:bg-indigo-500/10 hover:border-indigo-500/40 transition-all"
                                                    title="Manage Roles"
                                                >
                                                    <Shield className="w-3.5 h-3.5 mr-1.5" />
                                                    Roles
                                                </Button>
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    className="border-red-500/20 text-red-500 hover:bg-red-500/10 hover:border-red-500/40 transition-all"
                                                    onClick={() => { setUserToDelete(user); setDeleteDialogOpen(true); }}
                                                    title="Delete User"
                                                >
                                                    <Trash2 className="w-3.5 h-3.5 mr-1.5" />
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
                    allRoles={allRoles}
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
        </DashboardLayout>
    );
};

export default AdminUsers;