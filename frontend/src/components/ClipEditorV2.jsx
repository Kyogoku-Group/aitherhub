import React, { useState, useRef, useCallback, useEffect, useMemo } from "react";
import VideoService from "../base/services/videoService";
import ClipFeedbackPanel from "./ClipFeedbackPanel";

/**
 * ClipEditorV2 — Intelligent Clip Editor (Sales Intelligence Player style)
 *
 * Layout:
 * ┌──────────────────────────────────────────────────────────────────┐
 * │  Header (title, phase info, close)                               │
 * ├───────────────────────────┬──────────────────────────────────────┤
 * │                           │  AI Info / Captions / Feedback       │
 * │  9:16 Video (full height) │  (scrollable right panel)            │
 * │                           │                                      │
 * ├───────────────────────────┴──────────────────────────────────────┤
 * │  Timeline + Controls (trim handles, playback, speed)             │
 * └──────────────────────────────────────────────────────────────────┘
 */

// ─── Color Palette ──────────────────────────────────────────────────────
const COLORS = {
  bg: "#0f0f1a",
  surface: "#1a1a2e",
  surfaceLight: "#252540",
  border: "#333355",
  text: "#ffffff",
  textMuted: "#8888aa",
  textDim: "#555577",
  accent: "#FF6B35",
  accentHover: "#FF8855",
  green: "#10b981",
  red: "#ef4444",
  blue: "#6366f1",
  yellow: "#f59e0b",
  purple: "#8b5cf6",
  cyan: "#06b6d4",
};

const scoreToColor = (score, alpha = 1) => {
  if (score == null) return `rgba(80, 80, 120, ${alpha})`;
  if (score >= 80) return `rgba(16, 185, 129, ${alpha})`;
  if (score >= 60) return `rgba(245, 158, 11, ${alpha})`;
  if (score >= 40) return `rgba(251, 146, 60, ${alpha})`;
  return `rgba(239, 68, 68, ${alpha})`;
};

const scoreToEmoji = (score) => {
  if (score == null) return "—";
  if (score >= 80) return "🔥";
  if (score >= 60) return "👍";
  if (score >= 40) return "😐";
  return "👎";
};

const formatTime = (sec) => {
  if (!sec && sec !== 0) return "0:00";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  return `${m}:${s.toString().padStart(2, "0")}`;
};

const MARKER_ICONS = {
  sales: { icon: "💰", color: COLORS.yellow, label: "売上" },
  hook: { icon: "🎣", color: COLORS.green, label: "フック" },
  comment_spike: { icon: "💬", color: COLORS.blue, label: "コメント" },
  speech_peak: { icon: "🎤", color: COLORS.purple, label: "発話" },
  product_mention: { icon: "🛍️", color: COLORS.cyan, label: "商品" },
};

// ═══════════════════════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════════════════════

