import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import { jwtDecode } from 'jwt-decode';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    const fetchUser = async (tokenData) => {
      try {
        const API_URL = import.meta.env.VITE_API_BASE_URL || '/api';
        const response = await axios.get(`${API_URL}/users/me`);
        const fullUser = { ...tokenData, ...response.data };
        // Ensure _id exists (compatibility between JWT and API aliases)
        if (!fullUser._id && fullUser.id) fullUser._id = fullUser.id;
        setUser(fullUser);
      } catch (err) {
        console.error("Profile fetch error:", err);
      }
    };

    if (token) {
      try {
        const decoded = jwtDecode(token);
        if (decoded.exp * 1000 < Date.now()) {
          logout();
        } else {
          setUser(decoded); // Immediate load from token
          axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
          fetchUser(decoded); // Background load full profile
        }
      } catch (err) {
        logout();
      }
    }
    setLoading(false);
  }, []);

  const login = async (username, password) => {
    const formData = new FormData();
    formData.append('username', username);
    formData.append('password', password);

    const API_URL = import.meta.env.VITE_API_BASE_URL || '/api';
    const response = await axios.post(`${API_URL}/auth/token`, formData);
    const { access_token } = response.data;

    localStorage.setItem('token', access_token);
    const decoded = jwtDecode(access_token);
    setUser(decoded);
    axios.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
    
    // Fetch full profile info
    try {
      const profileResponse = await axios.get(`${API_URL}/users/me`);
      const fullUser = { ...decoded, ...profileResponse.data };
      if (!fullUser._id && fullUser.id) fullUser._id = fullUser.id;
      setUser(fullUser);
    } catch (err) {
      console.error("Full profile fetch failed after login", err);
    }
    
    return decoded;
  };

  const logout = () => {
    localStorage.removeItem('token');
    setUser(null);
    delete axios.defaults.headers.common['Authorization'];
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, loading }}>
      {!loading && children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
