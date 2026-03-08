//
//  KeychainManager.swift
//  LiveBoost
//
//  Created by Live Commerce Japan
//  Copyright © 2026 Live Commerce Japan. All rights reserved.
//

import Foundation
import Security

/// A lightweight wrapper around the iOS Keychain for secure token storage.
final class KeychainManager {

    static let shared = KeychainManager()

    private init() {}

    // MARK: - Public API

    /// Saves a string value to the Keychain.
    @discardableResult
    func save(_ value: String, forKey key: String) -> Bool {
        guard let data = value.data(using: .utf8) else { return false }

        // Delete any existing item first
        delete(forKey: key)

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Configuration.keychainService,
            kSecAttrAccount as String: key,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock
        ]

        let status = SecItemAdd(query as CFDictionary, nil)
        return status == errSecSuccess
    }

    /// Retrieves a string value from the Keychain.
    func retrieve(forKey key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Configuration.keychainService,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
              let data = result as? Data,
              let string = String(data: data, encoding: .utf8) else {
            return nil
        }

        return string
    }

    /// Deletes a value from the Keychain.
    @discardableResult
    func delete(forKey key: String) -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Configuration.keychainService,
            kSecAttrAccount as String: key
        ]

        let status = SecItemDelete(query as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
    }

    // MARK: - Convenience

    /// Saves the JWT access token.
    @discardableResult
    func saveAccessToken(_ token: String) -> Bool {
        return save(token, forKey: Configuration.keychainTokenKey)
    }

    /// Retrieves the JWT access token.
    var accessToken: String? {
        return retrieve(forKey: Configuration.keychainTokenKey)
    }

    /// Clears the JWT access token.
    @discardableResult
    func clearAccessToken() -> Bool {
        return delete(forKey: Configuration.keychainTokenKey)
    }
}
