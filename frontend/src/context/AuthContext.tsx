import React, { createContext, useContext, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";

interface AuthContextType {
    user: any | null;
    token: string | null;
    login: (token: string, userData?: any) => void;
    logout: () => void;
    isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

import { jwtDecode } from "jwt-decode";

// Helper to decode JWT token to check expiration using library
function isTokenExpired(token: string): boolean {
    try {
        const decoded: any = jwtDecode(token);
        if (!decoded.exp) return false;

        return Date.now() >= decoded.exp * 1000;
    } catch (e) {
        return true; // Treat invalid token as expired
    }
}

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
    // Initialize state synchronously from localStorage to prevent redirect on refresh
    const [token, setToken] = useState<string | null>(() => {
        const t = localStorage.getItem("access_token");
        if (t && t !== "null" && t !== "undefined") {
            if (isTokenExpired(t)) {
                localStorage.removeItem("access_token");
                localStorage.removeItem("user_data");
                localStorage.removeItem("id_token");
                localStorage.removeItem("loggedIn");
                return null;
            }
            return t;
        }
        return null;
    });

    const [user, setUser] = useState<any | null>(() => {
        const savedUser = localStorage.getItem("user_data");
        return (savedUser && savedUser !== "null" && savedUser !== "undefined") ? JSON.parse(savedUser) : null;
    });

    const navigate = useNavigate();

    const login = (newToken: string, userData?: any) => {
        if (!newToken) return;

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
        // Force a hard redirect to ensure state is cleared completely
        window.location.href = "/login";
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
