//
//  Configuration.swift
//  LiveBoost
//
//  Created by Live Commerce Japan
//  Copyright © 2026 Live Commerce Japan. All rights reserved.
//

import Foundation

/// Central configuration for the LiveBoost app.
/// All constants and environment-specific values are managed here.
enum Configuration {

    // MARK: - API

    /// Base URL for the AitherHub Backend API.
    /// Override via Info.plist key `AITHERHUB_API_BASE_URL` for different environments.
    static var apiBaseURL: String {
        if let url = Bundle.main.infoDictionary?["AITHERHUB_API_BASE_URL"] as? String,
           !url.isEmpty {
            return url
        }
        return "https://api.aitherhub.com"
    }

    /// API version prefix.
    static let apiVersion = "/api/v1"

    /// Full API base path.
    static var apiBasePath: String {
        return apiBaseURL + apiVersion
    }

    // MARK: - Upload

    /// Maximum size of each video chunk in bytes (10 MB).
    static let chunkSizeBytes: Int64 = 10 * 1024 * 1024

    /// Maximum number of concurrent chunk uploads.
    static let maxConcurrentUploads: Int = 3

    /// Maximum retry count for a failed chunk upload.
    static let maxUploadRetries: Int = 3

    /// Timeout interval for upload requests (seconds).
    static let uploadTimeoutInterval: TimeInterval = 120

    // MARK: - Video Encoding

    /// Target video bitrate for H.264 encoding (2 Mbps).
    static let videoBitrate: Int = 2_000_000

    /// Target audio bitrate for AAC encoding (128 kbps).
    static let audioBitrate: Int = 128_000

    /// Video frame rate.
    static let videoFrameRate: Int = 30

    /// Video resolution width.
    static let videoWidth: Int = 1080

    /// Video resolution height.
    static let videoHeight: Int = 1920

    // MARK: - App Groups

    /// App Group identifier shared between the main app and the Broadcast Upload Extension.
    static let appGroupIdentifier = "group.com.lcj.liveboost"

    // MARK: - Keychain

    /// Keychain service name for storing authentication tokens.
    static let keychainService = "com.lcj.liveboost.auth"

    /// Keychain key for the JWT access token.
    static let keychainTokenKey = "access_token"

    // MARK: - Polling

    /// Interval for polling analysis status (seconds).
    static let analysisPollingInterval: TimeInterval = 10

    /// Maximum polling duration before timeout (seconds).
    static let analysisPollingTimeout: TimeInterval = 600  // 10 minutes

    // MARK: - Storage

    /// Temporary directory for video chunks within the app's cache.
    static var chunkCacheDirectory: URL {
        let cacheDir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first!
        return cacheDir.appendingPathComponent("LiveBoostChunks", isDirectory: true)
    }

    /// Shared container directory for App Group (used by Broadcast Extension).
    static var sharedContainerDirectory: URL? {
        return FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: appGroupIdentifier
        )
    }
}
