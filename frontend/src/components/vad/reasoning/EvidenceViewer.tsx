import { VadReasoningListItem } from "@/services/vad_api";
import { getEvidenceItems } from "./reasoningUtils";
import { Image as ImageIcon, FileJson, FolderGit2 } from "lucide-react";
import { normalizeEvidenceUrl } from "@/services/vad_api";

export function EvidenceViewer({ item }: { item: VadReasoningListItem }) {
  const evidence = getEvidenceItems(item);
  
  if (!evidence || evidence.length === 0) {
    return (
      <div className="p-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-4 flex items-center gap-2">
          <FolderGit2 size={14} /> Evidence Objects
        </h3>
        <div className="text-slate-500 text-sm py-6">No evidence objects found for this job.</div>
      </div>
    );
  }

  const annotatedFrame = evidence.find(e => e.media_role === "annotated_frame");
  const montage = evidence.find(e => e.media_role === "tubelet_montage");
  const frames = evidence.filter(e => e.media_role === "frame" || e.media_role === "tubelet_frame");

  return (
    <div className="p-2">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200 mb-4 flex items-center gap-2">
        <FolderGit2 size={18} className="text-blue-400" /> Evidence Objects
      </h3>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        {annotatedFrame?.presigned_url && (
          <div className="flex flex-col gap-2">
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest">Annotated Peak Frame</span>
            <img src={normalizeEvidenceUrl(annotatedFrame.presigned_url)} className="rounded-lg border border-zinc-700 w-full object-contain bg-black h-[140px]" alt="Annotated frame" />
          </div>
        )}
        
        {montage?.presigned_url && (
          <div className="flex flex-col gap-2">
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest">Tubelet Montage</span>
            <img src={normalizeEvidenceUrl(montage.presigned_url)} className="rounded-lg border border-zinc-700 w-full object-contain bg-black h-[140px]" alt="Montage" />
          </div>
        )}
      </div>

      {frames.length > 0 && (
        <div className="mt-2">
          <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1.5 block">Sampled Frames ({frames.length})</span>
          <div className="flex gap-2 overflow-x-auto pb-1 custom-scrollbar">
            {frames.map((f, i) => f.presigned_url ? (
              <img key={i} src={normalizeEvidenceUrl(f.presigned_url)} className="h-[70px] w-auto rounded border border-zinc-700 bg-black shrink-0" alt={`Frame ${i}`} />
            ) : null)}
          </div>
        </div>
      )}

      {evidence.some(e => !e.presigned_url) && (
        <details className="mt-6 group">
          <summary className="text-xs font-semibold text-slate-500 uppercase tracking-widest cursor-pointer hover:text-slate-300 select-none flex items-center w-max">
            Raw Object Keys ({evidence.filter(e => !e.presigned_url).length})
          </summary>
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
            {evidence.filter(e => !e.presigned_url).map((e, i) => {
              const objectKey = e.object_key || e.key || (typeof e === 'string' ? e : "Unknown object");
              return (
                <div key={i} className="flex items-center gap-2 bg-zinc-900 border border-zinc-800 p-2 rounded text-[10px] text-slate-400 font-mono truncate">
                  {objectKey.includes('json') ? <FileJson size={12} /> : <ImageIcon size={12} />}
                  <span className="truncate">{objectKey}</span>
                </div>
              );
            })}
          </div>
        </details>
      )}
    </div>
  );
}
