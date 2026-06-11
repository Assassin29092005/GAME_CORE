import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

// ─────────────────────────────────────────────────────────────────────────────
// Paste your Firebase web-app config here.
// Firebase console → Project settings → General → Your apps → Web app → Config.
// Until you do, the site runs in DEMO MODE (no login, sample data) so you can
// develop and preview everything locally.
// ─────────────────────────────────────────────────────────────────────────────
export const firebaseConfig = {
  apiKey: "PASTE_API_KEY",
  authDomain: "PASTE_PROJECT.firebaseapp.com",
  projectId: "PASTE_PROJECT_ID",
  storageBucket: "PASTE_PROJECT.appspot.com",
  messagingSenderId: "PASTE_SENDER_ID",
  appId: "PASTE_APP_ID",
};

export const isConfigured = !/^PASTE_/.test(firebaseConfig.apiKey);

let auth = null;
let db = null;

if (isConfigured) {
  const app = initializeApp(firebaseConfig);
  auth = getAuth(app);
  db = getFirestore(app);
}

export { auth, db };
