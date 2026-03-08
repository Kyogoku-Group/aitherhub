//
//  Logger.swift
//  LiveBoost
//
//  Created by Live Commerce Japan
//  Copyright © 2026 Live Commerce Japan. All rights reserved.
//

import Foundation
import os.log

/// Centralized logging utility for LiveBoost.
/// Uses Apple's unified logging system (os.log) for performance and privacy.
enum Log {

    // MARK: - Subsystems

    private static let subsystem = Bundle.main.bundleIdentifier ?? "com.lcj.liveboost"

    // MARK: - Categories

    static let capture = os.Logger(subsystem: subsystem, category: "Capture")
    static let upload = os.Logger(subsystem: subsystem, category: "Upload")
    static let network = os.Logger(subsystem: subsystem, category: "Network")
    static let encoding = os.Logger(subsystem: subsystem, category: "Encoding")
    static let broadcast = os.Logger(subsystem: subsystem, category: "Broadcast")
    static let ui = os.Logger(subsystem: subsystem, category: "UI")
    static let general = os.Logger(subsystem: subsystem, category: "General")
}
