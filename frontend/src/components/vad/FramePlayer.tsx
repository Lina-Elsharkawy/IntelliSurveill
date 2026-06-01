import { useState, useEffect, useCallback, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { Play, Pause, SkipBack, SkipForward, Repeat, AlertTriangle } from "lucide-react";

export const FramePlayer = ({ 
  frameUrls, 
  fallbackMontageUrl 
}: { 
  frameUrls: string[], 
  fallbackMontageUrl?: string 
}) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(1);
  const [isLooping, setIsLooping] = useState(true);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  const hasFrames = frameUrls && frameUrls.length > 0;

  const handlePlayPause = useCallback(() => {
    setIsPlaying(p => !p);
  }, []);

  const handleNext = useCallback(() => {
    setCurrentIndex(i => (i + 1) % frameUrls.length);
  }, [frameUrls.length]);

  const handlePrev = useCallback(() => {
    setCurrentIndex(i => (i - 1 + frameUrls.length) % frameUrls.length);
  }, [frameUrls.length]);

  useEffect(() => {
    if (isPlaying && hasFrames) {
      const baseInterval = 1000 / 5; // Default assume 5fps baseline playback speed
      const interval = baseInterval / speed;
      timerRef.current = setInterval(() => {
        setCurrentIndex(prev => (prev + 1) % frameUrls.length);
      }, interval);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isPlaying, hasFrames, speed, frameUrls.length]);

  // Handle looping pause externally
  useEffect(() => {
    if (isPlaying && !isLooping && currentIndex === frameUrls.length - 1) {
      setIsPlaying(false);
    }
  }, [currentIndex, isPlaying, isLooping, frameUrls.length]);

  // Keyboard support
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!hasFrames) return;
      if (e.code === 'Space') {
        e.preventDefault();
        handlePlayPause();
      } else if (e.code === 'ArrowRight') {
        handleNext();
      } else if (e.code === 'ArrowLeft') {
        handlePrev();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [hasFrames, handlePlayPause, handleNext, handlePrev]);

  if (!hasFrames) {
    return (
      <div className="flex flex-col items-center justify-center p-12 bg-black/40 border border-white/5 rounded-lg text-center space-y-4">
        <AlertTriangle className="w-12 h-12 text-amber-500" />
        <div>
          <h3 className="text-lg font-medium text-slate-200 font-['Montserrat']">Individual frames not available</h3>
          <p className="text-sm text-slate-400 mt-1 max-w-md mx-auto">
            This event does not contain an individual frame sequence, likely because it was recorded before the frame saving feature was enabled.
          </p>
        </div>
        {fallbackMontageUrl && (
          <div className="mt-6 border border-white/10 rounded overflow-hidden shadow-2xl">
            <div className="bg-black/60 px-3 py-2 text-xs font-medium text-slate-300 border-b border-white/10">
              Showing Montage Instead
            </div>
            <img src={fallbackMontageUrl} alt="Montage fallback" className="max-w-full object-contain max-h-[400px]" />
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="anomaly-panel-glass rounded-lg overflow-hidden flex flex-col h-full">
      {/* Main Video Area */}
      <div 
        className="relative bg-black flex-1 flex items-center justify-center min-h-[400px] cursor-pointer group"
        onClick={handlePlayPause}
      >
        <img 
          src={frameUrls[currentIndex]} 
          alt={`Frame ${currentIndex}`} 
          className="max-w-full max-h-[600px] object-contain"
        />
        <div className="absolute top-4 right-4 bg-black/60 text-white text-xs px-2 py-1 rounded font-mono backdrop-blur-sm border border-white/10">
          Frame {currentIndex + 1} / {frameUrls.length}
        </div>
        {/* Play overlay if paused */}
        {!isPlaying && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-16 h-16 bg-black/50 rounded-full flex items-center justify-center backdrop-blur-sm border border-white/10 group-hover:bg-black/70 transition-colors">
              <Play className="w-8 h-8 text-white ml-1 opacity-80 group-hover:opacity-100" />
            </div>
          </div>
        )}
      </div>

      {/* Scrubber & Controls */}
      <div className="bg-black/40 p-4 border-t border-white/5 space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-400 font-mono w-8">{currentIndex + 1}</span>
          <Slider 
            value={[currentIndex]} 
            max={Math.max(1, frameUrls.length - 1)} 
            step={1} 
            onValueChange={(v) => {
              setCurrentIndex(v[0]);
            }} 
            className="flex-1"
          />
          <span className="text-xs text-slate-400 font-mono w-8 text-right">{frameUrls.length}</span>
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Button variant="outline" size="icon" className="w-8 h-8 bg-white/5 border-white/10 hover:bg-white/10" onClick={handlePrev}>
              <SkipBack className="w-4 h-4 text-slate-300" />
            </Button>
            <Button variant="default" size="icon" className="w-10 h-10 bg-[rgb(46,213,115)] hover:bg-[rgb(36,193,95)] text-black" onClick={handlePlayPause}>
              {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5 ml-0.5" />}
            </Button>
            <Button variant="outline" size="icon" className="w-8 h-8 bg-white/5 border-white/10 hover:bg-white/10" onClick={handleNext}>
              <SkipForward className="w-4 h-4 text-slate-300" />
            </Button>
          </div>

          <div className="flex items-center gap-2">
            <Badge variant="outline" className={`cursor-pointer transition-colors ${isLooping ? 'bg-[rgba(46,213,115,0.2)] text-[rgb(46,213,115)] border-[rgba(46,213,115,0.3)]' : 'bg-slate-800 text-slate-400 border-slate-700'}`} onClick={() => setIsLooping(!isLooping)}>
              <Repeat className="w-3 h-3 mr-1.5" /> Loop
            </Badge>
            <div className="flex items-center bg-black/40 rounded-md p-0.5 border border-white/10">
              {[0.5, 1, 2, 4].map(s => (
                <button
                  key={s}
                  onClick={() => setSpeed(s)}
                  className={`px-2 py-1 text-xs rounded transition-colors ${speed === s ? 'bg-slate-700 text-white shadow' : 'text-slate-400 hover:text-slate-200 hover:bg-white/10'}`}
                >
                  {s}x
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Thumbnails strip */}
      <div className="bg-black/60 p-2 overflow-x-auto border-t border-white/5 no-scrollbar">
        <div className="flex gap-1" style={{ width: 'max-content' }}>
          {frameUrls.map((url, i) => (
            <div 
              key={i} 
              onClick={() => { setCurrentIndex(i); setIsPlaying(false); }}
              className={`relative cursor-pointer transition-all border-2 rounded overflow-hidden flex-shrink-0 h-12 aspect-video ${i === currentIndex ? 'border-[rgb(46,213,115)] scale-105 z-10 shadow-[0_0_10px_rgba(46,213,115,0.5)]' : 'border-transparent opacity-50 hover:opacity-100'}`}
            >
              <img src={url} alt="" className="w-full h-full object-cover" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
