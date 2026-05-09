import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { useToast } from "@/components/ui/use-toast";
import { updateRoles, getUserRoles, Auth0User, Auth0Role } from "@/services/adminService";

interface ManageRolesDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    user: Auth0User | null;
    allRoles: Auth0Role[];
    onSuccess: () => void;
}

export function ManageRolesDialog({ isOpen, onOpenChange, user, allRoles, onSuccess }: ManageRolesDialogProps) {
    const { toast } = useToast();
    const [currentUserRoles, setCurrentUserRoles] = useState<Auth0Role[]>([]);
    const [isSavingRoles, setIsSavingRoles] = useState(false);
    const [isLoadingRoles, setIsLoadingRoles] = useState(false);

    useEffect(() => {
        const fetchCurrentRoles = async () => {
            if (user && isOpen) {
                setIsLoadingRoles(true);
                try {
                    const roles = await getUserRoles(user.user_id);
                    setCurrentUserRoles(roles);
                } catch (error) {
                    toast({ title: "Error", description: "Failed to fetch user roles.", variant: "destructive" });
                } finally {
                    setIsLoadingRoles(false);
                }
            } else {
                setCurrentUserRoles([]);
            }
        };
        fetchCurrentRoles();
    }, [user, isOpen, toast]);

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
        if (!user) return;
        setIsSavingRoles(true);
        try {
            const originalRoles = await getUserRoles(user.user_id);
            const originalIds = originalRoles.map(r => r.id);
            const currentIds = currentUserRoles.map(r => r.id);

            // Calculate roles to remove (all previous roles that are not the new one)
            const toAdd = currentIds.filter(id => !originalIds.includes(id));
            const toRemove = originalIds.filter(id => !currentIds.includes(id));

            // Execute single update to sync roles and audit log properly
            if (toRemove.length > 0 || toAdd.length > 0) {
                const oldRoleNames = originalRoles.map(r => r.name);
                const newRoleNames = currentUserRoles.map(r => r.name);
                
                await updateRoles(user.user_id, {
                    addRoles: toAdd,
                    removeRoles: toRemove,
                    oldRoleNames,
                    newRoleNames
                });
            }

            toast({ title: "Success", description: "Roles updated." });
            onOpenChange(false);
            onSuccess(); // Refresh parents
        } catch (error) {
            toast({ title: "Error", description: "Failed to update roles.", variant: "destructive" });
        } finally {
            setIsSavingRoles(false);
        }
    };

    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className="bg-gray-900 text-white border-gray-800">
                <DialogHeader>
                    <DialogTitle>Manage Roles</DialogTitle>
                    <DialogDescription className="text-gray-400">
                        Update roles for {user?.name || user?.email}
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-4 py-4">
                    {isLoadingRoles ? (
                        <div className="text-center text-gray-500 py-4">Loading roles...</div>
                    ) : (
                        allRoles.map(role => (
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
                        ))
                    )}
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
                    <Button onClick={saveRoles} disabled={isSavingRoles || isLoadingRoles}>
                        {isSavingRoles ? 'Saving...' : 'Save'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
