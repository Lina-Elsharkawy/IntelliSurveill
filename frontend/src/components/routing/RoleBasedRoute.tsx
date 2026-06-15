import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

interface Props {
    element: JSX.Element;
    allowedRoles: string[];
}

const RoleBasedRoute = ({ element, allowedRoles }: Props) => {
    const { isAuthenticated, roles } = useAuth();

    if (!isAuthenticated) return <Navigate to="/login" replace />;

    const hasAccess = roles ? roles.some(role => allowedRoles.includes(role)) : false;

    return hasAccess ? element : <Navigate to="/analytics" replace />;
};

export default RoleBasedRoute;
