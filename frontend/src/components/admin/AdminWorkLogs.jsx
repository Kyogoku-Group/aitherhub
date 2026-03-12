import { useState, useEffect, useCallback } from "react";
import axios from "axios";

/**
 * AdminWorkLogs – 作業ログ（デプロイ・修正・変更の履歴）
 *
 * work_logs テーブルのCRUD。
 * AIが過去の作業履歴を参照できるようにする。
 */

const ACTION_COLORS = {
  deploy: "bg-green-100 text-green-700",
  bugfix: "bg-red-100 text-red-700",
  feature: "bg-blue-100 text-blue-700",
  refactor: "bg-purple-100 text-purple-700",
  config: "bg-yellow-100 text-yellow-700",
  hotfix: "bg-red-200 text-red-800",
  other: "bg-gray-100 text-gray-600",
};

const INITIAL_FORM = {
  action: "bugfix", summary: "", details: "", files_changed: "",
  commit_hash: "", deployed_to: "", author: "manus-ai", related_bug_id: "",
};

export default function AdminWorkLogs({ adminKey }) {
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...INITIAL_FORM });
  const [expandedId, setExpandedId] = useState(null);
  const [filterAction, setFilterAction] = useState("");
  const baseURL = import.meta.env.VITE_API_BASE_URL;

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 100 };
      if (filterAction) params.action = filterAction;
      const res = await axios.get(`${baseURL}/api/v1/admin/work-logs`, {
        headers: { "X-Admin-Key": adminKey }, params,
      });
      setLogs(res.data.logs || []);
      setTotal(res.data.total || 0);
    } catch (e) {
      console.error("Failed to fetch work logs:", e);
    }
    setLoading(false);
  }, [baseURL, adminKey, filterAction]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const handleSubmit = async () => {
    try {
      const payload = { ...form };
      if (payload.related_bug_id === "") delete payload.related_bug_id;
      else payload.related_bug_id = parseInt(payload.related_bug_id, 10) || null;

      await axios.post(`${baseURL}/api/v1/admin/work-logs`, payload, {
        headers: { "X-Admin-Key": adminKey },
      });
      setShowForm(false);
      setForm({ ...INITIAL_FORM });
      fetchLogs();
    } catch (e) {
      console.error("Failed to save work log:", e);
      alert("保存に失敗しました: " + (e.response?.data?.detail || e.message));
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return "-";
    try {
      return new Date(dateStr).toLocaleString("ja-JP", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
    } catch { return dateStr; }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-gray-700">Work Logs</h2>
          <span className="text-xs text-gray-400">{total}件</span>
        </div>
        <div className="flex gap-2">
          <select value={filterAction} onChange={(e) => setFilterAction(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400">
            <option value="">全アクション</option>
            <option value="deploy">Deploy</option>
            <option value="bugfix">Bugfix</option>
            <option value="feature">Feature</option>
            <option value="refactor">Refactor</option>
            <option value="config">Config</option>
            <option value="hotfix">Hotfix</option>
          </select>
          <button onClick={() => { setShowForm(true); setForm({ ...INITIAL_FORM }); }}
            className="px-4 py-1.5 text-sm bg-orange-500 text-white rounded-lg hover:bg-orange-600">
            + 作業ログ追加
          </button>
        </div>
      </div>

      {/* Form Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setShowForm(false)}>
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-gray-700 mb-4">作業ログ追加</h3>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">アクション *</label>
                  <select value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400">
                    <option value="deploy">Deploy</option>
                    <option value="bugfix">Bugfix</option>
                    <option value="feature">Feature</option>
                    <option value="refactor">Refactor</option>
                    <option value="config">Config</option>
                    <option value="hotfix">Hotfix</option>
                    <option value="other">Other</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">作業者</label>
                  <input type="text" value={form.author} onChange={(e) => setForm({ ...form, author: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400" />
                </div>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">概要 *</label>
                <input type="text" value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
                  placeholder="例: retry-analysis APIのDONE保護とフォールバック修正" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">詳細</label>
                <textarea value={form.details} onChange={(e) => setForm({ ...form, details: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm h-24 resize-none focus:outline-none focus:ring-2 focus:ring-orange-400"
                  placeholder="修正内容の詳細..." />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">変更ファイル</label>
                <textarea value={form.files_changed} onChange={(e) => setForm({ ...form, files_changed: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm h-16 resize-none focus:outline-none focus:ring-2 focus:ring-orange-400"
                  placeholder="backend/app/api/v1/endpoints/video.py&#10;frontend/src/components/CsvAssetPanel.jsx" />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">コミットハッシュ</label>
                  <input type="text" value={form.commit_hash} onChange={(e) => setForm({ ...form, commit_hash: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-orange-400"
                    placeholder="abc1234" />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">デプロイ先</label>
                  <input type="text" value={form.deployed_to} onChange={(e) => setForm({ ...form, deployed_to: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
                    placeholder="production" />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">関連バグID</label>
                  <input type="text" value={form.related_bug_id} onChange={(e) => setForm({ ...form, related_bug_id: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
                    placeholder="1" />
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowForm(false)}
                className="px-4 py-2 text-sm bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200">キャンセル</button>
              <button onClick={handleSubmit}
                className="px-4 py-2 text-sm bg-orange-500 text-white rounded-lg hover:bg-orange-600">作成</button>
            </div>
          </div>
        </div>
      )}

      {/* Logs List */}
      {loading ? (
        <div className="flex items-center justify-center py-8">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
        </div>
      ) : logs.length === 0 ? (
        <div className="text-center py-8 text-gray-400 text-sm">作業ログがありません</div>
      ) : (
        <div className="space-y-2">
          {logs.map((log) => (
            <div key={log.id} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50"
                onClick={() => setExpandedId(expandedId === log.id ? null : log.id)}>
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${ACTION_COLORS[log.action] || ACTION_COLORS.other}`}>
                  {log.action}
                </span>
                <span className="text-sm text-gray-700 flex-1 truncate">{log.summary}</span>
                {log.commit_hash && (
                  <span className="text-[10px] text-gray-400 font-mono bg-gray-100 px-1.5 py-0.5 rounded">
                    {log.commit_hash.substring(0, 7)}
                  </span>
                )}
                <span className="text-xs text-gray-400 whitespace-nowrap">{formatDate(log.created_at)}</span>
                <span className="text-xs text-gray-400">{log.author}</span>
                <span className="text-gray-300">{expandedId === log.id ? "▲" : "▼"}</span>
              </div>

              {expandedId === log.id && (
                <div className="border-t border-gray-100 px-4 py-4 bg-gray-50 space-y-3">
                  {log.details && (
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-1">詳細</div>
                      <div className="text-sm text-gray-700 whitespace-pre-wrap">{log.details}</div>
                    </div>
                  )}
                  {log.files_changed && (
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-1">変更ファイル</div>
                      <div className="text-xs text-gray-500 font-mono whitespace-pre-wrap">{log.files_changed}</div>
                    </div>
                  )}
                  <div className="flex gap-4 text-xs text-gray-400">
                    {log.deployed_to && <span>デプロイ先: {log.deployed_to}</span>}
                    {log.related_bug_id && <span>関連バグ: #{log.related_bug_id}</span>}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
