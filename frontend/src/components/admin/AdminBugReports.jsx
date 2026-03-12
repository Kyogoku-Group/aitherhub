import { useState, useEffect, useCallback } from "react";
import axios from "axios";

/**
 * AdminBugReports – バグ報告の管理（問題→原因→解決策）
 *
 * bug_reports テーブルのCRUD。
 * AIが過去のバグと解決策を参照できるようにする。
 */

const SEVERITY_COLORS = {
  critical: "bg-red-600 text-white",
  high: "bg-red-100 text-red-700",
  medium: "bg-yellow-100 text-yellow-700",
  low: "bg-gray-100 text-gray-600",
};

const STATUS_COLORS = {
  open: "bg-red-100 text-red-700",
  investigating: "bg-yellow-100 text-yellow-700",
  resolved: "bg-green-100 text-green-700",
  closed: "bg-gray-100 text-gray-500",
};

const INITIAL_FORM = {
  title: "", severity: "medium", status: "open", category: "general",
  symptom: "", root_cause: "", solution: "", affected_files: "",
  related_video_ids: "", reported_by: "manus-ai",
};

export default function AdminBugReports({ adminKey }) {
  const [reports, setReports] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState(null);
  const [form, setForm] = useState({ ...INITIAL_FORM });
  const [expandedId, setExpandedId] = useState(null);
  const [filterStatus, setFilterStatus] = useState("");
  const baseURL = import.meta.env.VITE_API_BASE_URL;

  const fetchReports = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 100 };
      if (filterStatus) params.status = filterStatus;
      const res = await axios.get(`${baseURL}/api/v1/admin/bug-reports`, {
        headers: { "X-Admin-Key": adminKey }, params,
      });
      setReports(res.data.reports || []);
      setTotal(res.data.total || 0);
    } catch (e) {
      console.error("Failed to fetch bug reports:", e);
    }
    setLoading(false);
  }, [baseURL, adminKey, filterStatus]);

  useEffect(() => { fetchReports(); }, [fetchReports]);

  const handleSubmit = async () => {
    try {
      if (editId) {
        await axios.put(`${baseURL}/api/v1/admin/bug-reports/${editId}`, form, {
          headers: { "X-Admin-Key": adminKey },
        });
      } else {
        await axios.post(`${baseURL}/api/v1/admin/bug-reports`, form, {
          headers: { "X-Admin-Key": adminKey },
        });
      }
      setShowForm(false);
      setEditId(null);
      setForm({ ...INITIAL_FORM });
      fetchReports();
    } catch (e) {
      console.error("Failed to save bug report:", e);
      alert("保存に失敗しました: " + (e.response?.data?.detail || e.message));
    }
  };

  const startEdit = (report) => {
    setEditId(report.id);
    setForm({
      title: report.title || "",
      severity: report.severity || "medium",
      status: report.status || "open",
      category: report.category || "general",
      symptom: report.symptom || "",
      root_cause: report.root_cause || "",
      solution: report.solution || "",
      affected_files: report.affected_files || "",
      related_video_ids: report.related_video_ids || "",
      reported_by: report.reported_by || "manus-ai",
      resolved_by: report.resolved_by || "",
    });
    setShowForm(true);
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
          <h2 className="text-lg font-semibold text-gray-700">Bug Reports</h2>
          <span className="text-xs text-gray-400">{total}件</span>
        </div>
        <div className="flex gap-2">
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400">
            <option value="">全ステータス</option>
            <option value="open">Open</option>
            <option value="investigating">Investigating</option>
            <option value="resolved">Resolved</option>
            <option value="closed">Closed</option>
          </select>
          <button onClick={() => { setShowForm(true); setEditId(null); setForm({ ...INITIAL_FORM }); }}
            className="px-4 py-1.5 text-sm bg-orange-500 text-white rounded-lg hover:bg-orange-600">
            + 新規バグ報告
          </button>
        </div>
      </div>

      {/* Form Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setShowForm(false)}>
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-gray-700 mb-4">
              {editId ? "バグ報告を編集" : "新規バグ報告"}
            </h3>
            <div className="space-y-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">タイトル *</label>
                <input type="text" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
                  placeholder="例: retry-analysis APIでDONE動画のデータが消失する" />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">深刻度</label>
                  <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400">
                    <option value="critical">Critical</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">ステータス</label>
                  <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400">
                    <option value="open">Open</option>
                    <option value="investigating">Investigating</option>
                    <option value="resolved">Resolved</option>
                    <option value="closed">Closed</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">カテゴリ</label>
                  <input type="text" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
                    placeholder="例: worker, api, frontend" />
                </div>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">症状（何が起きたか）</label>
                <textarea value={form.symptom} onChange={(e) => setForm({ ...form, symptom: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm h-20 resize-none focus:outline-none focus:ring-2 focus:ring-orange-400"
                  placeholder="例: 再検証ボタンを押すとDONE動画のステータスがuploadedにリセットされ、2時間以上の再解析が始まる" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">原因（なぜ起きたか）</label>
                <textarea value={form.root_cause} onChange={(e) => setForm({ ...form, root_cause: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm h-20 resize-none focus:outline-none focus:ring-2 focus:ring-orange-400"
                  placeholder="例: CsvAssetPanelの再検証ボタンがretry-analysis APIを呼んでいた" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">解決策（どう直したか）</label>
                <textarea value={form.solution} onChange={(e) => setForm({ ...form, solution: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm h-20 resize-none focus:outline-none focus:ring-2 focus:ring-orange-400"
                  placeholder="例: 再検証ボタンのAPIをrecalc-csv-metricsに変更し、retry-analysisにDONE保護を追加" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">影響ファイル</label>
                <textarea value={form.affected_files} onChange={(e) => setForm({ ...form, affected_files: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm h-16 resize-none focus:outline-none focus:ring-2 focus:ring-orange-400"
                  placeholder="例: backend/app/api/v1/endpoints/video.py, frontend/src/components/CsvAssetPanel.jsx" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">報告者</label>
                  <input type="text" value={form.reported_by} onChange={(e) => setForm({ ...form, reported_by: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400" />
                </div>
                {editId && (
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">解決者</label>
                    <input type="text" value={form.resolved_by || ""} onChange={(e) => setForm({ ...form, resolved_by: e.target.value })}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400" />
                  </div>
                )}
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowForm(false)}
                className="px-4 py-2 text-sm bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200">キャンセル</button>
              <button onClick={handleSubmit}
                className="px-4 py-2 text-sm bg-orange-500 text-white rounded-lg hover:bg-orange-600">
                {editId ? "更新" : "作成"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reports List */}
      {loading ? (
        <div className="flex items-center justify-center py-8">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
        </div>
      ) : reports.length === 0 ? (
        <div className="text-center py-8 text-gray-400 text-sm">バグ報告がありません</div>
      ) : (
        <div className="space-y-3">
          {reports.map((r) => (
            <div key={r.id} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50"
                onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}>
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${SEVERITY_COLORS[r.severity] || "bg-gray-100"}`}>
                  {r.severity}
                </span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full ${STATUS_COLORS[r.status] || "bg-gray-100"}`}>
                  {r.status}
                </span>
                <span className="text-xs text-gray-400">[{r.category}]</span>
                <span className="text-sm text-gray-700 font-medium flex-1 truncate">{r.title}</span>
                <span className="text-xs text-gray-400">{formatDate(r.created_at)}</span>
                <button onClick={(e) => { e.stopPropagation(); startEdit(r); }}
                  className="text-xs text-gray-400 hover:text-orange-500 px-2">編集</button>
                <span className="text-gray-300">{expandedId === r.id ? "▲" : "▼"}</span>
              </div>

              {expandedId === r.id && (
                <div className="border-t border-gray-100 px-4 py-4 bg-gray-50 space-y-3">
                  {r.symptom && (
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-1">症状</div>
                      <div className="text-sm text-gray-700 whitespace-pre-wrap">{r.symptom}</div>
                    </div>
                  )}
                  {r.root_cause && (
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-1">原因</div>
                      <div className="text-sm text-gray-700 whitespace-pre-wrap">{r.root_cause}</div>
                    </div>
                  )}
                  {r.solution && (
                    <div>
                      <div className="text-xs font-medium text-orange-500 mb-1">解決策</div>
                      <div className="text-sm text-gray-700 whitespace-pre-wrap">{r.solution}</div>
                    </div>
                  )}
                  {r.affected_files && (
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-1">影響ファイル</div>
                      <div className="text-xs text-gray-500 font-mono whitespace-pre-wrap">{r.affected_files}</div>
                    </div>
                  )}
                  <div className="flex gap-4 text-xs text-gray-400">
                    <span>報告: {r.reported_by || "-"}</span>
                    {r.resolved_by && <span>解決: {r.resolved_by}</span>}
                    {r.resolved_at && <span>解決日: {formatDate(r.resolved_at)}</span>}
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
