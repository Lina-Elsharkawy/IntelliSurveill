import { Navigate } from "react-router-dom";

interface PrivateRouteProps {
    element: JSX.Element;
    isAuthenticated: boolean;
}

const PrivateRoute = ({ element, isAuthenticated }: PrivateRouteProps) => {
    return isAuthenticated ? element : <Navigate to="/login" replace />;
};

export default PrivateRoute;
