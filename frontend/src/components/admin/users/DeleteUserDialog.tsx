import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/use-toast";
import { deleteUser, Auth0User } from "@/services/adminService";

interface DeleteUserDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    user: Auth0User | null;
    onSuccess: (deletedUserId: string) => void;
}

export function DeleteUserDialog({ isOpen, onOpenChange, user, onSuccess }: DeleteUserDialogProps) {
    const { toast } = useToast();
    const [isDeleting, setIsDeleting] = useState(false);

    const handleDeleteUser = async () => {
        if (!user) return;
        setIsDeleting(true);
        try {
            await deleteUser(user.user_id);
            toast({ title: "Success", description: "User deleted." });
            onOpenChange(false);
            onSuccess(user.user_id);
        } catch (error) {
            toast({ title: "Error", description: "Failed to delete user.", variant: "destructive" });
        } finally {
            setIsDeleting(false);
        }
    };

    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className="bg-gray-900 text-white border-gray-800">
                <DialogHeader>
                    <DialogTitle>Delete User</DialogTitle>
                    <DialogDescription className="text-gray-400">
                        Are you sure you want to delete {user?.name || user?.email}? This action cannot be undone.
                    </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
                    <Button variant="destructive" onClick={handleDeleteUser} disabled={isDeleting}>
                        {isDeleting ? 'Deleting...' : 'Delete User'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
