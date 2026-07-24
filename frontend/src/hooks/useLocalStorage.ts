"use client";

import { useState, useEffect } from "react";

export function useLocalStorage<T>(key: string, initialValue: T) {
  const [storedValue, setStoredValue] = useState<T>(initialValue);
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    try {
      const item = window.localStorage.getItem(key);
      if (item) {
        try {
          // Attempt strict JSON parsing
          setStoredValue(JSON.parse(item));
        } catch (parseError) {
          // Fallback: If it is a legacy raw string (like "Dark"), use it and repair storage
          console.warn(`Repairing malformed JSON in localStorage for key "${key}"`);
          setStoredValue(item as unknown as T);
          window.localStorage.setItem(key, JSON.stringify(item));
        }
      } else {
        window.localStorage.setItem(key, JSON.stringify(initialValue));
      }
    } catch (error) {
      console.warn(`Error reading localStorage key "${key}":`, error);
    }
    setIsLoaded(true);
  }, [key]); 

  const setValue = (value: T | ((val: T) => T)) => {
    try {
      const valueToStore = value instanceof Function ? value(storedValue) : value;
      setStoredValue(valueToStore);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(key, JSON.stringify(valueToStore));
      }
    } catch (error) {
      console.warn(`Error setting localStorage key "${key}":`, error);
      if (error instanceof DOMException && error.name === 'QuotaExceededError') {
         alert("Local storage quota exceeded. Please clear some data.");
      }
    }
  };

  return [storedValue, setValue, isLoaded] as const;
}