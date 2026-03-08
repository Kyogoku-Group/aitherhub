//
//  FileStorageManager.swift
//  LiveBoost
//
//  Created by Live Commerce Japan
//  Copyright © 2026 Live Commerce Japan. All rights reserved.
//

import Foundation

/// Manages temporary file storage for video chunks.
/// All files are stored in the app's cache directory and are
/// never saved to the Camera Roll.
final class FileStorageManager {

    static let shared = FileStorageManager()

    private let fileManager = FileManager.default

    private init() {
        ensureCacheDirectoryExists()
    }

    // MARK: - Directory Management

    /// Ensures the chunk cache directory exists.
    private func ensureCacheDirectoryExists() {
        let dir = Configuration.chunkCacheDirectory
        if !fileManager.fileExists(atPath: dir.path) {
            do {
                try fileManager.createDirectory(at: dir, withIntermediateDirectories: true)
                Log.general.info("Created chunk cache directory: \(dir.path)")
            } catch {
                Log.general.error("Failed to create chunk cache directory: \(error.localizedDescription)")
            }
        }
    }

    /// Returns the directory for a specific session's chunks.
    func sessionDirectory(for sessionId: String) -> URL {
        let dir = Configuration.chunkCacheDirectory.appendingPathComponent(sessionId, isDirectory: true)
        if !fileManager.fileExists(atPath: dir.path) {
            try? fileManager.createDirectory(at: dir, withIntermediateDirectories: true)
        }
        return dir
    }

    /// Returns the file URL for a specific chunk.
    func chunkFileURL(sessionId: String, chunkIndex: Int) -> URL {
        let dir = sessionDirectory(for: sessionId)
        let filename = String(format: "chunk_%04d.mp4", chunkIndex)
        return dir.appendingPathComponent(filename)
    }

    /// Returns the file URL for the active recording buffer.
    func activeRecordingURL(sessionId: String) -> URL {
        let dir = sessionDirectory(for: sessionId)
        return dir.appendingPathComponent("active_recording.mp4")
    }

    // MARK: - Cleanup

    /// Deletes a specific chunk file after successful upload.
    func deleteChunk(at url: URL) {
        do {
            if fileManager.fileExists(atPath: url.path) {
                try fileManager.removeItem(at: url)
                Log.upload.info("Deleted chunk: \(url.lastPathComponent)")
            }
        } catch {
            Log.upload.error("Failed to delete chunk: \(error.localizedDescription)")
        }
    }

    /// Deletes all files for a specific session.
    func deleteSession(_ sessionId: String) {
        let dir = sessionDirectory(for: sessionId)
        do {
            if fileManager.fileExists(atPath: dir.path) {
                try fileManager.removeItem(at: dir)
                Log.general.info("Deleted session directory: \(sessionId)")
            }
        } catch {
            Log.general.error("Failed to delete session directory: \(error.localizedDescription)")
        }
    }

    /// Cleans up all cached chunks. Called on app launch or when storage is low.
    func cleanupAllCaches() {
        let dir = Configuration.chunkCacheDirectory
        do {
            if fileManager.fileExists(atPath: dir.path) {
                try fileManager.removeItem(at: dir)
                ensureCacheDirectoryExists()
                Log.general.info("Cleaned up all chunk caches")
            }
        } catch {
            Log.general.error("Failed to cleanup caches: \(error.localizedDescription)")
        }
    }

    // MARK: - Queries

    /// Returns the total size of cached files in bytes.
    func totalCacheSize() -> Int64 {
        let dir = Configuration.chunkCacheDirectory
        guard let enumerator = fileManager.enumerator(at: dir, includingPropertiesForKeys: [.fileSizeKey]) else {
            return 0
        }

        var totalSize: Int64 = 0
        for case let fileURL as URL in enumerator {
            if let resourceValues = try? fileURL.resourceValues(forKeys: [.fileSizeKey]),
               let fileSize = resourceValues.fileSize {
                totalSize += Int64(fileSize)
            }
        }
        return totalSize
    }

    /// Returns the file size of a specific file.
    func fileSize(at url: URL) -> Int64 {
        guard let attributes = try? fileManager.attributesOfItem(atPath: url.path),
              let size = attributes[.size] as? Int64 else {
            return 0
        }
        return size
    }
}
