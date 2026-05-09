import { useState, useEffect } from "react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/use-toast";
import { updateUser, Auth0User } from "@/services/adminService";

interface UpdateUserDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    user: Auth0User | null;
    onSuccess: () => void;
}

export function UpdateUserDialog({ isOpen, onOpenChange, user, onSuccess }: UpdateUserDialogProps) {
    const { toast } = useToast();
    const { user: currentUser, updateUserLocally } = useAuth();
    const [updateEmail, setUpdateEmail] = useState("");
    const [updateName, setUpdateName] = useState("");
    const [updatePassword, setUpdatePassword] = useState("");
    const [isUpdating, setIsUpdating] = useState(false);

    useEffect(() => {
        if (user && isOpen) {
            setUpdateEmail(user.email);
            setUpdateName(user.name || "");
            setUpdatePassword("");
        }
    }, [user, isOpen]);

    const handleUpdateUser = async () => {
        if (!user) return;

        setIsUpdating(true);
        try {
            const updateData: { email?: string; name?: string; password?: string } = {};

            if (updateEmail && updateEmail !== user.email) {
                updateData.email = updateEmail;
            }
            if (updateName && updateName !== user.name) {
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
                onOpenChange(false);
                return;
            }

            await updateUser(user.user_id, updateData);
            
            // If the updated user is the current logged-in user, update the context
            if (currentUser && currentUser.sub === user.user_id) {
                updateUserLocally({
                    name: updateName || updateData.name,
                    email: updateEmail || updateData.email
                });
            }

            toast({ title: "Success", description: "User updated successfully." });
            onOpenChange(false);
            onSuccess();
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
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className="bg-gray-900 text-white border-gray-800">
                <DialogHeader>
                    <DialogTitle>Update User</DialogTitle>
                    <DialogDescription className="text-gray-400">
                        Update user information for {user?.email}
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
                    <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
                    <Button onClick={handleUpdateUser} disabled={isUpdating}>
                        {isUpdating ? 'Updating...' : 'Update User'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
