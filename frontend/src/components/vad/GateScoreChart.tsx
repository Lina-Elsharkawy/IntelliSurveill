export const GateScoreChart = ({ 
  gateName,
  isOnline
}: { 
  gateName: string;
  isOnline: boolean;
}) => {
  return (
    <div className="flex flex-col items-center justify-center h-[100px] bg-black/20 border border-white/5 rounded-lg mt-4 border-dashed">
      <span className="text-[11px] text-slate-500 font-['Montserrat']">
        {isOnline ? "No Recent Score" : "Waiting for Lab Stream"}
      </span>
    </div>
  );
};
