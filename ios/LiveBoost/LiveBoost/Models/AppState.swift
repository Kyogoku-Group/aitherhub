//
//  AppState.swift
//  LiveBoost
//
//  Created by Live Commerce Japan
//  Copyright © 2026 Live Commerce Japan. All rights reserved.
//

import Foundation

/// Represents the five core states of the LiveBoost capture workflow.
///
/// State transitions:
///   Idle → Recording → Uploading → Analyzing → Completed → Idle
///
/// Error can be reached from any state and transitions back to Idle.
enum CaptureState: Equatable {
    case idle
    case recording
    case uploading(progress: Double)   // 0.0 … 1.0
    case analyzing
    case completed
    case error(message: String)

    // MARK: - Display Helpers

    var displayTitle: String {
        switch self {
        case .idle:
            return "AitherHub Capture"
        case .recording:
            return "ライブ終了"
        case .uploading:
            return "アップロード中…"
        case .analyzing:
            return "解析中…"
        case .completed:
            return "完了"
        case .error:
            return "エラー"
        }
    }

    var statusDescription: String {
        switch self {
        case .idle:
            return "タップしてライブ収録を開始"
        case .recording:
            return "録画中 — タップして終了"
        case .uploading(let progress):
            let pct = Int(progress * 100)
            return "アップロード中… \(pct)%"
        case .analyzing:
            return "AitherHubで解析中…"
        case .completed:
            return "Top Sales Momentsが生成されました"
        case .error(let message):
            return message
        }
    }

    var isButtonEnabled: Bool {
        switch self {
        case .idle, .recording, .completed, .error:
            return true
        case .uploading, .analyzing:
            return false
        }
    }
}
