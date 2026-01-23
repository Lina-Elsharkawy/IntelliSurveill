import React, { createContext, useContext, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";

interface AuthContextType {
    user: any | null; // Replace 'any' with your User type if available
    token: string | null;
    login: (token: string, userData?: any) => void;
    logout: () => void;
    isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
    // Initialize state synchronously from localStorage to prevent redirect on refresh
    const [token, setToken] = useState<string | null>(() => localStorage.getItem("access_token"));
    const [user, setUser] = useState<any | null>(() => {
        const savedUser = localStorage.getItem("user_data");
        return savedUser ? JSON.parse(savedUser) : null;
    });

    const navigate = useNavigate();

    const login = (newToken: string, userData?: any) => {
        localStorage.setItem("access_token", newToken);
        if (userData) {
            localStorage.setItem("user_data", JSON.stringify(userData));
            setUser(userData);
        }
        setToken(newToken);
        navigate("/dashboard");
    };

    const logout = () => {
        localStorage.removeItem("access_token");
        localStorage.removeItem("user_data");
        localStorage.removeItem("id_token");
        localStorage.removeItem("loggedIn");
        setToken(null);
        setUser(null);
        navigate("/login");
    };

    useEffect(() => {
        const handleUnauthorized = () => logout();
        window.addEventListener('auth:unauthorized', handleUnauthorized);
        return () => window.removeEventListener('auth:unauthorized', handleUnauthorized);
    }, [navigate]);

    const isAuthenticated = !!token;

    return (
        <AuthContext.Provider value={{ user, token, login, logout, isAuthenticated }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error("useAuth must be used within an AuthProvider");
    }
    return context;
};
