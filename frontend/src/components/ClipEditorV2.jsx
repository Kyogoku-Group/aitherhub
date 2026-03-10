import React, { useState, useRef, useCallback, useEffect, useMemo } from "react";
import VideoService from "../base/services/videoService";
import ClipFeedbackPanel from "./ClipFeedbackPanel";

/**
 * ClipEditorV2 — Sales Intelligence Player style Clip Editor
 *
 * Layout (matching reference screenshot):
 * ┌──────────────────────────────────────────────────────────────────┐
 * │  Header (CLIP EDITOR, phase info, 2/59, close)                   │
 * ├──────────────────────┬───────────────────────────────────────────┤
 * │                      │  Time badge, tags                         │
 * │  9:16 Video          │  Sales Moments                            │
 * │  (full height,       │  AI要約                                    │
 * │   no black bars)     │  改善提案                                   │
 * │  + subtitle overlay  │  (scrollable)                             │
 * │                      │                                           │
 * ├──────────────────────┴───────────────────────────────────────────┤
 * │  Timeline (heatmap) + Controls (1x/1.5x/2x, 前/次, Phase/Full)  │
 * └──────────────────────────────────────────────────────────────────┘
 */

const C = {
  bg: "#0f0f1a",
  surface: "#1a1a2e",
  surfaceLight: "#252540",
  border: "#333355",
  text: "#fff",
  textMuted: "#8888aa",
  textDim: "#555577",
  accent: "#FF6B35",
  green: "#10b981",
  red: "#ef4444",
  blue: "#6366f1",
  yellow: "#f59e0b",
  purple: "#8b5cf6",
  cyan: "#06b6d4",
  teal: "#0d3d38",
};

const scoreColor = (s, a = 1) => {
  if (s == null) return `rgba(80,80,120,${a})`;
  if (s >= 80) return `rgba(16,185,129,${a})`;
  if (s >= 60) return `rgba(245,158,11,${a})`;
  if (s >= 40) return `rgba(251,146,60,${a})`;
  return `rgba(239,68,68,${a})`;
};

const fmt = (sec) => {
  if (!sec && sec !== 0) return "0:00";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
};

const MARKERS = {
  sales: { icon: "\u{1F4B0}", label: "\u58F2\u4E0A" },
  hook: { icon: "\u{1F3A3}", label: "\u30D5\u30C3\u30AF" },
  comment_spike: { icon: "\u{1F4AC}", label: "\u30B3\u30E1\u30F3\u30C8" },
  speech_peak: { icon: "\u{1F3A4}", label: "\u767A\u8A71" },
  product_mention: { icon: "\u{1F6CD}\uFE0F", label: "\u5546\u54C1" },
};

