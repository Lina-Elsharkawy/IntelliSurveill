import { AlertCircle, CameraOff, Database, SearchX } from "lucide-react";

export const EmptyState = ({
  type,
  message,
  description,
  className
}: {
  type: "offline" | "no-events" | "no-evidence" | "no-data";
  message: string;
  description?: string;
  className?: string;
}) => {
  const getIcon = () => {
    switch (type) {
      case "offline": return <CameraOff className="w-12 h-12 text-slate-500 mb-4" />;
      case "no-events": return <SearchX className="w-12 h-12 text-slate-500 mb-4" />;
      case "no-evidence": return <Database className="w-12 h-12 text-slate-500 mb-4" />;
      default: return <AlertCircle className="w-12 h-12 text-slate-500 mb-4" />;
    }
  };

  return (
    <div className={`flex flex-col items-center justify-center min-h-[250px] text-slate-500 border-2 border-dashed border-white/5 rounded-xl bg-black/20 p-8 text-center ${className || ''}`}>
      {getIcon()}
      <h3 className="text-lg font-medium text-slate-300 font-['Montserrat']">{message}</h3>
      {description && (
        <p className="mt-2 max-w-md text-sm text-slate-400">
          {description}
        </p>
      )}
    </div>
  );
};
