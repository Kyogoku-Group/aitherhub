import { useState, useEffect, useCallback } from "react";
import axios from "axios";

/**
 * AdminSystemErrors – Worker/API エラーログ表示
 *
 * video_error_logs テーブルのデータを表示する。
 * worker処理エラー、stuck_video_monitor、APIエラーなどが記録される。
 */

const SOURCE_COLORS = {
  worker: "bg-red-100 text-red-700",
  monitor: "bg-yellow-100 text-yellow-700",
  api: "bg-blue-100 text-blue-700",
  frontend: "bg-purple-100 text-purple-700",
};

export default function AdminSystemErrors({ adminKey }) {
  const [summary, setSummary] = useState(null);
  const [errors, setErrors] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [filterVideoId, setFilterVideoId] = useState("");
  const [filterCode, setFilterCode] = useState("");
  const [filterSource, setFilterSource] = useState("");
  const [page, setPage] = useState(0);
  const LIMIT = 50;
  const baseURL = import.meta.env.VITE_API_BASE_URL;

  const fetchSummary = useCallback(async () => {
    try {
      const res = await axios.get(`${baseURL}/api/v1/admin/system-error-logs/summary`, {
        headers: { "X-Admin-Key": adminKey },
        params: { hours: 24 },
      });
      setSummary(res.data);
    } catch (e) {
      console.error("Failed to fetch error summary:", e);
    }
  }, [baseURL, adminKey]);

  const fetchErrors = useCallback(async (offset = 0) => {
    setLoading(true);
    try {
      const params = { limit: LIMIT, offset };
      if (filterVideoId) params.video_id = filterVideoId;
      if (filterCode) params.error_code = filterCode;
      if (filterSource) params.source = filterSource;

      const res = await axios.get(`${baseURL}/api/v1/admin/system-error-logs`, {
        headers: { "X-Admin-Key": adminKey },
        params,
      });
      setErrors(res.data.errors || []);
      setTotal(res.data.total || 0);
    } catch (e) {
      console.error("Failed to fetch system errors:", e);
    }
    setLoading(false);
  }, [baseURL, adminKey, filterVideoId, filterCode, filterSource]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchErrors(page * LIMIT); }, [fetchErrors, page]);

  const formatDate = (dateStr) => {
    if (!dateStr) return "-";
    try {
      return new Date(dateStr).toLocaleString("ja-JP", {
        month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
    } catch { return dateStr; }
  };

  return (
    <div className="space-y-6">
      {/* Summary */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <h2 className="text-lg font-semibold text-gray-700">System Error Logs</h2>
          <span className="text-xs text-gray-400">直近24時間</span>
          <button onClick={fetchSummary} className="ml-auto text-xs text-gray-400 hover:text-gray-600">更新</button>
        </div>

        {summary && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="text-xs text-gray-400 mb-1">総エラー数</div>
                <div className={`text-2xl font-bold ${summary.total_errors > 0 ? "text-red-600" : "text-green-600"}`}>
                  {summary.total_errors}
                </div>
              </div>
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="text-xs text-gray-400 mb-1">エラーコード種別</div>
                <div className="text-2xl font-bold text-gray-700">
                  {Object.keys(summary.by_error_code || {}).length}
                </div>
              </div>
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="text-xs text-gray-400 mb-1">ステップ種別</div>
                <div className="text-2xl font-bold text-gray-700">
                  {Object.keys(summary.by_step || {}).length}
                </div>
              </div>
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="text-xs text-gray-400 mb-1">ソース種別</div>
                <div className="text-2xl font-bold text-gray-700">
                  {Object.keys(summary.by_source || {}).length}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* By Error Code */}
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <h3 className="text-sm font-medium text-gray-600 mb-3">エラーコード別</h3>
                {Object.keys(summary.by_error_code || {}).length === 0 ? (
                  <p className="text-xs text-gray-400">なし</p>
                ) : (
                  <div className="space-y-1.5 max-h-40 overflow-y-auto">
                    {Object.entries(summary.by_error_code || {}).map(([code, count]) => (
                      <div key={code} className="flex items-center justify-between">
                        <span className="text-xs text-gray-700 truncate max-w-[150px]" title={code}>{code}</span>
                        <span className="text-xs font-medium text-red-600 bg-red-50 px-2 py-0.5 rounded">{count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* By Step */}
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <h3 className="text-sm font-medium text-gray-600 mb-3">ステップ別</h3>
                {Object.keys(summary.by_step || {}).length === 0 ? (
                  <p className="text-xs text-gray-400">なし</p>
                ) : (
                  <div className="space-y-1.5 max-h-40 overflow-y-auto">
                    {Object.entries(summary.by_step || {}).map(([step, count]) => (
                      <div key={step} className="flex items-center justify-between">
                        <span className="text-xs text-gray-700 truncate max-w-[150px]" title={step}>{step}</span>
                        <span className="text-xs font-medium text-orange-600 bg-orange-50 px-2 py-0.5 rounded">{count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* By Source */}
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <h3 className="text-sm font-medium text-gray-600 mb-3">ソース別</h3>
                {Object.keys(summary.by_source || {}).length === 0 ? (
                  <p className="text-xs text-gray-400">なし</p>
                ) : (
                  <div className="space-y-1.5">
                    {Object.entries(summary.by_source || {}).map(([src, count]) => (
                      <div key={src} className="flex items-center justify-between">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${SOURCE_COLORS[src] || "bg-gray-100 text-gray-600"}`}>{src}</span>
                        <span className="text-sm font-medium text-gray-700">{count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Error Log Table */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <h2 className="text-lg font-semibold text-gray-700">エラーログ詳細</h2>
          <span className="text-xs text-gray-400">{total}件</span>
        </div>

        <div className="flex flex-wrap gap-2 mb-4">
          <input type="text" placeholder="video_id" value={filterVideoId}
            onChange={(e) => setFilterVideoId(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-orange-400" />
          <input type="text" placeholder="error_code" value={filterCode}
            onChange={(e) => setFilterCode(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-orange-400" />
          <select value={filterSource} onChange={(e) => setFilterSource(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400">
            <option value="">全ソース</option>
            <option value="worker">Worker</option>
            <option value="monitor">Monitor</option>
            <option value="api">API</option>
          </select>
          <button onClick={() => { setPage(0); fetchErrors(0); }}
            className="px-4 py-1.5 text-sm bg-orange-500 text-white rounded-lg hover:bg-orange-600">検索</button>
          <button onClick={() => { setFilterVideoId(""); setFilterCode(""); setFilterSource(""); setPage(0); }}
            className="px-4 py-1.5 text-sm bg-gray-200 text-gray-600 rounded-lg hover:bg-gray-300">クリア</button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
          </div>
        ) : errors.length === 0 ? (
          <div className="text-center py-8 text-gray-400 text-sm">エラーログがありません</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left">
                  <th className="py-2 px-2 text-xs text-gray-500 font-medium">日時</th>
                  <th className="py-2 px-2 text-xs text-gray-500 font-medium">ソース</th>
                  <th className="py-2 px-2 text-xs text-gray-500 font-medium">コード</th>
                  <th className="py-2 px-2 text-xs text-gray-500 font-medium">ステップ</th>
                  <th className="py-2 px-2 text-xs text-gray-500 font-medium">動画</th>
                  <th className="py-2 px-2 text-xs text-gray-500 font-medium">メッセージ</th>
                </tr>
              </thead>
              <tbody>
                {errors.map((err) => (
                  <tr key={err.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-2 px-2 text-xs text-gray-400 whitespace-nowrap">{formatDate(err.created_at)}</td>
                    <td className="py-2 px-2">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${SOURCE_COLORS[err.source] || "bg-gray-100 text-gray-600"}`}>
                        {err.source}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-xs text-gray-700 font-mono max-w-[120px] truncate" title={err.error_code}>
                      {err.error_code}
                    </td>
                    <td className="py-2 px-2 text-xs text-gray-500 max-w-[120px] truncate" title={err.error_step}>
                      {err.error_step || "-"}
                    </td>
                    <td className="py-2 px-2 text-xs text-gray-500 max-w-[150px] truncate" title={err.filename || err.video_id}>
                      {err.filename || (err.video_id ? err.video_id.substring(0, 12) + "..." : "-")}
                    </td>
                    <td className="py-2 px-2 text-xs text-gray-500 max-w-[250px] truncate" title={err.error_message}>
                      {err.error_message || "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {total > LIMIT && (
              <div className="flex items-center justify-between mt-4">
                <span className="text-xs text-gray-400">
                  {page * LIMIT + 1} - {Math.min((page + 1) * LIMIT, total)} / {total}件
                </span>
                <div className="flex gap-2">
                  <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}
                    className="px-3 py-1 text-xs bg-gray-100 text-gray-600 rounded hover:bg-gray-200 disabled:opacity-50">前へ</button>
                  <button onClick={() => setPage((p) => p + 1)} disabled={(page + 1) * LIMIT >= total}
                    className="px-3 py-1 text-xs bg-gray-100 text-gray-600 rounded hover:bg-gray-200 disabled:opacity-50">次へ</button>
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
