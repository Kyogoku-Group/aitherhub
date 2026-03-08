//
//  CaptureSession.swift
//  LiveBoost
//
//  Created by Live Commerce Japan
//  Copyright © 2026 Live Commerce Japan. All rights reserved.
//

import Foundation

/// Represents a single capture session from start to completion.
/// Tracks metadata needed for the upload and analysis pipeline.
struct CaptureSession: Identifiable, Codable {

    /// Unique identifier for this session (maps to AitherHub video_id).
    let id: String

    /// The authenticated user's ID on AitherHub.
    let userId: String

    /// Source of the stream (always "tiktok_live_ios_companion" for MVP).
    let streamSource: String

    /// Timestamp when recording started.
    let startedAt: Date

    /// Timestamp when recording ended.
    var endedAt: Date?

    /// Total number of chunks uploaded.
    var totalChunks: Int

    /// Total bytes uploaded.
    var totalBytesUploaded: Int64

    /// Current state of the session.
    var state: SessionState

    // MARK: - Nested Types

    enum SessionState: String, Codable {
        case recording
        case uploading
        case analyzing
        case completed
        case failed
    }

    // MARK: - Initializer

    init(userId: String) {
        self.id = UUID().uuidString
        self.userId = userId
        self.streamSource = "tiktok_live_ios_companion"
        self.startedAt = Date()
        self.endedAt = nil
        self.totalChunks = 0
        self.totalBytesUploaded = 0
        self.state = .recording
    }
}

/// Represents a single chunk of video data.
struct VideoChunk: Identifiable {
    let id: Int                 // Chunk sequence number (0-based)
    let fileURL: URL            // Local file path
    let fileSize: Int64         // Size in bytes
    var isUploaded: Bool = false
    var uploadURL: URL?         // SAS URL from backend
    var retryCount: Int = 0
}
