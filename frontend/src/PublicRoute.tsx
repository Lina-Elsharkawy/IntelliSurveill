import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

interface PublicRouteProps {
    element: JSX.Element;
}

const PublicRoute = ({ element }: PublicRouteProps) => {
    const { isAuthenticated } = useAuth();
    return isAuthenticated ? <Navigate to="/dashboard" replace /> : element;
};

export default PublicRoute;
