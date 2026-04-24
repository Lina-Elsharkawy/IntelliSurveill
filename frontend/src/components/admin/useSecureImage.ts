import { useState, useRef, useEffect } from "react";

export function useSecureImage() {
  const [imageUrls, setImageUrls] = useState<Record<string, string>>({});
  const [imageErrors, setImageErrors] = useState<Record<string, string>>({});
  const imageUrlsRef = useRef<Record<string, string>>({});

  const getAccessToken = (): string | null => {
    return (
      localStorage.getItem("access_token") ||
      localStorage.getItem("token") ||
      sessionStorage.getItem("access_token") ||
      sessionStorage.getItem("token")
    );
  };

  const fetchImage = async (
    key: string,
    endpoint: string
  ): Promise<string | null> => {
    try {
      if (imageUrlsRef.current[key]) {
        return imageUrlsRef.current[key];
      }

      const token = getAccessToken();
      if (!token) {
        console.warn(`No access token found for image key ${key}`);
        setImageErrors((prev) => ({ ...prev, [key]: "Missing token" }));
        return null;
      }

      const resp = await fetch(endpoint, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
        cache: "no-store",
      });

      if (!resp.ok) {
        console.error(
          `Image fetch failed for key ${key}:`,
          resp.status,
          resp.statusText
        );
        setImageErrors((prev) => ({
          ...prev,
          [key]: `${resp.status} ${resp.statusText}`,
        }));
        return null;
      }

      const blob = await resp.blob();
      const objectUrl = URL.createObjectURL(blob);

      setImageUrls((prev) => {
        if (prev[key]) {
          try {
            URL.revokeObjectURL(prev[key]);
          } catch {
            // ignore revoke failures
          }
        }
        const next = { ...prev, [key]: objectUrl };
        imageUrlsRef.current = next;
        return next;
      });

      setImageErrors((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });

      return objectUrl;
    } catch (err) {
      console.error(`Error fetching image for key ${key}:`, err);
      setImageErrors((prev) => ({ ...prev, [key]: "Fetch error" }));
      return null;
    }
  };

  useEffect(() => {
    return () => {
      // Cleanup Object URLs on unmount
      Object.values(imageUrlsRef.current).forEach((url) => {
        try {
          URL.revokeObjectURL(url);
        } catch {
          // ignore cleanup failures
        }
      });
    };
  }, []);

  return { imageUrls, imageErrors, fetchImage, imageUrlsRef };
}
