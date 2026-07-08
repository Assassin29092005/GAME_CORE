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
  apiKey: "AIzaSyB2lwikxfS9IANzD_YzFtPQZBf0oF3uFHc",
  authDomain: "game-4cedf.firebaseapp.com",
  projectId: "game-4cedf",
  storageBucket: "game-4cedf.firebasestorage.app",
  messagingSenderId: "551713539905",
  appId: "1:551713539905:web:8dc818086a9ee5465903c0",
  measurementId: "G-GZ7S17R815"
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
