import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

interface PrivateRouteProps {
    element: JSX.Element;
}

const PrivateRoute = ({ element }: PrivateRouteProps) => {
    const { isAuthenticated, roles } = useAuth();

    if (!isAuthenticated) return <Navigate to="/login" replace />;

    // Admins are naturally also users, so they are allowed to access regular user routes.

    return element;
};

export default PrivateRoute;
