//
//  APIModels.swift
//  LiveBoost
//
//  Created by Live Commerce Japan
//  Copyright © 2026 Live Commerce Japan. All rights reserved.
//

import Foundation

// MARK: - Authentication

struct LoginRequest: Codable {
    let email: String
    let password: String
}

struct LoginResponse: Codable {
    let accessToken: String
    let tokenType: String
    let expiresAt: String

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case tokenType = "token_type"
        case expiresAt = "expires_at"
    }
}

// MARK: - Upload URL Generation

struct GenerateUploadURLRequest: Codable {
    let email: String
    let videoId: String
    let filename: String

    enum CodingKeys: String, CodingKey {
        case email
        case videoId = "video_id"
        case filename
    }
}

struct GenerateUploadURLResponse: Codable {
    let uploadUrl: String
    let blobName: String
    let videoId: String
    let expiresAt: String

    enum CodingKeys: String, CodingKey {
        case uploadUrl = "upload_url"
        case blobName = "blob_name"
        case videoId = "video_id"
        case expiresAt = "expires_at"
    }
}

// MARK: - Live Analysis

struct LiveAnalysisStartRequest: Codable {
    let videoId: String
    let userId: String
    let streamSource: String
    let totalChunks: Int

    enum CodingKeys: String, CodingKey {
        case videoId = "video_id"
        case userId = "user_id"
        case streamSource = "stream_source"
        case totalChunks = "total_chunks"
    }
}

struct LiveAnalysisStartResponse: Codable {
    let success: Bool
    let videoId: String
    let message: String

    enum CodingKeys: String, CodingKey {
        case success
        case videoId = "video_id"
        case message
    }
}

// MARK: - Analysis Status

struct AnalysisStatusResponse: Codable {
    let videoId: String
    let status: String
    let progress: Double?
    let results: AnalysisResults?

    enum CodingKeys: String, CodingKey {
        case videoId = "video_id"
        case status
        case progress
        case results
    }
}

struct AnalysisResults: Codable {
    let topSalesMoments: [SalesMoment]?
    let hookDetections: [HookDetection]?
    let clipCandidates: [ClipCandidate]?

    enum CodingKeys: String, CodingKey {
        case topSalesMoments = "top_sales_moments"
        case hookDetections = "hook_detections"
        case clipCandidates = "clip_candidates"
    }
}

struct SalesMoment: Codable, Identifiable {
    let id: String
    let timestamp: Double
    let productName: String?
    let salesCount: Int?
    let confidence: Double

    enum CodingKeys: String, CodingKey {
        case id
        case timestamp
        case productName = "product_name"
        case salesCount = "sales_count"
        case confidence
    }
}

struct HookDetection: Codable, Identifiable {
    let id: String
    let timestamp: Double
    let hookType: String
    let text: String?

    enum CodingKeys: String, CodingKey {
        case id
        case timestamp
        case hookType = "hook_type"
        case text
    }
}

struct ClipCandidate: Codable, Identifiable {
    let id: String
    let startTime: Double
    let endTime: Double
    let score: Double
    let label: String?

    enum CodingKeys: String, CodingKey {
        case id
        case startTime = "start_time"
        case endTime = "end_time"
        case score
        case label
    }
}
