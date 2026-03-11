"""
Video processing progress calculation utilities.
"""


def calculate_progress(status: str) -> int:
    """
    Calculate progress percentage based on current video processing status.

    Args:
        status: Current video status (e.g., 'STEP_0_EXTRACT_FRAMES', 'DONE', etc.)

    Returns:
        Progress percentage (0-100). Returns -1 for ERROR status.

    Examples:
        >>> calculate_progress('uploaded')
        0
        >>> calculate_progress('STEP_5_BUILD_PHASE_UNITS')
        89
        >>> calculate_progress('DONE')
        100
        >>> calculate_progress('ERROR')
        -1
    """
    # Calibrated from observed processing timeline so progress reflects elapsed time better.
    status_map = {
        "NEW": 0,
        "uploaded": 0,
        "STEP_COMPRESS_1080P": 1,
        "STEP_0_EXTRACT_FRAMES": 2,
        "STEP_1_DETECT_PHASES": 4,
        "STEP_2_EXTRACT_METRICS": 10,
        "STEP_3_TRANSCRIBE_AUDIO": 80,
        "STEP_4_IMAGE_CAPTION": 87,
        "STEP_5_BUILD_PHASE_UNITS": 89,
        "STEP_6_BUILD_PHASE_DESCRIPTION": 91,
        "STEP_7_GROUPING": 93,
        "STEP_8_UPDATE_BEST_PHASE": 94,
        "STEP_9_BUILD_VIDEO_STRUCTURE_FEATURES": 95,
        "STEP_10_ASSIGN_VIDEO_STRUCTURE_GROUP": 96,
        "STEP_11_UPDATE_VIDEO_STRUCTURE_GROUP_STATS": 97,
        "STEP_12_UPDATE_VIDEO_STRUCTURE_BEST": 98,
        "STEP_13_BUILD_REPORTS": 99,
        "STEP_14_FINALIZE": 99,
        "STEP_14_SPLIT_VIDEO": 99,
        "DONE": 100,
        "ERROR": -1,
    }
    return status_map.get(status, 0)


def get_status_message(status: str) -> str:
    """
    Get user-friendly Japanese message for current processing status.

    Args:
        status: Current video status

    Returns:
        Japanese message describing the current processing step

    Examples:
        >>> get_status_message('STEP_3_TRANSCRIBE_AUDIO')
        '音声書き起こし中...'
        >>> get_status_message('DONE')
        '解析完了'
    """
    messages = {
        "NEW": "アップロード待ち",
        "uploaded": "アップロード完了",
        "STEP_COMPRESS_1080P": "動画を解析準備中...",
        "STEP_0_EXTRACT_FRAMES": "フレーム抽出中...",
        "STEP_1_DETECT_PHASES": "フェーズ検出中...",
        "STEP_2_EXTRACT_METRICS": "メトリクス抽出中...",
        "STEP_3_TRANSCRIBE_AUDIO": "音声書き起こし中...",
        "STEP_4_IMAGE_CAPTION": "画像キャプション生成中...",
        "STEP_5_BUILD_PHASE_UNITS": "フェーズユニット構築中...",
        "STEP_6_BUILD_PHASE_DESCRIPTION": "フェーズ説明生成中...",
        "STEP_7_GROUPING": "グルーピング中...",
        "STEP_8_UPDATE_BEST_PHASE": "ベストフェーズ更新中...",
        "STEP_9_BUILD_VIDEO_STRUCTURE_FEATURES": "ビデオ構造特徴構築中...",
        "STEP_10_ASSIGN_VIDEO_STRUCTURE_GROUP": "ビデオ構造グループ割り当て中...",
        "STEP_11_UPDATE_VIDEO_STRUCTURE_GROUP_STATS": "ビデオ構造グループ統計更新中...",
        "STEP_12_UPDATE_VIDEO_STRUCTURE_BEST": "ビデオ構造ベスト更新中...",
        "STEP_13_BUILD_REPORTS": "レポート生成中...",
        "STEP_14_FINALIZE": "最終処理中...",
        "STEP_14_SPLIT_VIDEO": "ビデオ分割中...",
        "DONE": "解析完了",
        "ERROR": "エラーが発生しました",
    }
    return messages.get(status, "処理中...")
