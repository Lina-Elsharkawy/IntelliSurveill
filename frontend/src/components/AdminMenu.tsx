import { LogOut, User } from "lucide-react";
import { useNavigate } from "react-router-dom";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";

const AdminMenu = () => {
  const navigate = useNavigate();

  const handleLogout = () => {
    // 1️⃣ Clear authentication data
    localStorage.removeItem("authToken"); 
    localStorage.removeItem("user");

    // 2️⃣ Redirect to login
    navigate("/login");
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {/* Admin Icon */}
        <Avatar className="cursor-pointer">
          <AvatarFallback className="bg-green-500 text-white">
            A
          </AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuItem className="flex gap-2">
          <User size={16} />
          Profile
        </DropdownMenuItem>

        <DropdownMenuItem
          onClick={handleLogout}
          className="flex gap-2 text-red-500 focus:text-red-500"
        >
          <LogOut size={16} />
          Logout
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default AdminMenu;