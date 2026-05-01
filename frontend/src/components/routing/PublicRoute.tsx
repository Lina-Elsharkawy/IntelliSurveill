import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

interface PublicRouteProps {
    element: JSX.Element;
}

const PublicRoute = ({ element }: PublicRouteProps) => {
    const { isAuthenticated, roles } = useAuth();

    if (isAuthenticated) {
        if (roles.includes('admin')) {
            return <Navigate to="/admin-users" replace />;
        }
        return <Navigate to="/dashboard" replace />;
    }

    return element;
};

export default PublicRoute;
