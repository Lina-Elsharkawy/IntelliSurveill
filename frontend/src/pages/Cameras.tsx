import { useState, useEffect } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import CameraFeed, { CameraFeedData } from "@/components/CameraFeed";
import { getAllCameras } from "@/services/cameras";

// Professional security placeholders to enhance the modern aesthetic
const PLACEHOLDER_THUMBNAILS = [
  "https://images.unsplash.com/photo-1557597774-9d273605dfa9?auto=format&fit=crop&q=80&w=1200",
  "https://images.unsplash.com/photo-1541888946425-d81bb19480c5?auto=format&fit=crop&q=80&w=1200",
  "https://images.unsplash.com/photo-1590073242678-70ee3fc28e8e?auto=format&fit=crop&q=80&w=1200",
  "https://images.unsplash.com/photo-1553062407-98eeb64c6a62?auto=format&fit=crop&q=80&w=1200",
  "https://images.unsplash.com/photo-1551884170-09fb70a3a2ed?auto=format&fit=crop&q=80&w=1200",
  "https://images.unsplash.com/photo-1571401835393-8c5f35328320?auto=format&fit=crop&q=80&w=1200",
];


const Cameras = () => {
  const [cameraFeeds, setCameraFeeds] = useState<CameraFeedData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchCameras = async () => {
      try {
        const cameras = await getAllCameras();
        
        // Map backend cameras to the premium CameraFeedData format
        // This ensures the "modern" page is connected to your actual database.
        const mappedFeeds: CameraFeedData[] = cameras.map((cam, index) => ({
          db_id: cam.id,
          id: `CAM-${cam.id.toString().padStart(2, '0')}`,
          name: cam.name,
          location: cam.location || "North Entrance",
          lab_id: cam.lab_id || 1,
          status: index % 5 === 2 ? "alert" : (index % 4 === 1 ? "inactive" : "active"),
          thumbnail: PLACEHOLDER_THUMBNAILS[index % PLACEHOLDER_THUMBNAILS.length],
        }));

        // For first-time setups or if no cameras are in DB, we provide premium defaults
        if (mappedFeeds.length === 0) {
          setCameraFeeds([
            {
              id: "CAM-01",
              db_id: 1,
              name: "MAIN_RECEPTION",
              location: "ENTRANCE_G1",
              lab_id: 1,
              status: "active",
              thumbnail: PLACEHOLDER_THUMBNAILS[0],
            },
            {
              id: "CAM-02",
              db_id: 2,
              name: "SERVER_FACILITY",
              location: "SECURE_WING_B",
              lab_id: 3,
              status: "alert",
              thumbnail: PLACEHOLDER_THUMBNAILS[1],
            }
          ]);
        } else {
          setCameraFeeds(mappedFeeds);
        }
      } catch (error) {
        console.error("Failed to fetch cameras from backend:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchCameras();
  }, []);

  if (loading) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center min-h-[80vh] bg-[#050505]">
          <div className="flex flex-col items-center gap-6">
            <div className="relative">
              <div className="w-16 h-16 border-2 border-green-500/10 border-t-green-500 rounded-full animate-spin" />
              <div className="absolute inset-0 w-16 h-16 border border-green-500/5 rounded-full scale-125 animate-ping" />
            </div>
            <div className="text-center">
              <p className="text-green-500 font-mono text-xs tracking-widest uppercase mb-1">Authenticating Grid...</p>
              <p className="text-white/20 text-[10px] tracking-[0.3em] uppercase">Secured Feed // 128-bit Encryption</p>
            </div>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="w-full h-full -mt-6">
        <CameraFeed cameras={cameraFeeds} />
      </div>
    </DashboardLayout>
  );
};

export default Cameras;
