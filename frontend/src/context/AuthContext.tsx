import React, { createContext, useContext, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { jwtDecode } from "jwt-decode";

interface AuthContextType {
    user: any | null;
    token: string | null;
    roles: string[];
    login: (token: string, idToken?: string) => void;
    logout: () => void;
    updateUserLocally: (updatedData: any) => void;
    isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * Extracts roles from a decoded JWT token.
 * Handles multiple possible claim locations and normalizes to string[].
 */
function extractRolesFromToken(token: string): string[] {
    try {
        const decoded: any = jwtDecode(token);
        let roles = decoded["https://myapp.com/roles"] || decoded.roles || [];
        if (typeof roles === 'string') roles = [roles];
        if (!Array.isArray(roles)) roles = [];
        return roles;
    } catch {
        return [];
    }
}

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
    const navigate = useNavigate();
    const [token, setToken] = useState<string | null>(() => localStorage.getItem("access_token"));
    const [idToken, setIdToken] = useState<string | null>(() => localStorage.getItem("id_token"));
    const [user, setUser] = useState<any | null>(null);
    const [roles, setRoles] = useState<string[]>(() => {
        const t = localStorage.getItem("id_token");
        return t ? extractRolesFromToken(t) : [];
    });

    useEffect(() => {
        if (idToken) {
            try {
                const decoded: any = jwtDecode(idToken);
                setUser(decoded);
                setRoles(extractRolesFromToken(idToken));
            } catch (err) {
                console.error("Invalid id_token", err);
            }
        }
    }, [idToken]);

    useEffect(() => {
        const handleUnauthorized = () => {
            logout();
        };

        window.addEventListener('auth:unauthorized', handleUnauthorized);
        return () => window.removeEventListener('auth:unauthorized', handleUnauthorized);
    }, []);

    const login = (accessToken: string, newIdToken?: string) => {
        localStorage.setItem("access_token", accessToken);
        setToken(accessToken);

        if (newIdToken) {
            localStorage.setItem("id_token", newIdToken);
            setIdToken(newIdToken);

            try {
                setRoles(extractRolesFromToken(newIdToken));
            } catch (e) {
                console.error("Error decoding id_token during login", e);
            }
        }
        navigate("/dashboard");
    };

    const logout = () => {
        localStorage.removeItem("access_token");
        localStorage.removeItem("id_token");
        localStorage.removeItem("chat_history");
        setToken(null);
        setIdToken(null);
        setUser(null);
        setRoles([]);
        window.location.href = "/login"; // hard redirect
    };

    const updateUserLocally = (updatedData: any) => {
        setUser((prev: any) => ({
            ...prev,
            ...updatedData
        }));
    };

    const isAuthenticated = !!token;

    return (
        <AuthContext.Provider value={{ user, token, roles, login, logout, updateUserLocally, isAuthenticated }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) throw new Error("useAuth must be used within an AuthProvider");
    return context;
};
