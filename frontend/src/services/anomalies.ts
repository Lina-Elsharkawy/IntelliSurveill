export async function getAllAnomalies() {
  const token = localStorage.getItem("access_token"); // get token from login
  if (!token) throw new Error("User is not authenticated");

  const res = await fetch("http://localhost:3000/api/anomalies/get_all_anomalies", {
    headers: {
      Authorization: `Bearer ${token}`, // send JWT to backend
    },
  });

  if (!res.ok) {
    const errData = await res.json();
    throw new Error(errData.error || "Failed to fetch anomalies");
  }

  return res.json();
}
