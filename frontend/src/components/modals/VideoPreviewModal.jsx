import { useEffect, useRef, useState, useCallback } from "react";
import CloseSvg from "../../assets/icons/close.svg";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogClose } from "../ui/dialog";

export default function VideoPreviewModal({
  open,
  onClose,
  videoUrl,
  timeStart = 0,
  skipSeek = false,
  isClipPreview = false
}) {
  const videoRef = useRef(null);
  const hasSetupRef = useRef(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isBuffering, setIsBuffering] = useState(false);
  const [bufferedProgress, setBufferedProgress] = useState(0);
  const [showCustomLoading, setShowCustomLoading] = useState(true);
  const prevOpenRef = useRef(false);
  const prevVideoUrlRef = useRef(null);
  const bufferCheckRef = useRef(null);

  const resetUiState = () => {
    setIsLoading(true);
    setIsBuffering(false);
    setBufferedProgress(0);
    setShowCustomLoading(true);
    hasSetupRef.current = false;
    if (bufferCheckRef.current) {
      clearInterval(bufferCheckRef.current);
      bufferCheckRef.current = null;
    }
  };

  // Reset states when modal closes or URL changes
  useEffect(() => {
    const prevOpen = prevOpenRef.current;
    const prevVideoUrl = prevVideoUrlRef.current;

    if ((!open && prevOpen) || (videoUrl !== prevVideoUrl)) {
      queueMicrotask(() => {
        resetUiState();
      });
    }

    prevOpenRef.current = open;
    prevVideoUrlRef.current = videoUrl;
  }, [open, videoUrl]);

  // Buffering state handlers
  const handleWaiting = useCallback(() => {
    setIsBuffering(true);
  }, []);

  const handlePlaying = useCallback(() => {
    setIsBuffering(false);
    setIsLoading(false);
    setShowCustomLoading(false);
  }, []);

  const handleCanPlayThrough = useCallback(() => {
    setIsBuffering(false);
  }, []);

  // Setup seek/play when modal opens or URL changes
  useEffect(() => {
    if (!open || !videoUrl) {
      return;
    }

    const setupVideoPlay = () => {
      const vid = videoRef.current;
      if (!vid || hasSetupRef.current) {
        return;
      }

      hasSetupRef.current = true;
      let hasSeeked = false;

      const seekAndPlay = async () => {
        try {
          setShowCustomLoading(true);
          setIsLoading(true);
          vid.defaultMuted = false;
          vid.muted = false;

          const shouldSkipSeek = isClipPreview || skipSeek;
          const shouldSeek = !shouldSkipSeek && !hasSeeked && Math.abs(vid.currentTime - timeStart) > 0.5;
          if (shouldSeek && timeStart !== null && timeStart !== undefined) {
            vid.currentTime = timeStart;
            hasSeeked = true;
          } else if (shouldSkipSeek) {
            hasSeeked = true;
          }

          // Wait for sufficient buffer before playing to avoid stuttering
          const waitForBuffer = () => {
            return new Promise((resolve) => {
              const checkBuffer = () => {
                if (!vid || vid.readyState >= 4) {
                  // HAVE_ENOUGH_DATA - sufficient buffer
                  resolve();
                  return;
                }
                // Check if we have at least 3 seconds buffered ahead
                const currentTime = vid.currentTime;
                for (let i = 0; i < vid.buffered.length; i++) {
                  const start = vid.buffered.start(i);
                  const end = vid.buffered.end(i);
                  if (currentTime >= start && currentTime <= end) {
                    if (end - currentTime >= 3) {
                      resolve();
                      return;
                    }
                  }
                }
                // Not enough buffer yet, check again soon
                setTimeout(checkBuffer, 200);
              };
              // Start checking, but resolve after max 5 seconds regardless
              const timeout = setTimeout(() => resolve(), 5000);
              const wrappedResolve = () => {
                clearTimeout(timeout);
                resolve();
              };
              const checkBufferWithResolve = () => {
                if (!vid || vid.readyState >= 4) {
                  wrappedResolve();
                  return;
                }
                const currentTime = vid.currentTime;
                for (let i = 0; i < vid.buffered.length; i++) {
                  const start = vid.buffered.start(i);
                  const end = vid.buffered.end(i);
                  if (currentTime >= start && currentTime <= end) {
                    if (end - currentTime >= 3) {
                      wrappedResolve();
                      return;
                    }
                  }
                }
                setTimeout(checkBufferWithResolve, 200);
              };
              checkBufferWithResolve();
            });
          };

          await waitForBuffer();

          try {
            // Try playing with sound first
            vid.muted = false;
            await vid.play();
            setIsLoading(false);
            setIsBuffering(false);
            setTimeout(() => setShowCustomLoading(false), 300);
          } catch {
            // Autoplay with sound blocked by browser policy - fallback to muted
            try {
              vid.muted = true;
              await vid.play();
              setIsLoading(false);
              setIsBuffering(false);
              setTimeout(() => setShowCustomLoading(false), 300);
            } catch {
              setIsLoading(false);
              setShowCustomLoading(false);
            }
          }
        } catch (e) {
          console.error("Error seeking/playing video preview:", e);
          setIsLoading(false);
          setShowCustomLoading(false);
        }
      };

      const handleCanPlay = () => {
        if (!hasSeeked) {
          seekAndPlay();
        }
      };

      const handleLoadedMetadata = () => {
        if (vid.readyState >= 3) {
          seekAndPlay();
        }
      };

      // Add event listeners
      vid.addEventListener("loadedmetadata", handleLoadedMetadata);
      vid.addEventListener("canplay", handleCanPlay);

      // Check current state
      if (vid.readyState >= 3) {
        seekAndPlay();
      } else if (vid.readyState >= 1) {
        handleLoadedMetadata();
      }

      return () => {
        vid.removeEventListener("loadedmetadata", handleLoadedMetadata);
        vid.removeEventListener("canplay", handleCanPlay);
      };
    };

    const cleanup = setupVideoPlay();

    if (!hasSetupRef.current) {
      const timeoutId = setTimeout(() => {
        if (open && videoUrl && !hasSetupRef.current) {
          setupVideoPlay();
        }
      }, 100);

      return () => {
        clearTimeout(timeoutId);
        if (cleanup) cleanup();
      };
    }

    return () => {
      if (cleanup) cleanup();
    };
  }, [videoUrl, open, isClipPreview, skipSeek, timeStart]);

  const handleProgress = () => {
    const video = videoRef.current;
    if (!video || video.duration === 0) return;

    const currentTime = video.currentTime;

    let bufferedEnd = 0;
    for (let i = 0; i < video.buffered.length; i++) {
      const start = video.buffered.start(i);
      const end = video.buffered.end(i);
      if (currentTime >= start && currentTime <= end) {
        bufferedEnd = end;
        break;
      }
    }

    const progress = Math.max(0, Math.min(100, (bufferedEnd / video.duration) * 100));
    setBufferedProgress(progress);
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (bufferCheckRef.current) {
        clearInterval(bufferCheckRef.current);
      }
    };
  }, []);

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => (!nextOpen ? onClose?.() : null)}>
      <DialogContent
        overlayClassName="bg-black/60"
        hideClose
        className="w-[95vw] max-w-5xl p-0 bg-black border border-white/10 overflow-hidden"
      >
        <DialogTitle className="sr-only">Video preview</DialogTitle>
        <DialogDescription className="sr-only">Video preview dialog</DialogDescription>

        <DialogClose asChild>
          <button
            onClick={onClose}
            className="absolute right-3 top-3 z-10 w-10 h-10 rounded-full bg-white/80 hover:bg-white transition flex items-center justify-center cursor-pointer"
          >
            <img src={CloseSvg} alt="Close" className="w-4 h-4" />
          </button>
        </DialogClose>

        {videoUrl ? (
          <div className="relative w-full h-full bg-black aspect-video">
            <video
              ref={videoRef}
              key={videoUrl}
              src={videoUrl}
              controls
              autoPlay
              playsInline
              preload="auto"
              poster=""
              className="w-full h-full"
              style={{ backgroundColor: "black" }}
              onProgress={handleProgress}
              onWaiting={handleWaiting}
              onPlaying={handlePlaying}
              onCanPlayThrough={handleCanPlayThrough}
              onError={(e) => console.error("Video error:", e)}
            />

            {/* Initial Loading Overlay */}
            {isLoading && showCustomLoading && (
              <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
                <div className="flex flex-col items-center gap-3">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white"></div>
                  <div className="flex flex-col items-center gap-2">
                    <p className="text-white text-sm">動画を準備中...</p>
                    {bufferedProgress > 0 && (
                      <div className="w-48 bg-gray-700 rounded-full h-1.5">
                        <div
                          className="bg-purple-500 h-1.5 rounded-full transition-all duration-300"
                          style={{ width: `${bufferedProgress}%` }}
                        />
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Buffering Overlay (during playback) */}
            {isBuffering && !isLoading && (
              <div className="absolute inset-0 bg-black/30 flex items-center justify-center pointer-events-none">
                <div className="flex flex-col items-center gap-2">
                  <div className="animate-spin rounded-full h-10 w-10 border-2 border-white/30 border-t-white"></div>
                  <p className="text-white/80 text-xs">バッファリング中...</p>
                </div>
              </div>
            )}

          </div>
        ) : (
          <div className="w-full aspect-video flex items-center justify-center text-white/80">
            プレビューを読み込み中...
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