// ═══════════════════════════════════════════════════════════════════════════
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
  const origStart = clip?.time_start || 0;
  const origEnd = clip?.time_end || 0;
  const [dragging, setDragging] = useState(null);

  const [timelineData, setTimelineData] = useState(null);
  const [segments, setSegments] = useState([]);
  const [videoScore, setVideoScore] = useState(null);

  const [tab, setTab] = useState("info");
  const [isTrimming, setIsTrimming] = useState(false);
  const [status, setStatus] = useState(null);
  const [captions, setCaptions] = useState([]);
  const [editCapIdx, setEditCapIdx] = useState(null);
  const [savingCaps, setSavingCaps] = useState(false);

  const clipDur = trimEnd - trimStart;

  const videoUrl = useMemo(() => {
    return clip?.clip_url || videoData?.video_url || clip?.video_url || null;
  }, [videoData, clip]);

  // Current caption based on playback time
  const currentCaption = useMemo(() => {
    if (!captions.length) return null;
    return captions.find(
      (c) => currentTime >= (c.start || 0) && currentTime <= (c.end || c.start + 3)
    );
  }, [captions, currentTime]);

  const currentPhase = useMemo(() => {
    if (!segments.length) return null;
    return segments.find((s) => {
      const st = s.start_sec ?? s.time_start ?? 0;
      const en = s.end_sec ?? s.time_end ?? 0;
      return currentTime >= st && currentTime <= en;
    });
  }, [segments, currentTime]);

  // ─── Load Data ─────────────────────────────────────────────────
  useEffect(() => {
    if (!videoId) return;
    (async () => {
      try {
        const [tl, seg, sc] = await Promise.all([
          VideoService.getTimelineData(videoId),
          VideoService.getSegmentScores(videoId),
          VideoService.getVideoScore(videoId),
        ]);
        setTimelineData(tl);
        setSegments(seg?.segments || []);
        setVideoScore(sc);
      } catch (e) {
        console.warn("Editor data load failed:", e);
      }
    })();
  }, [videoId]);

  useEffect(() => {
    if (clip?.captions) setCaptions(clip.captions);
  }, [clip]);

  // ─── Video Handlers ────────────────────────────────────────────
  const onTimeUpdate = useCallback(() => {
    if (videoRef.current) setCurrentTime(videoRef.current.currentTime);
  }, []);

  const onMeta = useCallback(() => {
    if (videoRef.current) {
      setDuration(videoRef.current.duration);
      setVideoReady(true);
    }
  }, []);

  const toggle = useCallback(() => {
    if (!videoRef.current) return;
    isPlaying ? videoRef.current.pause() : videoRef.current.play();
    setIsPlaying(!isPlaying);
  }, [isPlaying]);

  const seek = useCallback((t) => {
    if (videoRef.current) {
      videoRef.current.currentTime = t;
      setCurrentTime(t);
    }
  }, []);

  const setSpeed = useCallback((r) => {
    setPlaybackRate(r);
    if (videoRef.current) videoRef.current.playbackRate = r;
  }, []);

  // ─── Timeline ──────────────────────────────────────────────────
  const onTLClick = useCallback(
    (e) => {
      if (!timelineRef.current || !duration) return;
      const rect = timelineRef.current.getBoundingClientRect();
      seek(Math.max(0, Math.min(duration, ((e.clientX - rect.left) / rect.width) * duration)));
    },
    [duration, seek]
  );

  // ─── Trim Drag ─────────────────────────────────────────────────
  const onTrimDrag = useCallback(
    (e) => {
      if (!dragging || !timelineRef.current || !duration) return;
      const rect = timelineRef.current.getBoundingClientRect();
      const t = Math.max(0, Math.min(duration, ((e.clientX - rect.left) / rect.width) * duration));
      if (dragging === "s" && t < trimEnd - 1) setTrimStart(Math.round(t * 10) / 10);
      if (dragging === "e" && t > trimStart + 1) setTrimEnd(Math.round(t * 10) / 10);
    },
    [dragging, duration, trimStart, trimEnd]
  );

  const onTrimEnd = useCallback(() => setDragging(null), []);

  useEffect(() => {
    if (dragging) {
      window.addEventListener("mousemove", onTrimDrag);
      window.addEventListener("mouseup", onTrimEnd);
      return () => {
        window.removeEventListener("mousemove", onTrimDrag);
        window.removeEventListener("mouseup", onTrimEnd);
      };
    }
  }, [dragging, onTrimDrag, onTrimEnd]);

  // ─── Apply Trim ────────────────────────────────────────────────
  const applyTrim = async () => {
    if (!clip?.clip_id) return;
    setIsTrimming(true);
    setStatus(null);
    try {
      const res = await VideoService.trimClip(videoId, clip.clip_id, trimStart, trimEnd);
      setStatus({ ok: true, msg: "トリム適用中..." });
      if (onClipUpdated) onClipUpdated(res);
    } catch (e) {
      setStatus({ ok: false, msg: `トリム失敗: ${e.message}` });
    } finally {
      setIsTrimming(false);
    }
  };

  // ─── Caption Edit ──────────────────────────────────────────────
  const editCap = (i, txt) => {
    setCaptions((p) => {
      const u = [...p];
      u[i] = { ...u[i], text: txt };
      return u;
    });
  };

  const saveCaps = async () => {
    if (!clip?.clip_id) return;
    setSavingCaps(true);
    setStatus(null);
    try {
      await VideoService.updateClipCaptions(videoId, clip.clip_id, captions);
      setStatus({ ok: true, msg: "字幕を保存しました" });
    } catch (e) {
      setStatus({ ok: false, msg: `字幕保存失敗: ${e.message}` });
    } finally {
      setSavingCaps(false);
    }
  };

  // ═══════════════════════════════════════════════════════════════
  // RENDER
  // ═══════════════════════════════════════════════════════════════
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: C.bg,
        zIndex: 1000,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {/* ═══ HEADER ═══ */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "6px 16px",
          borderBottom: `1px solid ${C.border}`,
          backgroundColor: C.surface,
          flexShrink: 0,
          height: 40,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", color: C.textMuted, fontSize: 20, cursor: "pointer" }}
          >
            ‹
          </button>
          <span style={{ color: C.text, fontSize: 13, fontWeight: 700, letterSpacing: 1 }}>CLIP EDITOR</span>
          <span
            style={{
              fontSize: 11,
              color: C.textDim,
              padding: "2px 8px",
              backgroundColor: C.surfaceLight,
              borderRadius: 4,
            }}
          >
            Phase {clip.phase_index ?? "?"} | {fmt(origStart)} - {fmt(origEnd)}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {clip.clip_url && (
            <a
              href={clip.clip_url}
              download
              style={{
                padding: "4px 14px",
                backgroundColor: C.purple,
                color: "#fff",
                borderRadius: 6,
                textDecoration: "none",
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              Export MP4
            </a>
          )}
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", color: C.textMuted, fontSize: 18, cursor: "pointer" }}
          >
            ✕
          </button>
        </div>
      </div>

      {/* ═══ MAIN: LEFT VIDEO + RIGHT PANEL ═══ */}
      <div style={{ display: "flex", flex: 1, minHeight: 0, overflow: "hidden" }}>
        {/* ─── LEFT: Video ─── */}
        <div
          style={{
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "#000",
            position: "relative",
            overflow: "hidden",
            /* Key fix: use aspect-ratio to constrain width based on available height */
          }}
        >
          {/* Inner container maintains 9:16 aspect ratio, height-based */}
          <div
            style={{
              position: "relative",
              height: "100%",
              aspectRatio: "9 / 16",
              maxWidth: "45vw",
              backgroundColor: "#000",
            }}
          >
            {videoUrl ? (
              <video
                ref={videoRef}
                src={videoUrl}
                onTimeUpdate={onTimeUpdate}
                onLoadedMetadata={onMeta}
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
                onClick={toggle}
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                  cursor: "pointer",
                }}
              />
            ) : (
              <div
                style={{
                  width: "100%",
                  height: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: C.textDim,
                  fontSize: 14,
                }}
              >
                プレビューなし
              </div>
            )}

            {/* Play overlay */}
            {!isPlaying && videoReady && (
              <div
                onClick={toggle}
                style={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: "pointer",
                  backgroundColor: "rgba(0,0,0,0.15)",
                }}
              >
                <div
                  style={{
                    width: 52,
                    height: 52,
                    borderRadius: "50%",
                    backgroundColor: "rgba(255,107,53,0.85)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 20,
                    color: "#fff",
                  }}
                >
                  ▶
                </div>
              </div>
            )}

            {/* Time + Phase overlay (top-left) */}
            <div
              style={{
                position: "absolute",
                top: 8,
                left: 8,
                padding: "3px 10px",
                borderRadius: 4,
                backgroundColor: "rgba(0,0,0,0.7)",
                color: "#fff",
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              {fmt(origStart)} – {fmt(origEnd)}
              <span style={{ marginLeft: 6, opacity: 0.6, fontSize: 10 }}>
                Phase {clip.phase_index ?? "?"}
              </span>
            </div>

            {/* ★ SUBTITLE OVERLAY ★ */}
            {currentCaption && (
              <div
                style={{
                  position: "absolute",
                  bottom: 40,
                  left: 12,
                  right: 12,
                  textAlign: "center",
                  pointerEvents: "none",
                }}
              >
                <span
                  style={{
                    display: "inline-block",
                    padding: "6px 16px",
                    borderRadius: 6,
                    backgroundColor: "rgba(0,0,0,0.75)",
                    color: currentCaption.emphasis ? C.yellow : "#fff",
                    fontSize: 18,
                    fontWeight: currentCaption.emphasis ? 800 : 600,
                    lineHeight: 1.4,
                    maxWidth: "90%",
                    textShadow: "0 1px 4px rgba(0,0,0,0.8)",
                  }}
                >
                  {currentCaption.text}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* ─── RIGHT: Info Panel ─── */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
            borderLeft: `1px solid ${C.border}`,
            backgroundColor: C.surface,
            overflow: "hidden",
          }}
        >
          {/* Tabs */}
          <div
            style={{
              display: "flex",
              flexShrink: 0,
              borderBottom: `1px solid ${C.border}`,
              backgroundColor: C.bg,
            }}
          >
            {[
              { k: "info", l: "AI分析" },
              { k: "captions", l: "字幕" },
              { k: "trim", l: "Trim" },
              { k: "feedback", l: "評価" },
            ].map((t) => (
              <button
                key={t.k}
                onClick={() => setTab(t.k)}
                style={{
                  flex: 1,
                  padding: "9px 0",
                  border: "none",
                  backgroundColor: tab === t.k ? C.surface : "transparent",
                  color: tab === t.k ? C.text : C.textDim,
                  cursor: "pointer",
                  fontSize: 13,
                  fontWeight: tab === t.k ? 600 : 400,
                  borderBottom: tab === t.k ? `2px solid ${C.accent}` : "2px solid transparent",
                }}
              >
                {t.l}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div style={{ flex: 1, overflow: "auto", padding: "14px 16px" }}>
            {/* ─── AI分析 ─── */}
            {tab === "info" && (
              <div>
                {/* Time badge */}
                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "5px 14px",
                    borderRadius: 20,
                    backgroundColor: C.accent + "22",
                    border: `1px solid ${C.accent}44`,
                    marginBottom: 14,
                  }}
                >
                  <span style={{ fontSize: 12 }}>⏱</span>
                  <span style={{ color: C.accent, fontSize: 13, fontWeight: 600 }}>
                    {fmt(origStart)} – {fmt(origEnd)}
                  </span>
                </div>

                {/* Tags row */}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
                  {clip.clip_type && (
                    <span style={tagStyle(C.yellow)}>{clip.clip_type.toUpperCase()}</span>
                  )}
                  {clip.ai_score != null && (
                    <span style={tagStyle(scoreColor(clip.ai_score))}>
                      Score: {Math.round(clip.ai_score)}
                    </span>
                  )}
                </div>

                {/* AI Score Cards */}
                <Section title="AI 評価">
                  {[
                    { l: "バイラル度", s: currentPhase?.viral_score, i: "🔥" },
                    { l: "フック力", s: currentPhase?.hook_score, i: "🎣" },
                    { l: "エンゲージメント", s: currentPhase?.engagement_score, i: "💬" },
                    { l: "発話エネルギー", s: currentPhase?.speech_energy, i: "🎤" },
                  ].map((x, idx) => (
                    <ScoreRow key={idx} icon={x.i} label={x.l} score={x.s} />
                  ))}
                </Section>

                {/* AI Summary */}
                {clip.description && (
                  <Section title="AI要約">
                    <p
                      style={{
                        color: C.text,
                        fontSize: 13,
                        lineHeight: 1.7,
                        margin: 0,
                        padding: 12,
                        backgroundColor: C.surfaceLight,
                        borderRadius: 8,
                      }}
                    >
                      {clip.description}
                    </p>
                  </Section>
                )}

                {/* Video Score */}
                {videoScore?.overall_score != null && (
                  <Section title="動画全体スコア">
                    <div
                      style={{
                        padding: 12,
                        backgroundColor: C.surfaceLight,
                        borderRadius: 8,
                        border: `1px solid ${scoreColor(videoScore.overall_score, 0.3)}`,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ color: C.textMuted, fontSize: 12 }}>Overall</span>
                        <span
                          style={{
                            fontSize: 26,
                            fontWeight: 800,
                            color: scoreColor(videoScore.overall_score),
                          }}
                        >
                          {Math.round(videoScore.overall_score)}
                        </span>
                      </div>
                    </div>
                  </Section>
                )}

                {/* AI Markers */}
                {timelineData?.markers?.length > 0 && (
                  <Section title={`AI マーカー (${timelineData.markers.length})`}>
                    {timelineData.markers.slice(0, 8).map((m, i) => {
                      const mi = MARKERS[m.type] || MARKERS.sales;
                      return (
                        <div
                          key={i}
                          onClick={() => seek(m.time_start)}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            padding: "5px 10px",
                            marginBottom: 3,
                            backgroundColor: C.bg,
                            borderRadius: 5,
                            cursor: "pointer",
                            fontSize: 12,
                            border: `1px solid ${C.border}`,
                          }}
                        >
                          <span>{mi.icon}</span>
                          <span style={{ color: C.accent, fontWeight: 600, minWidth: 38 }}>
                            {fmt(m.time_start)}
                          </span>
                          <span
                            style={{
                              color: C.text,
                              flex: 1,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {m.label || m.description || mi.label}
                          </span>
                        </div>
                      );
                    })}
                  </Section>
                )}
              </div>
            )}

            {/* ─── 字幕 ─── */}
            {tab === "captions" && (
              <div>
                <SectionTitle>字幕編集</SectionTitle>
                {captions.length === 0 ? (
                  <div
                    style={{
                      color: C.textDim,
                      textAlign: "center",
                      padding: 32,
                      fontSize: 13,
                      backgroundColor: C.surfaceLight,
                      borderRadius: 8,
                    }}
                  >
                    字幕データがありません。
                    <br />
                    クリップを再生成すると自動字幕が追加されます。
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    {captions.map((cap, i) => (
                      <div
                        key={i}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          padding: "6px 10px",
                          backgroundColor: C.surfaceLight,
                          borderRadius: 5,
                          border: editCapIdx === i ? `1px solid ${C.accent}` : "1px solid transparent",
                        }}
                      >
                        <span
                          onClick={() => seek(cap.start)}
                          style={{
                            color: C.accent,
                            fontSize: 11,
                            minWidth: 42,
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          {fmt(cap.start)}
                        </span>
                        {editCapIdx === i ? (
                          <input
                            type="text"
                            value={cap.text}
                            onChange={(e) => editCap(i, e.target.value)}
                            onBlur={() => setEditCapIdx(null)}
                            onKeyDown={(e) => e.key === "Enter" && setEditCapIdx(null)}
                            autoFocus
                            style={{
                              flex: 1,
                              padding: "3px 6px",
                              backgroundColor: C.bg,
                              border: `1px solid ${C.accent}`,
                              borderRadius: 4,
                              color: C.text,
                              fontSize: 13,
                              outline: "none",
                            }}
                          />
                        ) : (
                          <span
                            onClick={() => setEditCapIdx(i)}
                            style={{
                              flex: 1,
                              color: cap.emphasis ? C.yellow : C.text,
                              fontSize: 13,
                              fontWeight: cap.emphasis ? 700 : 400,
                              cursor: "text",
                            }}
                          >
                            {cap.text}
                          </span>
                        )}
                      </div>
                    ))}
                    <button
                      onClick={saveCaps}
                      disabled={savingCaps}
                      style={{
                        padding: "9px 20px",
                        border: "none",
                        borderRadius: 8,
                        backgroundColor: C.green,
                        color: "#fff",
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: "pointer",
                        opacity: savingCaps ? 0.6 : 1,
                        marginTop: 10,
                      }}
                    >
                      {savingCaps ? "保存中..." : "字幕を保存"}
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* ─── Trim ─── */}
            {tab === "trim" && (
              <div>
                <SectionTitle>トリム編集</SectionTitle>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 14,
                    padding: 14,
                    backgroundColor: C.surfaceLight,
                    borderRadius: 8,
                  }}
                >
                  <TrimControl
                    label="開始時間"
                    value={trimStart}
                    onChange={(v) => v < trimEnd - 1 && v >= 0 && setTrimStart(Math.round(v * 10) / 10)}
                  />
                  <TrimControl
                    label="終了時間"
                    value={trimEnd}
                    onChange={(v) => v > trimStart + 1 && setTrimEnd(Math.round(v * 10) / 10)}
                  />
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      padding: "6px 10px",
                      backgroundColor: C.bg,
                      borderRadius: 6,
                    }}
                  >
                    <span style={{ color: C.textMuted, fontSize: 12 }}>クリップ長</span>
                    <span style={{ color: C.text, fontSize: 15, fontWeight: 700 }}>
                      {clipDur.toFixed(1)}秒
                    </span>
                  </div>
                  <button
                    onClick={applyTrim}
                    disabled={isTrimming || (trimStart === origStart && trimEnd === origEnd)}
                    style={{
                      padding: "10px 20px",
                      border: "none",
                      borderRadius: 8,
                      backgroundColor:
                        trimStart === origStart && trimEnd === origEnd ? C.surfaceLight : C.accent,
                      color: "#fff",
                      fontSize: 13,
                      fontWeight: 600,
                      cursor:
                        trimStart === origStart && trimEnd === origEnd ? "not-allowed" : "pointer",
                      opacity: isTrimming ? 0.6 : 1,
                      width: "100%",
                    }}
                  >
                    {isTrimming ? "生成中..." : "トリムを適用"}
                  </button>
                </div>
              </div>
            )}

            {/* ─── 評価 ─── */}
            {tab === "feedback" && (
              <ClipFeedbackPanel
                videoId={videoId}
                phaseIndex={clip.phase_index != null ? Number(clip.phase_index) : 0}
                timeStart={clip.time_start || origStart}
                timeEnd={clip.time_end || origEnd}
                clipId={clip.clip_id}
                aiScore={clip.ai_score}
                scoreBreakdown={clip.score_breakdown}
              />
            )}
          </div>

          {/* Status */}
          {status && (
            <div
              style={{
                margin: "0 14px 10px",
                padding: "6px 10px",
                borderRadius: 6,
                flexShrink: 0,
                backgroundColor: status.ok ? "rgba(16,185,129,0.1)" : "rgba(239,68,68,0.1)",
                color: status.ok ? C.green : C.red,
                fontSize: 12,
                border: `1px solid ${status.ok ? C.green : C.red}`,
              }}
            >
              {status.msg}
            </div>
          )}
        </div>
      </div>

      {/* ═══ BOTTOM: Timeline + Controls ═══ */}
      <div
        style={{
          padding: "6px 16px 8px",
          borderTop: `1px solid ${C.border}`,
          backgroundColor: C.surface,
          flexShrink: 0,
        }}
      >
        {/* Timeline bar */}
        <div
          ref={timelineRef}
          onClick={onTLClick}
          style={{
            position: "relative",
            height: 32,
            backgroundColor: C.bg,
            borderRadius: 5,
            overflow: "hidden",
            cursor: "pointer",
            marginBottom: 5,
          }}
        >
          {/* Heatmap */}
          {(segments.length > 0 ? segments : timelineData?.phases || []).map((seg, i) => {
            const st = seg.start_sec ?? seg.time_start ?? 0;
            const en = seg.end_sec ?? seg.time_end ?? 0;
            if (!duration) return null;
            const sc = seg.viral_score ?? seg.hook_score ?? 0;
            return (
              <div
                key={i}
                style={{
                  position: "absolute",
                  top: 0,
                  bottom: 0,
                  left: `${(st / duration) * 100}%`,
                  width: `${((en - st) / duration) * 100}%`,
                  backgroundColor: scoreColor(sc, 0.6),
                  borderRight: `1px solid ${C.bg}`,
                }}
                title={`Phase ${seg.phase_index ?? i}: ${Math.round(sc)}`}
              />
            );
          })}

          {/* Trim region */}
          {duration > 0 && (
            <div
              style={{
                position: "absolute",
                top: 0,
                bottom: 0,
                left: `${(trimStart / duration) * 100}%`,
                width: `${((trimEnd - trimStart) / duration) * 100}%`,
                backgroundColor: "rgba(255,107,53,0.2)",
                border: `2px solid ${C.accent}`,
                borderRadius: 3,
                pointerEvents: "none",
              }}
            />
          )}

          {/* Trim handles */}
          {duration > 0 && (
            <>
              <div
                onMouseDown={(e) => {
                  e.stopPropagation();
                  setDragging("s");
                }}
                style={handleStyle((trimStart / duration) * 100)}
              />
              <div
                onMouseDown={(e) => {
                  e.stopPropagation();
                  setDragging("e");
                }}
                style={handleStyle((trimEnd / duration) * 100)}
              />
            </>
          )}

          {/* AI Markers */}
          {timelineData?.markers?.map((m, i) => {
            if (!duration) return null;
            const mi = MARKERS[m.type] || MARKERS.sales;
            return (
              <div
                key={`m${i}`}
                style={{
                  position: "absolute",
                  top: -2,
                  left: `${(m.time_start / duration) * 100}%`,
                  transform: "translateX(-6px)",
                  fontSize: 11,
                  zIndex: 3,
                  cursor: "pointer",
                  filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.5))",
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  seek(m.time_start);
                }}
                title={m.label || mi.label}
              >
                {mi.icon}
              </div>
            );
          })}

          {/* Playhead */}
          {duration > 0 && (
            <div
              style={{
                position: "absolute",
                top: 0,
                bottom: 0,
                left: `${(currentTime / duration) * 100}%`,
                width: 2,
                backgroundColor: "#fff",
                zIndex: 4,
                pointerEvents: "none",
                boxShadow: "0 0 4px rgba(255,255,255,0.5)",
              }}
            />
          )}
        </div>

        {/* Controls row */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          {/* Left: trim range */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
            <span style={{ color: C.textDim }}>{fmt(0)}</span>
            <span style={{ color: C.accent, fontWeight: 600, fontSize: 12 }}>
              {fmt(trimStart)} — {fmt(trimEnd)} ({clipDur.toFixed(1)}s)
            </span>
            <span style={{ color: C.textDim }}>{fmt(duration)}</span>
          </div>

          {/* Center: playback */}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Btn onClick={() => seek(Math.max(0, currentTime - 5))}>-5s</Btn>
            <button
              onClick={toggle}
              style={{
                width: 36,
                height: 36,
                borderRadius: "50%",
                backgroundColor: C.accent,
                border: "none",
                color: "#fff",
                fontSize: 15,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {isPlaying ? "⏸" : "▶"}
            </button>
            <Btn onClick={() => seek(Math.min(duration, currentTime + 5))}>+5s</Btn>
            <span style={{ color: C.textMuted, fontSize: 11, marginLeft: 4 }}>
              {fmt(currentTime)} / {fmt(duration)}
            </span>
          </div>

          {/* Right: speed */}
          <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
            {[1, 1.5, 2].map((r) => (
              <button
                key={r}
                onClick={() => setSpeed(r)}
                style={{
                  padding: "3px 9px",
                  border: `1px solid ${C.border}`,
                  borderRadius: 5,
                  fontSize: 11,
                  cursor: "pointer",
                  backgroundColor: playbackRate === r ? C.accent : C.surfaceLight,
                  color: playbackRate === r ? "#fff" : C.textMuted,
                  fontWeight: playbackRate === r ? 700 : 400,
                }}
              >
                {r}x
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// Sub-components
// ═══════════════════════════════════════════════════════════════════════════

const Section = ({ title, children }) => (
  <div style={{ marginBottom: 16 }}>
    <SectionTitle>{title}</SectionTitle>
    {children}
  </div>
);

const SectionTitle = ({ children }) => (
  <div
    style={{
      color: "#8888aa",
      fontSize: 11,
      marginBottom: 8,
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: 1,
    }}
  >
    {children}
  </div>
);

const ScoreRow = ({ icon, label, score }) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "7px 10px",
      marginBottom: 4,
      backgroundColor: "#252540",
      borderRadius: 6,
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
      <span style={{ fontSize: 13 }}>{icon}</span>
      <span style={{ color: "#fff", fontSize: 12 }}>{label}</span>
    </div>
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 60, height: 5, backgroundColor: "#0f0f1a", borderRadius: 3, overflow: "hidden" }}>
        <div
          style={{
            width: `${Math.min(100, score || 0)}%`,
            height: "100%",
            borderRadius: 3,
            backgroundColor: scoreColor(score),
          }}
        />
      </div>
      <span style={{ color: scoreColor(score), fontSize: 13, fontWeight: 700, minWidth: 24, textAlign: "right" }}>
        {score != null ? Math.round(score) : "—"}
      </span>
    </div>
  </div>
);

const TrimControl = ({ label, value, onChange }) => (
  <div>
    <span style={{ color: "#8888aa", fontSize: 12, marginBottom: 4, display: "block" }}>{label}</span>
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      {[-1, -0.5, 0.5, 1].map((d) => (
        <button
          key={d}
          onClick={() => onChange(value + d)}
          style={{
            padding: "4px 8px",
            border: "1px solid #333355",
            borderRadius: 5,
            backgroundColor: "#0f0f1a",
            color: "#8888aa",
            fontSize: 11,
            cursor: "pointer",
          }}
        >
          {d > 0 ? "+" : ""}
          {d}s
        </button>
      ))}
      <span style={{ color: "#fff", fontSize: 16, fontWeight: 700, marginLeft: 6 }}>{fmt(value)}</span>
    </div>
  </div>
);

const Btn = ({ onClick, children }) => (
  <button
    onClick={onClick}
    style={{
      padding: "4px 10px",
      border: "1px solid #333355",
      borderRadius: 6,
      backgroundColor: "#252540",
      color: "#fff",
      fontSize: 12,
      cursor: "pointer",
    }}
  >
    {children}
  </button>
);

const tagStyle = (color) => ({
  padding: "2px 8px",
  borderRadius: 4,
  fontSize: 11,
  fontWeight: 600,
  backgroundColor: typeof color === "string" && color.startsWith("rgba") ? color.replace(/[\d.]+\)$/, "0.15)") : color + "22",
  color: color,
  border: `1px solid ${typeof color === "string" && color.startsWith("rgba") ? color.replace(/[\d.]+\)$/, "0.3)") : color + "44"}`,
});

const handleStyle = (leftPct) => ({
  position: "absolute",
  top: 0,
  bottom: 0,
  left: `${leftPct}%`,
  width: 8,
  backgroundColor: "#FF6B35",
  cursor: "ew-resize",
  zIndex: 2,
  borderRadius: 2,
  transform: "translateX(-4px)",
});

export default ClipEditorV2;
