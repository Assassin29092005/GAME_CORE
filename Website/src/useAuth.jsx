import { createContext, useContext, useEffect, useState } from "react";
import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut,
  updateProfile,
} from "firebase/auth";
import { auth, isConfigured } from "./firebase.js";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [demo, setDemo] = useState(() => sessionStorage.getItem("gc_demo") === "1");
  const [loading, setLoading] = useState(isConfigured);

  useEffect(() => {
    if (!isConfigured) return undefined;
    return onAuthStateChanged(auth, (u) => {
      setUser(u);
      setLoading(false);
    });
  }, []);

  const value = {
    user,
    demo,
    loading,
    isConfigured,
    enterDemo: () => {
      sessionStorage.setItem("gc_demo", "1");
      setDemo(true);
    },
    signIn: (email, password) => signInWithEmailAndPassword(auth, email, password),
    signUp: async (email, password, callsign) => {
      const cred = await createUserWithEmailAndPassword(auth, email, password);
      if (callsign) await updateProfile(cred.user, { displayName: callsign });
      return cred;
    },
    signOutUser: () => {
      sessionStorage.removeItem("gc_demo");
      setDemo(false);
      return isConfigured && auth?.currentUser ? signOut(auth) : Promise.resolve();
    },
  };

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
