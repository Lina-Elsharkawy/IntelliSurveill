import React, { createContext, useContext, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { jwtDecode } from "jwt-decode";

interface AuthContextType {
    user: any | null;
    token: string | null;
    roles: string[];
    login: (token: string, idToken?: string) => void;
    logout: () => void;
    isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
    const navigate = useNavigate();
    const [token, setToken] = useState<string | null>(() => localStorage.getItem("access_token"));
    const [idToken, setIdToken] = useState<string | null>(() => localStorage.getItem("id_token"));
    const [user, setUser] = useState<any | null>(null);
    const [roles, setRoles] = useState<string[]>(() => {
        const t = localStorage.getItem("id_token");
        if (t) {
            try {
                const decoded: any = jwtDecode(t);
                let extracted = decoded["https://myapp.com/roles"] || decoded.roles || [];
                if (typeof extracted === 'string') extracted = [extracted];
                let finalRoles = Array.isArray(extracted) ? extracted : [];

                return finalRoles;
            } catch (e) {
                return [];
            }
        }
        return [];
    });

    useEffect(() => {
        if (idToken) {
            try {
                const decoded: any = jwtDecode(idToken);
                setUser(decoded);

                let extractedRoles = decoded["https://myapp.com/roles"] || decoded.roles || [];

                if (typeof extractedRoles === 'string') {
                    extractedRoles = [extractedRoles];
                } else if (!Array.isArray(extractedRoles)) {
                    extractedRoles = [];
                }

                setRoles(extractedRoles);
            } catch (err) {
                console.error("Invalid id_token", err);
            }
        }
    }, [idToken]);

    const login = (accessToken: string, newIdToken?: string) => {
        localStorage.setItem("access_token", accessToken);
        setToken(accessToken);

        if (newIdToken) {
            localStorage.setItem("id_token", newIdToken);
            setIdToken(newIdToken);

            try {
                const decoded: any = jwtDecode(newIdToken);

                // Try multiple paths for roles
                let userRoles = decoded["https://myapp.com/roles"] || decoded.roles || [];

                // Handle case where roles is a string

                // Handle case where roles is a string
                if (typeof userRoles === 'string') {
                    userRoles = [userRoles];
                }

                // Ensure it's an array
                if (!Array.isArray(userRoles)) {
                    userRoles = [];
                }

                setRoles(userRoles);

                if (userRoles.includes('admin')) {
                    navigate("/admin-users");
                    return;
                }
            } catch (e) {
                console.error("Error decoding id_token during login", e);
            }
        }

        navigate("/dashboard");
    };

    const logout = () => {
        localStorage.removeItem("access_token");
        localStorage.removeItem("id_token");
        setToken(null);
        setIdToken(null);
        setUser(null);
        setRoles([]);
        window.location.href = "/login"; // hard redirect
    };

    const isAuthenticated = !!token;

    return (
        <AuthContext.Provider value={{ user, token, roles, login, logout, isAuthenticated }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) throw new Error("useAuth must be used within an AuthProvider");
    return context;
};
