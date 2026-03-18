import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

interface PrivateRouteProps {
    element: JSX.Element;
}

const PrivateRoute = ({ element }: PrivateRouteProps) => {
    const { isAuthenticated, roles } = useAuth();

    if (!isAuthenticated) return <Navigate to="/login" replace />;

    // If user is admin, they shouldn't access regular user routes
    if (roles && roles.includes('admin')) {
        return <Navigate to="/admin-users" replace />;
    }

    return element;
};

export default PrivateRoute;