const ClipEditorV2 = ({ videoId, clip, videoData, onClose, onClipUpdated }) => {
  const videoRef = useRef(null);
  const timelineRef = useRef(null);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [videoReady, setVideoReady] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);

  const [trimStart, setTrimStart] = useState(clip?.time_start || 0);
  const [trimEnd, setTrimEnd] = useState(clip?.time_end || 0);
  const originalStart = clip?.time_start || 0;
  const originalEnd = clip?.time_end || 0;
  const [isDraggingTrim, setIsDraggingTrim] = useState(null);

  const [timelineData, setTimelineData] = useState(null);
  const [segments, setSegments] = useState([]);
  const [videoScore, setVideoScore] = useState(null);

  const [activeTab, setActiveTab] = useState("info"); // "info" | "captions" | "trim" | "feedback"
  const [isTrimming, setIsTrimming] = useState(false);
  const [statusMessage, setStatusMessage] = useState(null);
  const [captions, setCaptions] = useState([]);
  const [editingCaptionIdx, setEditingCaptionIdx] = useState(null);
  const [isSavingCaptions, setIsSavingCaptions] = useState(false);

  const clipDuration = trimEnd - trimStart;
  const trimDelta = clipDuration - (originalEnd - originalStart);

  const fullVideoUrl = useMemo(() => {
    if (videoData?.video_url) return videoData.video_url;
    if (clip?.video_url) return clip.video_url;
    return null;
  }, [videoData, clip]);

  // Current phase based on playback position
  const currentPhase = useMemo(() => {
    if (!segments.length) return null;
    return segments.find((s) => {
      const start = s.start_sec ?? s.time_start ?? 0;
      const end = s.end_sec ?? s.time_end ?? 0;
      return currentTime >= start && currentTime <= end;
    });
  }, [segments, currentTime]);

  // ─── Load Timeline Data ──────────────────────────────────────────
  useEffect(() => {
    if (!videoId) return;
    const loadData = async () => {
      try {
        const [timeline, segData, scoreData] = await Promise.all([
          VideoService.getTimelineData(videoId),
          VideoService.getSegmentScores(videoId),
          VideoService.getVideoScore(videoId),
        ]);
        setTimelineData(timeline);
        setSegments(segData?.segments || []);
        setVideoScore(scoreData);
      } catch (e) {
        console.warn("Failed to load editor data:", e);
      }
    };
    loadData();
  }, [videoId]);

  useEffect(() => {
    if (clip?.captions) setCaptions(clip.captions);
  }, [clip]);

  // ─── Video Event Handlers ────────────────────────────────────────
  const handleTimeUpdate = useCallback(() => {
    if (videoRef.current) setCurrentTime(videoRef.current.currentTime);
  }, []);

  const handleLoadedMetadata = useCallback(() => {
    if (videoRef.current) {
      setDuration(videoRef.current.duration);
      setVideoReady(true);
    }
  }, []);

  const togglePlay = useCallback(() => {
    if (!videoRef.current) return;
    if (isPlaying) videoRef.current.pause();
    else videoRef.current.play();
    setIsPlaying(!isPlaying);
  }, [isPlaying]);

  const seekTo = useCallback((time) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      setCurrentTime(time);
    }
  }, []);

  const changeSpeed = useCallback((rate) => {
    setPlaybackRate(rate);
    if (videoRef.current) videoRef.current.playbackRate = rate;
  }, []);

  // ─── Timeline Click Handler ──────────────────────────────────────
  const handleTimelineClick = useCallback((e) => {
    if (!timelineRef.current || !duration) return;
    const rect = timelineRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const ratio = x / rect.width;
    seekTo(Math.max(0, Math.min(duration, ratio * duration)));
  }, [duration, seekTo]);

  // ─── Trim Handlers ───────────────────────────────────────────────
  const handleTrimDrag = useCallback((e) => {
    if (!isDraggingTrim || !timelineRef.current || !duration) return;
    const rect = timelineRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const time = (x / rect.width) * duration;
    const clampedTime = Math.max(0, Math.min(duration, time));
    if (isDraggingTrim === "start") {
      if (clampedTime < trimEnd - 1) setTrimStart(Math.round(clampedTime * 10) / 10);
    } else {
      if (clampedTime > trimStart + 1) setTrimEnd(Math.round(clampedTime * 10) / 10);
    }
  }, [isDraggingTrim, duration, trimStart, trimEnd]);

  const handleTrimDragEnd = useCallback(() => setIsDraggingTrim(null), []);

  useEffect(() => {
    if (isDraggingTrim) {
      window.addEventListener("mousemove", handleTrimDrag);
      window.addEventListener("mouseup", handleTrimDragEnd);
      return () => {
        window.removeEventListener("mousemove", handleTrimDrag);
        window.removeEventListener("mouseup", handleTrimDragEnd);
      };
    }
  }, [isDraggingTrim, handleTrimDrag, handleTrimDragEnd]);

  // ─── Apply Trim ──────────────────────────────────────────────────
  const handleApplyTrim = async () => {
    if (!clip?.clip_id) return;
    setIsTrimming(true);
    setStatusMessage(null);
    try {
      const res = await VideoService.trimClip(videoId, clip.clip_id, trimStart, trimEnd);
      try {
        const startDelta = trimStart - originalStart;
        const endDelta = trimEnd - originalEnd;
        if (Math.abs(startDelta) > 0.05) {
          await VideoService.logClipEdit(videoId, {
            clip_id: clip.clip_id, edit_type: "trim_start",
            before_value: { start_sec: originalStart },
            after_value: { start_sec: trimStart }, delta_seconds: startDelta,
          });
        }
        if (Math.abs(endDelta) > 0.05) {
          await VideoService.logClipEdit(videoId, {
            clip_id: clip.clip_id, edit_type: "trim_end",
            before_value: { end_sec: originalEnd },
            after_value: { end_sec: trimEnd }, delta_seconds: endDelta,
          });
        }
      } catch (logErr) {
        console.warn("Edit tracking failed:", logErr);
      }
      setStatusMessage({ type: "success", text: "トリム適用中... 新しいクリップを生成しています" });
      if (onClipUpdated) onClipUpdated(res);
    } catch (e) {
      setStatusMessage({ type: "error", text: `トリム失敗: ${e.message}` });
    } finally {
      setIsTrimming(false);
    }
  };

  // ─── Caption Handlers ────────────────────────────────────────────
  const handleCaptionTextChange = (idx, newText) => {
    setCaptions((prev) => {
      const updated = [...prev];
      updated[idx] = { ...updated[idx], text: newText };
      return updated;
    });
  };

  const handleSaveCaptions = async () => {
    if (!clip?.clip_id) return;
    setIsSavingCaptions(true);
    setStatusMessage(null);
    try {
      await VideoService.updateClipCaptions(videoId, clip.clip_id, captions);
      setStatusMessage({ type: "success", text: "字幕を保存しました" });
    } catch (e) {
      setStatusMessage({ type: "error", text: `字幕保存失敗: ${e.message}` });
    } finally {
      setIsSavingCaptions(false);
    }
  };

  // ═══════════════════════════════════════════════════════════════════
  // RENDER
  // ═══════════════════════════════════════════════════════════════════
  return (
    <div style={{
      position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: COLORS.bg, zIndex: 1000,
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>

      {/* ═══ Header ═══ */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "8px 16px", borderBottom: `1px solid ${COLORS.border}`,
        backgroundColor: COLORS.surface, flexShrink: 0, minHeight: 44,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button onClick={onClose} style={{
            background: "none", border: "none", color: COLORS.textMuted,
            fontSize: 18, cursor: "pointer", padding: "4px 8px",
          }}>
            ‹
          </button>
          <span style={{ color: COLORS.text, fontSize: 14, fontWeight: 600 }}>
            CLIP EDITOR
          </span>
          <span style={{
            fontSize: 12, color: COLORS.textDim,
            padding: "2px 8px", backgroundColor: COLORS.surfaceLight, borderRadius: 4,
          }}>
            Phase {clip.phase_index ?? "?"} | {formatTime(originalStart)} - {formatTime(originalEnd)}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {clip.clip_url && (
            <a href={clip.clip_url} download style={{
              padding: "6px 16px", backgroundColor: COLORS.purple,
              color: "#fff", borderRadius: 8, textDecoration: "none",
              fontSize: 13, fontWeight: 600,
            }}>
              Export MP4
            </a>
          )}
          <button onClick={onClose} style={{
            background: "none", border: "none", color: COLORS.textMuted,
            fontSize: 20, cursor: "pointer", padding: "4px 8px",
          }}>
            ✕
          </button>
        </div>
      </div>

      {/* ═══ Main Content: Left Video + Right Panel ═══ */}
      <div style={{ display: "flex", flex: 1, minHeight: 0, overflow: "hidden" }}>

        {/* ─── Left: 9:16 Video (full height) ─── */}
        <div style={{
          width: "45%", maxWidth: 500, flexShrink: 0,
          display: "flex", flexDirection: "column",
          backgroundColor: "#000", position: "relative",
        }}>
          {/* Video fills the entire left area */}
          <div style={{
            flex: 1, position: "relative", display: "flex",
            alignItems: "center", justifyContent: "center",
            overflow: "hidden",
          }}>
            {(fullVideoUrl || clip.clip_url) ? (
              <video
                ref={videoRef}
                src={clip.clip_url || fullVideoUrl}
                onTimeUpdate={handleTimeUpdate}
                onLoadedMetadata={handleLoadedMetadata}
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
                style={{
                  width: "100%", height: "100%",
                  objectFit: "contain",
                }}
              />
            ) : (
              <div style={{
                color: COLORS.textDim, fontSize: 16,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                プレビューなし
              </div>
            )}

            {/* Play overlay */}
            {!isPlaying && videoReady && (
              <div onClick={togglePlay} style={{
                position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer", backgroundColor: "rgba(0,0,0,0.2)",
              }}>
                <div style={{
                  width: 56, height: 56, borderRadius: "50%",
                  backgroundColor: "rgba(255,107,53,0.9)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 22, color: "#fff",
                }}>
                  ▶
                </div>
              </div>
            )}

            {/* Time overlay (top-left) */}
            <div style={{
              position: "absolute", top: 8, left: 8,
              padding: "4px 10px", borderRadius: 6,
              backgroundColor: "rgba(0,0,0,0.7)", color: "#fff",
              fontSize: 13, fontWeight: 600,
            }}>
              {formatTime(originalStart)} – {formatTime(originalEnd)}
              <span style={{ marginLeft: 8, opacity: 0.7, fontSize: 11 }}>
                Phase {clip.phase_index ?? "?"}
              </span>
            </div>
          </div>
        </div>

        {/* ─── Right: Info Panel (scrollable) ─── */}
        <div style={{
          flex: 1, display: "flex", flexDirection: "column",
          borderLeft: `1px solid ${COLORS.border}`,
          backgroundColor: COLORS.surface, overflow: "hidden",
        }}>
          {/* Tabs */}
          <div style={{
            display: "flex", gap: 0, flexShrink: 0,
            borderBottom: `1px solid ${COLORS.border}`,
            backgroundColor: COLORS.bg,
          }}>
            {[
              { key: "info", label: "AI分析" },
              { key: "captions", label: "字幕" },
              { key: "trim", label: "Trim" },
              { key: "feedback", label: "評価" },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                style={{
                  flex: 1, padding: "10px 0", border: "none",
                  backgroundColor: activeTab === tab.key ? COLORS.surface : "transparent",
                  color: activeTab === tab.key ? COLORS.text : COLORS.textDim,
                  cursor: "pointer", fontSize: 13, fontWeight: activeTab === tab.key ? 600 : 400,
                  borderBottom: activeTab === tab.key ? `2px solid ${COLORS.accent}` : "2px solid transparent",
                  transition: "all 0.15s",
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab Content (scrollable) */}
          <div style={{ flex: 1, overflow: "auto", padding: 16 }}>

            {/* ─── AI分析 Tab ─── */}
            {activeTab === "info" && (
              <div>
                {/* Time badge */}
                <div style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "6px 14px", borderRadius: 20,
                  backgroundColor: COLORS.accent + "22", border: `1px solid ${COLORS.accent}44`,
                  marginBottom: 16,
                }}>
                  <span style={{ fontSize: 13 }}>⏱</span>
                  <span style={{ color: COLORS.accent, fontSize: 14, fontWeight: 600 }}>
                    {formatTime(originalStart)} – {formatTime(originalEnd)}
                  </span>
                </div>

                {/* Tags */}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
                  {clip.clip_type && (
                    <span style={{
                      padding: "3px 10px", borderRadius: 4, fontSize: 12, fontWeight: 600,
                      backgroundColor: COLORS.yellow + "22", color: COLORS.yellow,
                      border: `1px solid ${COLORS.yellow}44`,
                    }}>
                      {clip.clip_type.toUpperCase()}
                    </span>
                  )}
                  {clip.ai_score != null && (
                    <span style={{
                      padding: "3px 10px", borderRadius: 4, fontSize: 12, fontWeight: 600,
                      backgroundColor: scoreToColor(clip.ai_score, 0.15),
                      color: scoreToColor(clip.ai_score),
                      border: `1px solid ${scoreToColor(clip.ai_score, 0.3)}`,
                    }}>
                      Score: {Math.round(clip.ai_score)}
                    </span>
                  )}
                </div>

                {/* AI Score Cards */}
                <div style={{ marginBottom: 20 }}>
                  <div style={{
                    color: COLORS.textMuted, fontSize: 11, marginBottom: 10,
                    fontWeight: 600, textTransform: "uppercase", letterSpacing: 1,
                  }}>
                    AI 評価
                  </div>
                  {[
                    { label: "バイラル度", score: currentPhase?.viral_score, icon: "🔥" },
                    { label: "フック力", score: currentPhase?.hook_score, icon: "🎣" },
                    { label: "エンゲージメント", score: currentPhase?.engagement_score, icon: "💬" },
                    { label: "発話エネルギー", score: currentPhase?.speech_energy, icon: "🎤" },
                  ].map((item, i) => (
                    <div key={i} style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: "8px 12px", marginBottom: 6,
                      backgroundColor: COLORS.surfaceLight, borderRadius: 8,
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 14 }}>{item.icon}</span>
                        <span style={{ color: COLORS.text, fontSize: 13 }}>{item.label}</span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <div style={{
                          width: 80, height: 6, backgroundColor: COLORS.bg,
                          borderRadius: 3, overflow: "hidden",
                        }}>
                          <div style={{
                            width: `${Math.min(100, item.score || 0)}%`,
                            height: "100%", borderRadius: 3,
                            backgroundColor: scoreToColor(item.score),
                          }} />
                        </div>
                        <span style={{
                          color: scoreToColor(item.score), fontSize: 14,
                          fontWeight: 700, minWidth: 28, textAlign: "right",
                        }}>
                          {item.score != null ? Math.round(item.score) : "—"}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* AI Summary (if available from clip description) */}
                {clip.description && (
                  <div style={{ marginBottom: 20 }}>
                    <div style={{
                      color: COLORS.textMuted, fontSize: 11, marginBottom: 8,
                      fontWeight: 600, textTransform: "uppercase", letterSpacing: 1,
                    }}>
                      AI要約
                    </div>
                    <p style={{
                      color: COLORS.text, fontSize: 13, lineHeight: 1.7,
                      margin: 0, padding: 12, backgroundColor: COLORS.surfaceLight,
                      borderRadius: 8,
                    }}>
                      {clip.description}
                    </p>
                  </div>
                )}

                {/* Video Overall Score */}
                {videoScore?.overall_score != null && (
                  <div style={{
                    padding: 14, backgroundColor: COLORS.surfaceLight, borderRadius: 10,
                    border: `1px solid ${scoreToColor(videoScore.overall_score, 0.3)}`,
                    marginBottom: 16,
                  }}>
                    <div style={{
                      display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 8,
                    }}>
                      <span style={{ color: COLORS.textMuted, fontSize: 12, fontWeight: 600 }}>
                        動画全体スコア
                      </span>
                      <span style={{
                        fontSize: 28, fontWeight: 800,
                        color: scoreToColor(videoScore.overall_score),
                      }}>
                        {Math.round(videoScore.overall_score)}
                      </span>
                    </div>
                    {videoScore.score_breakdown && (
                      <div style={{ fontSize: 12, color: COLORS.textDim }}>
                        {Object.entries(videoScore.score_breakdown).map(([k, v]) => (
                          <div key={k} style={{
                            display: "flex", justifyContent: "space-between", padding: "3px 0",
                          }}>
                            <span>{k.replace(/_/g, " ")}</span>
                            <span style={{ color: COLORS.textMuted }}>
                              {typeof v === "number" ? Math.round(v) : v}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* AI Markers */}
                {timelineData?.markers?.length > 0 && (
                  <div>
                    <div style={{
                      color: COLORS.textMuted, fontSize: 11, marginBottom: 8,
                      fontWeight: 600, textTransform: "uppercase", letterSpacing: 1,
                    }}>
                      AI マーカー ({timelineData.markers.length})
                    </div>
                    {timelineData.markers.slice(0, 8).map((m, i) => {
                      const markerInfo = MARKER_ICONS[m.type] || MARKER_ICONS.sales;
                      return (
                        <div key={i} onClick={() => seekTo(m.time_start)} style={{
                          display: "flex", alignItems: "center", gap: 8,
                          padding: "6px 10px", marginBottom: 4,
                          backgroundColor: COLORS.bg, borderRadius: 6,
                          cursor: "pointer", fontSize: 12,
                          border: `1px solid ${COLORS.border}`,
                          transition: "background-color 0.15s",
                        }}>
                          <span>{markerInfo.icon}</span>
                          <span style={{ color: COLORS.accent, fontWeight: 600, minWidth: 40 }}>
                            {formatTime(m.time_start)}
                          </span>
                          <span style={{
                            color: COLORS.text, flex: 1, overflow: "hidden",
                            textOverflow: "ellipsis", whiteSpace: "nowrap",
                          }}>
                            {m.label || m.description || markerInfo.label}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {/* ─── Captions Tab ─── */}
            {activeTab === "captions" && (
              <div>
                <div style={{
                  color: COLORS.textMuted, fontSize: 11, marginBottom: 12,
                  fontWeight: 600, textTransform: "uppercase", letterSpacing: 1,
                }}>
                  字幕編集
                </div>
                {captions.length === 0 ? (
                  <div style={{
                    color: COLORS.textDim, textAlign: "center", padding: 40, fontSize: 13,
                    backgroundColor: COLORS.surfaceLight, borderRadius: 8,
                  }}>
                    字幕データがありません。<br />
                    クリップを再生成すると自動字幕が追加されます。
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {captions.map((cap, idx) => (
                      <div key={idx} style={{
                        display: "flex", alignItems: "center", gap: 8,
                        padding: "8px 12px", backgroundColor: COLORS.surfaceLight,
                        borderRadius: 6, cursor: "pointer",
                        border: editingCaptionIdx === idx ? `1px solid ${COLORS.accent}` : `1px solid transparent`,
                      }}>
                        <span
                          onClick={() => seekTo(cap.start)}
                          style={{
                            color: COLORS.accent, fontSize: 11, minWidth: 44,
                            fontWeight: 600, cursor: "pointer",
                          }}
                        >
                          {formatTime(cap.start)}
                        </span>
                        {editingCaptionIdx === idx ? (
                          <input
                            type="text" value={cap.text}
                            onChange={(e) => handleCaptionTextChange(idx, e.target.value)}
                            onBlur={() => setEditingCaptionIdx(null)}
                            onKeyDown={(e) => { if (e.key === "Enter") setEditingCaptionIdx(null); }}
                            autoFocus
                            style={{
                              flex: 1, padding: "4px 8px",
                              backgroundColor: COLORS.bg, border: `1px solid ${COLORS.accent}`,
                              borderRadius: 4, color: COLORS.text, fontSize: 13, outline: "none",
                            }}
                          />
                        ) : (
                          <span onClick={() => setEditingCaptionIdx(idx)} style={{
                            flex: 1, color: cap.emphasis ? COLORS.yellow : COLORS.text,
                            fontSize: 13, fontWeight: cap.emphasis ? 700 : 400,
                          }}>
                            {cap.text}
                          </span>
                        )}
                      </div>
                    ))}
                    <button onClick={handleSaveCaptions} disabled={isSavingCaptions} style={{
                      padding: "10px 24px", border: "none", borderRadius: 8,
                      backgroundColor: COLORS.green, color: "#fff",
                      fontSize: 13, fontWeight: 600, cursor: "pointer",
                      opacity: isSavingCaptions ? 0.6 : 1, marginTop: 12,
                    }}>
                      {isSavingCaptions ? "保存中..." : "字幕を保存"}
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* ─── Trim Tab ─── */}
            {activeTab === "trim" && (
              <div>
                <div style={{
                  color: COLORS.textMuted, fontSize: 11, marginBottom: 12,
                  fontWeight: 600, textTransform: "uppercase", letterSpacing: 1,
                }}>
                  トリム編集
                </div>

                <div style={{
                  display: "flex", flexDirection: "column", gap: 16,
                  padding: 16, backgroundColor: COLORS.surfaceLight, borderRadius: 8,
                }}>
                  {/* Start time */}
                  <div>
                    <span style={{ color: COLORS.textMuted, fontSize: 12, marginBottom: 6, display: "block" }}>
                      開始時間
                    </span>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {[-1, -0.5, 0.5, 1].map((d) => (
                        <button key={d} onClick={() => {
                          const newStart = Math.max(0, trimStart + d);
                          if (newStart < trimEnd - 1) setTrimStart(Math.round(newStart * 10) / 10);
                        }} style={trimBtnStyle}>
                          {d > 0 ? "+" : ""}{d}s
                        </button>
                      ))}
                      <span style={{ color: COLORS.text, fontSize: 18, fontWeight: 700, marginLeft: 8 }}>
                        {formatTime(trimStart)}
                      </span>
                    </div>
                  </div>

                  {/* End time */}
                  <div>
                    <span style={{ color: COLORS.textMuted, fontSize: 12, marginBottom: 6, display: "block" }}>
                      終了時間
                    </span>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {[-1, -0.5, 0.5, 1].map((d) => (
                        <button key={d} onClick={() => {
                          const newEnd = trimEnd + d;
                          if (newEnd > trimStart + 1) setTrimEnd(Math.round(newEnd * 10) / 10);
                        }} style={trimBtnStyle}>
                          {d > 0 ? "+" : ""}{d}s
                        </button>
                      ))}
                      <span style={{ color: COLORS.text, fontSize: 18, fontWeight: 700, marginLeft: 8 }}>
                        {formatTime(trimEnd)}
                      </span>
                    </div>
                  </div>

                  {/* Duration info */}
                  <div style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "8px 12px", backgroundColor: COLORS.bg, borderRadius: 6,
                  }}>
                    <span style={{ color: COLORS.textMuted, fontSize: 12 }}>クリップ長</span>
                    <span style={{ color: COLORS.text, fontSize: 16, fontWeight: 700 }}>
                      {clipDuration.toFixed(1)}秒
                      {trimDelta !== 0 && (
                        <span style={{
                          color: trimDelta > 0 ? COLORS.green : COLORS.red,
                          marginLeft: 6, fontSize: 13,
                        }}>
                          ({trimDelta > 0 ? "+" : ""}{trimDelta.toFixed(1)}s)
                        </span>
                      )}
                    </span>
                  </div>

                  <button
                    onClick={handleApplyTrim}
                    disabled={isTrimming || (trimStart === originalStart && trimEnd === originalEnd)}
                    style={{
                      padding: "12px 24px", border: "none", borderRadius: 8,
                      backgroundColor: (trimStart === originalStart && trimEnd === originalEnd)
                        ? COLORS.surfaceLight : COLORS.accent,
                      color: "#fff", fontSize: 14, fontWeight: 600,
                      cursor: (trimStart === originalStart && trimEnd === originalEnd)
                        ? "not-allowed" : "pointer",
                      opacity: isTrimming ? 0.6 : 1, width: "100%",
                    }}
                  >
                    {isTrimming ? "生成中..." : "トリムを適用"}
                  </button>
                </div>
              </div>
            )}

            {/* ─── Feedback Tab ─── */}
            {activeTab === "feedback" && (
              <ClipFeedbackPanel
                videoId={videoId}
                phaseIndex={clip.phase_index ?? 0}
                timeStart={clip.time_start || originalStart}
                timeEnd={clip.time_end || originalEnd}
                clipId={clip.clip_id}
                aiScore={clip.ai_score}
                scoreBreakdown={clip.score_breakdown}
              />
            )}
          </div>

          {/* Status message */}
          {statusMessage && (
            <div style={{
              margin: "0 16px 12px", padding: "8px 12px", borderRadius: 6, flexShrink: 0,
              backgroundColor: statusMessage.type === "success" ? "rgba(16,185,129,0.1)" : "rgba(239,68,68,0.1)",
              color: statusMessage.type === "success" ? COLORS.green : COLORS.red,
              fontSize: 12, border: `1px solid ${statusMessage.type === "success" ? COLORS.green : COLORS.red}`,
            }}>
              {statusMessage.text}
            </div>
          )}
        </div>
      </div>

      {/* ═══ Bottom: Timeline + Controls ═══ */}
      <div style={{
        padding: "8px 16px 10px", borderTop: `1px solid ${COLORS.border}`,
        backgroundColor: COLORS.surface, flexShrink: 0,
      }}>
        {/* Heatmap Timeline */}
        <div
          ref={timelineRef}
          onClick={handleTimelineClick}
          style={{
            position: "relative", height: 36, backgroundColor: COLORS.bg,
            borderRadius: 6, overflow: "hidden", cursor: "pointer", marginBottom: 6,
          }}
        >
          {/* Heatmap segments */}
          {(segments.length > 0 ? segments : timelineData?.phases || []).map((seg, i) => {
            const start = seg.start_sec ?? seg.time_start ?? 0;
            const end = seg.end_sec ?? seg.time_end ?? 0;
            if (!duration) return null;
            const left = (start / duration) * 100;
            const width = ((end - start) / duration) * 100;
            const score = seg.viral_score ?? seg.hook_score ?? 0;
            return (
              <div key={i} style={{
                position: "absolute", top: 0, bottom: 0,
                left: `${left}%`, width: `${width}%`,
                backgroundColor: scoreToColor(score, 0.6),
                borderRight: `1px solid ${COLORS.bg}`,
              }} title={`Phase ${seg.phase_index ?? i}: Score ${Math.round(score)}`} />
            );
          })}

          {/* Trim region */}
          {duration > 0 && (
            <div style={{
              position: "absolute", top: 0, bottom: 0,
              left: `${(trimStart / duration) * 100}%`,
              width: `${((trimEnd - trimStart) / duration) * 100}%`,
              backgroundColor: "rgba(255, 107, 53, 0.2)",
              border: `2px solid ${COLORS.accent}`,
              borderRadius: 3, pointerEvents: "none",
            }} />
          )}

          {/* Trim handles */}
          {duration > 0 && (
            <>
              <div
                onMouseDown={(e) => { e.stopPropagation(); setIsDraggingTrim("start"); }}
                style={{
                  position: "absolute", top: 0, bottom: 0,
                  left: `${(trimStart / duration) * 100}%`,
                  width: 8, backgroundColor: COLORS.accent,
                  cursor: "ew-resize", zIndex: 2, borderRadius: "3px 0 0 3px",
                  transform: "translateX(-4px)",
                }}
              />
              <div
                onMouseDown={(e) => { e.stopPropagation(); setIsDraggingTrim("end"); }}
                style={{
                  position: "absolute", top: 0, bottom: 0,
                  left: `${(trimEnd / duration) * 100}%`,
                  width: 8, backgroundColor: COLORS.accent,
                  cursor: "ew-resize", zIndex: 2, borderRadius: "0 3px 3px 0",
                  transform: "translateX(-4px)",
                }}
              />
            </>
          )}

          {/* AI Markers */}
          {timelineData?.markers?.map((m, i) => {
            if (!duration) return null;
            const markerInfo = MARKER_ICONS[m.type] || MARKER_ICONS.sales;
            return (
              <div key={`marker-${i}`} style={{
                position: "absolute", top: -2,
                left: `${(m.time_start / duration) * 100}%`,
                transform: "translateX(-6px)",
                fontSize: 12, zIndex: 3, cursor: "pointer",
                filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.5))",
              }} onClick={(e) => { e.stopPropagation(); seekTo(m.time_start); }}
                 title={m.label || m.description || markerInfo.label}
              >
                {markerInfo.icon}
              </div>
            );
          })}

          {/* Playhead */}
          {duration > 0 && (
            <div style={{
              position: "absolute", top: 0, bottom: 0,
              left: `${(currentTime / duration) * 100}%`,
              width: 2, backgroundColor: "#fff",
              zIndex: 4, pointerEvents: "none",
              boxShadow: "0 0 4px rgba(255,255,255,0.5)",
            }} />
          )}
        </div>

        {/* Controls row */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          {/* Left: time info */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: COLORS.textDim, fontSize: 11 }}>{formatTime(0)}</span>
            <span style={{ color: COLORS.accent, fontWeight: 600, fontSize: 12 }}>
              {formatTime(trimStart)} — {formatTime(trimEnd)} ({clipDuration.toFixed(1)}s)
            </span>
            <span style={{ color: COLORS.textDim, fontSize: 11 }}>{formatTime(duration)}</span>
          </div>

          {/* Center: playback controls */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button onClick={() => seekTo(Math.max(0, currentTime - 5))} style={controlBtnStyle}>
              -5s
            </button>
            <button onClick={togglePlay} style={{
              ...controlBtnStyle,
              width: 40, height: 40, borderRadius: "50%",
              backgroundColor: COLORS.accent, fontSize: 16, padding: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              {isPlaying ? "⏸" : "▶"}
            </button>
            <button onClick={() => seekTo(Math.min(duration, currentTime + 5))} style={controlBtnStyle}>
              +5s
            </button>
            <span style={{ color: COLORS.textMuted, fontSize: 12, marginLeft: 4 }}>
              {formatTime(currentTime)} / {formatTime(duration)}
            </span>
          </div>

          {/* Right: speed controls */}
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {[1, 1.5, 2].map((rate) => (
              <button
                key={rate}
                onClick={() => changeSpeed(rate)}
                style={{
                  padding: "4px 10px", border: `1px solid ${COLORS.border}`,
                  borderRadius: 6, fontSize: 12, cursor: "pointer",
                  backgroundColor: playbackRate === rate ? COLORS.accent : COLORS.surfaceLight,
                  color: playbackRate === rate ? "#fff" : COLORS.textMuted,
                  fontWeight: playbackRate === rate ? 700 : 400,
                }}
              >
                {rate}x
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Styles ─────────────────────────────────────────────────────────────
const controlBtnStyle = {
  padding: "6px 12px", border: `1px solid ${COLORS.border}`,
  borderRadius: 8, backgroundColor: COLORS.surfaceLight,
  color: COLORS.text, fontSize: 13, cursor: "pointer",
};

const trimBtnStyle = {
  padding: "5px 10px", border: `1px solid ${COLORS.border}`,
  borderRadius: 6, backgroundColor: COLORS.bg,
  color: COLORS.textMuted, fontSize: 12, cursor: "pointer",
};

export default ClipEditorV2;
