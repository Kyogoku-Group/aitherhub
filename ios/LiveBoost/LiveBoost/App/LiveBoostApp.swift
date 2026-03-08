//
//  LiveBoostApp.swift
//  LiveBoost
//
//  Created by Live Commerce Japan
//  Copyright © 2026 Live Commerce Japan. All rights reserved.
//
//  LiveBoost is the data collection infrastructure for the
//  Live Commerce Data OS. Designed with extensibility in mind.
//

import SwiftUI

@main
struct LiveBoostApp: App {

    // MARK: - State

    @StateObject private var appState = AppStateManager()

    // MARK: - Body

    var body: some Scene {
        WindowGroup {
            CaptureView()
                .environmentObject(appState)
                .onAppear {
                    configureAppearance()
                }
        }
    }

    // MARK: - Private

    private func configureAppearance() {
        // Global UI appearance configuration
        UINavigationBar.appearance().largeTitleTextAttributes = [
            .foregroundColor: UIColor.white
        ]
    }
}
