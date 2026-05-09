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
import { createUser, assignRoles, Auth0Role } from "@/services/adminService";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

interface CreateUserDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    onSuccess: () => void;
    allRoles: Auth0Role[];
}

export function CreateUserDialog({ isOpen, onOpenChange, onSuccess, allRoles }: CreateUserDialogProps) {
    const { toast } = useToast();
    const [newUserEmail, setNewUserEmail] = useState("");
    const [newUserPassword, setNewUserPassword] = useState("");
    const [newUserName, setNewUserName] = useState("");
    const [selectedRoleId, setSelectedRoleId] = useState<string>("");
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
            const user = await createUser(newUserEmail, newUserPassword, newUserName || undefined);
            
            // Assign role if one is selected
            if (selectedRoleId) {
                await assignRoles(user.user_id, [selectedRoleId]);
            }

            onOpenChange(false);
            setNewUserEmail("");
            setNewUserPassword("");
            setNewUserName("");
            setSelectedRoleId("");
            toast({ title: "Success", description: "User created and role assigned successfully." });
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

                    <div className="space-y-3">
                        <Label>Assign System Role *</Label>
                        <RadioGroup 
                            value={selectedRoleId} 
                            onValueChange={setSelectedRoleId}
                            className="grid grid-cols-1 gap-2"
                        >
                            {allRoles
                                .filter(r => ['admin', 'user'].includes(r.name.toLowerCase()))
                                .map((role) => (
                                <div
                                    key={role.id}
                                    className={`flex items-center space-x-3 p-3 rounded-lg border transition-all cursor-pointer ${
                                        selectedRoleId === role.id 
                                            ? "bg-primary/10 border-primary/50 shadow-[0_0_10px_rgba(46,213,115,0.1)]" 
                                            : "bg-gray-800/50 border-gray-700 hover:bg-gray-800"
                                    }`}
                                    onClick={() => setSelectedRoleId(role.id)}
                                >
                                    <RadioGroupItem
                                        value={role.id}
                                        id={`role-${role.id}`}
                                        className="border-gray-500"
                                    />
                                    <Label
                                        htmlFor={`role-${role.id}`}
                                        className="text-sm font-semibold cursor-pointer flex-1"
                                    >
                                        {role.name}
                                        <p className="text-[10px] text-gray-500 font-normal mt-0.5">{role.description}</p>
                                    </Label>
                                </div>
                            ))}
                        </RadioGroup>
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
