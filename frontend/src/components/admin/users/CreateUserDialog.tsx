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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/use-toast";
import { createUser } from "@/services/adminService";

interface CreateUserDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    onSuccess: () => void;
}

export function CreateUserDialog({ isOpen, onOpenChange, onSuccess }: CreateUserDialogProps) {
    const { toast } = useToast();
    const [newUserEmail, setNewUserEmail] = useState("");
    const [newUserPassword, setNewUserPassword] = useState("");
    const [newUserName, setNewUserName] = useState("");
    const [isCreating, setIsCreating] = useState(false);

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
            await createUser(newUserEmail, newUserPassword, newUserName || undefined);
            onOpenChange(false);
            setNewUserEmail("");
            setNewUserPassword("");
            setNewUserName("");
            toast({ title: "Success", description: "User created successfully." });
            onSuccess();
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

    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
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
                    <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
                    <Button onClick={handleCreateUser} disabled={isCreating}>
                        {isCreating ? 'Creating...' : 'Create User'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
