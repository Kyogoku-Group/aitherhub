import os
from typing import List, Dict, Any, Optional

from loguru import logger
from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel

from app.core.dependencies import get_current_user, get_db
from app.models.orm.chat import Chat as ChatModel
from sqlalchemy import insert
from starlette.background import BackgroundTask
import psycopg2


class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    max_tokens: Optional[int] = 2048
    model: Optional[str] = None


router = APIRouter(
    prefix="/chat",
    tags=["chat"],
)


@router.post("/stream")
async def stream_chat(
    payload: ChatRequest,
    video_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Proxy Azure OpenAI streaming responses and return SSE to client.

    Requires authenticated user (via `get_current_user`). Client should open
    an EventSource to receive `data: ...` events containing token deltas.
    """
    try:
        # Read config from environment
        from openai import AzureOpenAI

        api_key = os.getenv("AZURE_OPENAI_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_version = os.getenv("GPT5_API_VERSION") or "2024-12-01-preview"
        model = payload.model or os.getenv("GPT5_MODEL") or os.getenv("GPT5_DEPLOYMENT")

        if not api_key or not endpoint:
            raise HTTPException(status_code=500, detail="OpenAI configuration missing on server")

        # fetch latest report for the video (if any) and inject as system message
        # ensure video has finished processing (status == 'DONE') before answering
        try:
            sql_status = text("SELECT status FROM videos WHERE id = :video_id")
            sres = await db.execute(sql_status, {"video_id": video_id})
            vstatus = sres.scalar_one_or_none()
            if vstatus is None or str(vstatus).upper() != "DONE":
                raise HTTPException(status_code=400, detail="Chat unavailable: video report not ready")
        except HTTPException:
            raise
        except Exception:
            # if DB check fails for unexpected reasons, stop with server error
            raise HTTPException(status_code=500, detail="Failed to verify video status")

        report_text = ""
        try:
            sql_join = text(
                "SELECT pi.phase_index, pi.insight, vp.phase_description, vp.time_start, vp.time_end, "
                "vp.view_start, vp.view_end, vp.like_start, vp.like_end, vp.delta_view, vp.delta_like "
                "FROM phase_insights pi "
                "LEFT JOIN video_phases vp ON pi.video_id = vp.video_id AND pi.phase_index = vp.phase_index "
                "WHERE pi.video_id = :video_id "
                "ORDER BY pi.phase_index ASC"
            )
            res = await db.execute(sql_join, {"video_id": video_id})
            rows = res.fetchall()

            parts: List[str] = []
            if rows:
                for r in rows:
                    try:
                        idx = getattr(r, "phase_index", None) or r[0]
                    except Exception:
                        idx = r[0] if len(r) > 0 else "?"
                    try:
                        insight = getattr(r, "insight", None) or r[1]
                    except Exception:
                        insight = r[1] if len(r) > 1 else ""

                    try:
                        p_desc = getattr(r, "phase_description", None) or r[2]
                    except Exception:
                        p_desc = r[2] if len(r) > 2 else None
                    try:
                        p_time_start = getattr(r, "time_start", None) or r[3]
                    except Exception:
                        p_time_start = r[3] if len(r) > 3 else None
                    try:
                        p_time_end = getattr(r, "time_end", None) or r[4]
                    except Exception:
                        p_time_end = r[4] if len(r) > 4 else None
                    try:
                        p_view_start = getattr(r, "view_start", None) if hasattr(r, "view_start") else (r[5] if len(r) > 5 else None)
                    except Exception:
                        p_view_start = r[5] if len(r) > 5 else None
                    try:
                        p_view_end = getattr(r, "view_end", None) if hasattr(r, "view_end") else (r[6] if len(r) > 6 else None)
                    except Exception:
                        p_view_end = r[6] if len(r) > 6 else None
                    try:
                        p_like_start = getattr(r, "like_start", None) if hasattr(r, "like_start") else (r[7] if len(r) > 7 else None)
                    except Exception:
                        p_like_start = r[7] if len(r) > 7 else None
                    try:
                        p_like_end = getattr(r, "like_end", None) if hasattr(r, "like_end") else (r[8] if len(r) > 8 else None)
                    except Exception:
                        p_like_end = r[8] if len(r) > 8 else None
                    try:
                        p_delta_view = getattr(r, "delta_view", None) if hasattr(r, "delta_view") else (r[9] if len(r) > 9 else None)
                    except Exception:
                        p_delta_view = r[9] if len(r) > 9 else None
                    try:
                        p_delta_like = getattr(r, "delta_like", None) if hasattr(r, "delta_like") else (r[10] if len(r) > 10 else None)
                    except Exception:
                        p_delta_like = r[10] if len(r) > 10 else None

                    header = f"Phase {idx}"
                    if p_desc:
                        header += f": {p_desc}"
                    if p_time_start is not None or p_time_end is not None:
                        ts = f"{p_time_start if p_time_start is not None else ''}" \
                            f"-{p_time_end if p_time_end is not None else ''}"
                        header += f" ({ts}s)"

                    combined = header
                    if insight:
                        combined += f"\nInsight: {insight}"

                    metrics_lines = []
                    if p_view_start is not None or p_view_end is not None or p_delta_view is not None:
                        vs = f"start={p_view_start}" if p_view_start is not None else ""
                        ve = f"end={p_view_end}" if p_view_end is not None else ""
                        dv = f"delta={p_delta_view}" if p_delta_view is not None else ""
                        metrics = ", ".join([m for m in [vs, ve, dv] if m])
                        metrics_lines.append(f"Views: {metrics}")
                    if p_like_start is not None or p_like_end is not None or p_delta_like is not None:
                        ls = f"start={p_like_start}" if p_like_start is not None else ""
                        le = f"end={p_like_end}" if p_like_end is not None else ""
                        dl = f"delta={p_delta_like}" if p_delta_like is not None else ""
                        metrics = ", ".join([m for m in [ls, le, dl] if m])
                        metrics_lines.append(f"Likes: {metrics}")

                    if metrics_lines:
                        combined += "\n" + "\n".join(metrics_lines)

                    parts.append(combined)

            report_text = "\n\n".join(parts) if parts else ""
        except Exception:
            try:
                sql_insights = text(
                    "SELECT phase_index, insight FROM phase_insights WHERE video_id = :video_id ORDER BY phase_index ASC"
                )
                res_ins = await db.execute(sql_insights, {"video_id": video_id})
                rows_ins = res_ins.fetchall()

                phases_map: Dict[Any, Dict[str, Any]] = {}
                try:
                    sql_phases = text(
                        "SELECT phase_index, title, description, view_count, like_count FROM video_phases WHERE video_id = :video_id ORDER BY phase_index ASC"
                    )
                    res_ph = await db.execute(sql_phases, {"video_id": video_id})
                    rows_ph = res_ph.fetchall()
                    if rows_ph:
                        for r in rows_ph:
                            try:
                                p_idx = getattr(r, "phase_index", None) or r[0]
                            except Exception:
                                p_idx = r[0] if len(r) > 0 else None
                            try:
                                p_title = getattr(r, "title", None) or r[1]
                            except Exception:
                                p_title = r[1] if len(r) > 1 else None
                            try:
                                p_desc = getattr(r, "description", None) or r[2]
                            except Exception:
                                p_desc = r[2] if len(r) > 2 else None
                            try:
                                p_views = getattr(r, "view_count", None) if hasattr(r, "view_count") else (r[3] if len(r) > 3 else None)
                            except Exception:
                                p_views = r[3] if len(r) > 3 else None
                            try:
                                p_likes = getattr(r, "like_count", None) if hasattr(r, "like_count") else (r[4] if len(r) > 4 else None)
                            except Exception:
                                p_likes = r[4] if len(r) > 4 else None
                            if p_idx is not None:
                                phases_map[p_idx] = {
                                    "title": p_title or "",
                                    "description": p_desc or "",
                                    "views": p_views,
                                    "likes": p_likes,
                                }
                except Exception:
                    phases_map = {}

                parts: List[str] = []
                if rows_ins:
                    for r in rows_ins:
                        try:
                            idx = getattr(r, "phase_index", None) or r[0]
                        except Exception:
                            idx = r[0] if len(r) > 0 else "?"
                        try:
                            insight = getattr(r, "insight", None) or r[1]
                        except Exception:
                            insight = r[1] if len(r) > 1 else ""

                        phase_info = phases_map.get(idx)
                        if phase_info:
                            title = phase_info.get("title") or ""
                            desc = phase_info.get("description") or ""
                            header = f"Phase {idx}: {title}" if title else f"Phase {idx}"
                            combined = header
                            if desc:
                                combined += f" - {desc}"
                            if insight:
                                combined += f"\nInsight: {insight}"
                            views = phase_info.get("views")
                            likes = phase_info.get("likes")
                            metrics = []
                            if views is not None:
                                metrics.append(f"views={views}")
                            if likes is not None:
                                metrics.append(f"likes={likes}")
                            if metrics:
                                combined += f"\nMetrics: {', '.join(metrics)}"
                            parts.append(combined)
                        else:
                            parts.append(f"Phase {idx}: {insight}")
                report_text = "\n\n".join(parts) if parts else ""
            except Exception:
                report_text = ""

        # ── Fetch sales data from Qdrant (RAG knowledge base) ──
        sales_text = ""
        try:
            from app.services.rag.rag_client import get_qdrant_client, COLLECTION_NAME, init_collection
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            qclient = get_qdrant_client()
            init_collection(qclient)
            qresults, _ = qclient.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=Filter(
                    must=[FieldCondition(key="video_id", match=MatchValue(value=video_id))]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
            if qresults:
                payload_data = qresults[0].payload
                sd = payload_data.get("sales_data", {})
                sp = payload_data.get("set_products", [])
                sm = payload_data.get("screen_metrics", {})

                sales_parts: List[str] = []
                if sd:
                    if sd.get("gmv"): sales_parts.append(f"GMV（総売上）: ¥{sd['gmv']:,.0f}")
                    if sd.get("total_orders"): sales_parts.append(f"注文数: {sd['total_orders']}")
                    if sd.get("product_sales_count"): sales_parts.append(f"商品販売数: {sd['product_sales_count']}")
                    if sd.get("viewers"): sales_parts.append(f"視聴者数: {sd['viewers']:,.0f}")
                    if sd.get("impressions"): sales_parts.append(f"インプレッション: {sd['impressions']:,.0f}")
                    if sd.get("product_impressions"): sales_parts.append(f"商品インプレッション: {sd['product_impressions']:,.0f}")
                    if sd.get("product_clicks"): sales_parts.append(f"商品クリック数: {sd['product_clicks']:,.0f}")
                    if sd.get("live_ctr"): sales_parts.append(f"LIVE CTR: {sd['live_ctr']}%")
                    if sd.get("cvr"): sales_parts.append(f"CVR（転換率）: {sd['cvr']}%")
                    if sd.get("tap_through_rate"): sales_parts.append(f"タップスルー率: {sd['tap_through_rate']}%")
                    if sd.get("comment_rate"): sales_parts.append(f"コメント率: {sd['comment_rate']}%")
                    if sd.get("avg_gpm"): sales_parts.append(f"時間あたりGMV: ¥{sd['avg_gpm']:,.0f}")
                    if sd.get("duration_minutes"): sales_parts.append(f"配信時間: {sd['duration_minutes']}分")
                    if sd.get("follower_ratio"): sales_parts.append(f"フォロワー率: {sd['follower_ratio']}%")
                    if sd.get("traffic_sources"):
                        for src in sd["traffic_sources"]:
                            sales_parts.append(f"  トラフィック: {src.get('channel', '')} GMV {src.get('gmv_pct', '')}%")

                if sp:
                    sales_parts.append("")
                    sales_parts.append("【セット商品販売データ】")
                    for p in sp:
                        line = f"  {p.get('name', '')}: ¥{p.get('price', 0):,.0f} × {p.get('quantity_sold', 0)}個"
                        rev = p.get('set_revenue', 0)
                        if rev:
                            line += f" = ¥{rev:,.0f}"
                        sales_parts.append(line)

                if sm:
                    if sm.get("viewer_count"): sales_parts.append(f"リアルタイム視聴者数: {sm['viewer_count']}")
                    if sm.get("likes"): sales_parts.append(f"いいね数: {sm['likes']}")
                    if sm.get("shopping_rank"): sales_parts.append(f"ショッピングランキング: No.{sm['shopping_rank']}")
                    if sm.get("purchase_notifications"):
                        sales_parts.append(f"購入通知数: {len(sm['purchase_notifications'])}")

                if sales_parts:
                    sales_text = "\n【売上・パフォーマンスデータ】\n" + "\n".join(sales_parts)
        except Exception as e:
            # non-fatal: if Qdrant lookup fails, continue without sales data
            import traceback
            traceback.print_exc()
            sales_text = ""

        # ── Fetch product exposure data from DB ──
        product_exposure_text = ""
        try:
            sql_pe = text(
                "SELECT product_name, brand_name, time_start, time_end, confidence, source "
                "FROM video_product_exposures WHERE video_id = :vid ORDER BY time_start ASC"
            )
            pe_res = await db.execute(sql_pe, {"vid": video_id})
            pe_rows = pe_res.fetchall()
            if pe_rows:
                pe_parts: List[str] = ["\n【商品露出タイムライン】"]
                for r in pe_rows:
                    pname = r[0] or ""
                    bname = r[1] or ""
                    ts = r[2]
                    te = r[3]
                    label = f"{bname} {pname}".strip()
                    pe_parts.append(f"  {label}: {ts}s - {te}s")
                product_exposure_text = "\n".join(pe_parts)
        except Exception:
            product_exposure_text = ""

        # ── Fetch Excel data (product + trend) from Azure Blob ──
        excel_data_text = ""
        try:
            sql_excel = text(
                "SELECT v.excel_product_blob_url, v.excel_trend_blob_url, u.email "
                "FROM videos v JOIN users u ON v.user_id = u.id WHERE v.id = :vid"
            )
            excel_res = await db.execute(sql_excel, {"vid": video_id})
            excel_row = excel_res.fetchone()
            if excel_row:
                product_blob_url = excel_row[0]
                trend_blob_url = excel_row[1]
                user_email = excel_row[2]

                if product_blob_url or trend_blob_url:
                    import httpx
                    import tempfile
                    import openpyxl
                    import json as _json
                    from azure.storage.blob import generate_blob_sas, BlobSasPermissions
                    from datetime import timedelta, datetime, timezone
                    from urllib.parse import urlparse, unquote

                    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
                    account_name = ""
                    account_key = ""
                    for part in conn_str.split(";"):
                        if part.startswith("AccountName="):
                            account_name = part.split("=", 1)[1]
                        elif part.startswith("AccountKey="):
                            account_key = part.split("=", 1)[1]

                    def _gen_sas(blob_url: str) -> str:
                        try:
                            parsed = urlparse(blob_url)
                            path = unquote(parsed.path)
                            if path.startswith("/videos/"):
                                blob_name = path[len("/videos/"):]
                            else:
                                blob_name = path.lstrip("/")
                                if blob_name.startswith("videos/"):
                                    blob_name = blob_name[len("videos/"):]
                        except Exception:
                            filename = blob_url.split("/")[-1].split("?")[0]
                            blob_name = f"{user_email}/{video_id}/excel/{filename}"
                        expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
                        sas = generate_blob_sas(
                            account_name=account_name,
                            container_name="videos",
                            blob_name=blob_name,
                            account_key=account_key,
                            permission=BlobSasPermissions(read=True),
                            expiry=expiry,
                        )
                        return f"https://{account_name}.blob.core.windows.net/videos/{blob_name}?{sas}"

                    async def _parse_excel_for_chat(blob_url: str) -> list:
                        sas_url = _gen_sas(blob_url)
                        async with httpx.AsyncClient(timeout=15.0) as hclient:
                            resp = await hclient.get(sas_url)
                            if resp.status_code != 200:
                                return []
                            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
                                f.write(resp.content)
                                tmp_path = f.name
                            try:
                                wb = openpyxl.load_workbook(tmp_path, read_only=True, data_only=True)
                                ws = wb.active
                                items = []
                                if ws:
                                    rows_data = list(ws.iter_rows(values_only=True))
                                    if len(rows_data) >= 2:
                                        headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows_data[0])]
                                        for data_row in rows_data[1:]:
                                            if all(v is None for v in data_row):
                                                continue
                                            item = {}
                                            for i, val in enumerate(data_row):
                                                if i < len(headers):
                                                    if val is None:
                                                        item[headers[i]] = None
                                                    elif isinstance(val, (int, float)):
                                                        item[headers[i]] = val
                                                    else:
                                                        item[headers[i]] = str(val)
                                            items.append(item)
                                wb.close()
                                return items
                            finally:
                                os.unlink(tmp_path)

                    excel_parts: List[str] = []

                    if product_blob_url:
                        try:
                            products = await _parse_excel_for_chat(product_blob_url)
                            if products:
                                excel_parts.append("\n【商品販売データ（Excelアップロード）】")
                                # Format as readable table (limit to top 30 rows)
                                if products:
                                    headers = list(products[0].keys())
                                    excel_parts.append("  " + " | ".join(headers))
                                    for p in products[:30]:
                                        vals = []
                                        for h in headers:
                                            v = p.get(h)
                                            if v is None:
                                                vals.append("")
                                            elif isinstance(v, float):
                                                vals.append(f"{v:,.0f}" if v == int(v) else f"{v:,.2f}")
                                            else:
                                                vals.append(str(v))
                                        excel_parts.append("  " + " | ".join(vals))
                                    if len(products) > 30:
                                        excel_parts.append(f"  ... (他 {len(products) - 30} 行)")
                        except Exception as _e:
                            logger.debug(f"Non-critical error suppressed: {_e}")

                    if trend_blob_url:
                        try:
                            trends = await _parse_excel_for_chat(trend_blob_url)
                            if trends:
                                excel_parts.append("\n【トレンドデータ（Excelアップロード）】")
                                if trends:
                                    headers = list(trends[0].keys())
                                    excel_parts.append("  " + " | ".join(headers))
                                    for t in trends[:30]:
                                        vals = []
                                        for h in headers:
                                            v = t.get(h)
                                            if v is None:
                                                vals.append("")
                                            elif isinstance(v, float):
                                                vals.append(f"{v:,.0f}" if v == int(v) else f"{v:,.2f}")
                                            else:
                                                vals.append(str(v))
                                        excel_parts.append("  " + " | ".join(vals))
                                    if len(trends) > 30:
                                        excel_parts.append(f"  ... (他 {len(trends) - 30} 行)")
                        except Exception as _e:
                            logger.debug(f"Non-critical error suppressed: {_e}")

                    if excel_parts:
                        excel_data_text = "\n".join(excel_parts)
        except Exception:
            excel_data_text = ""

        system_msg = {
            "role": "system",
            "content": (
                "質問者の言語で回答してください。以下のレポートとデータに基づいて回答してください。\n"
                "データに含まれる数値は正確に引用してください。データにない情報は推測せず、その旨を伝えてください。\n\n"
                "【レポート】\n"
                + (report_text or "(レポートなし)")
                + sales_text
                + product_exposure_text
                + excel_data_text
            ),
        }

        # load recent chat history for this video (quick-history: last N QA pairs)
        history_msgs: List[Dict[str, Any]] = []
        try:
            history_limit = int(os.getenv("CHAT_HISTORY_LIMIT", "10"))
            sql_hist = text(
                "SELECT question, answer FROM chats WHERE video_id = :video_id ORDER BY created_at DESC LIMIT :limit"
            )
            hres = await db.execute(sql_hist, {"video_id": video_id, "limit": history_limit})
            hrows = hres.fetchall()
            if hrows:
                for r in list(reversed(hrows)):
                    try:
                        q_text = getattr(r, "question", None) or r[0]
                    except Exception:
                        q_text = r[0] if len(r) > 0 else ""
                    try:
                        a_text = getattr(r, "answer", None) or r[1]
                    except Exception:
                        a_text = r[1] if len(r) > 1 else ""
                    history_msgs.append({"role": "user", "content": q_text})
                    history_msgs.append({"role": "assistant", "content": a_text})
        except Exception:
            # non-fatal: if history load fails, continue without it
            history_msgs = []

        client = AzureOpenAI(api_key=api_key, azure_endpoint=endpoint, api_version=api_version)

        # accumulate parts in outer scope so background task can read them
        full_answer_parts: List[str] = []

        def event_generator():
            try:
                call_messages = [system_msg] + history_msgs + payload.messages

                # Responses API (new): messages -> input. Build input payload.
                input_payload = []
                for m in call_messages:
                    # keep structure role/content
                    try:
                        input_payload.append({"role": m.get("role"), "content": m.get("content")})
                    except Exception:
                        # skip malformed
                        continue

                resp = client.responses.create(
                    stream=True,
                    model=model,
                    input=input_payload,
                    max_output_tokens=payload.max_tokens,
                )

                # accumulate full answer to persist after stream
                for update in resp:
                    try:
                        # Try common fields for streamed chunks across SDKs
                        text_chunk = None
                        # delta events on the update object
                        if getattr(update, "delta", None):
                            text_chunk = getattr(update, "delta")
                        # direct text field
                        if not text_chunk:
                            text_chunk = getattr(update, "text", None)
                        # older field used by some events
                        if not text_chunk:
                            text_chunk = getattr(update, "output_text", None)

                        # dict-like fallback
                        if not text_chunk and isinstance(update, dict):
                            text_chunk = update.get("delta") or update.get("output_text") or update.get("text") or update.get("content")

                        # try choices/delta style fallback
                        if not text_chunk:
                            choices = getattr(update, "choices", None) or (update.get("choices") if isinstance(update, dict) else None)
                            if choices:
                                first = choices[0]
                                delta = getattr(first, "delta", None) or (first.get("delta") if isinstance(first, dict) else None)
                                if delta:
                                    text_chunk = getattr(delta, "text", None) or (delta.get("text") if isinstance(delta, dict) else None) or getattr(delta, "content", None) or (delta.get("content") if isinstance(delta, dict) else None)

                        # try output array structure
                        if not text_chunk:
                            out = getattr(update, "output", None) if not isinstance(update, dict) else update.get("output")
                            if out:
                                if isinstance(out, str):
                                    text_chunk = out
                                elif isinstance(out, list):
                                    parts = []
                                    for o in out:
                                        if isinstance(o, dict):
                                            c = o.get("content")
                                            if isinstance(c, str):
                                                parts.append(c)
                                            elif isinstance(c, list):
                                                for p in c:
                                                    if isinstance(p, dict):
                                                        parts.append(p.get("text") or p.get("content") or "")
                                    if parts:
                                        text_chunk = "".join(parts)

                        if text_chunk:
                            full_answer_parts.append(text_chunk)
                            yield f"data: {text_chunk}\n\n"
                    except Exception:
                        # ignore streaming chunk parse errors
                        continue

                # signal end
                yield "data: [DONE]\n\n"

                # after stream completes, leave persistence to background task
                pass

            except Exception as e:
                # send error as SSE and finish
                yield f"data: [ERROR] {str(e)}\n\n"
            finally:
                try:
                    client.close()
                except Exception as _e:
                    logger.debug(f"Non-critical error suppressed: {_e}")

        # background task: use synchronous psycopg2 insert so commit is immediate
        def _bg_save_sync() -> None:
            try:
                full_answer = "".join(full_answer_parts)
                try:
                    if "\\n" in full_answer or "\\r\\n" in full_answer:
                        full_answer = full_answer.replace('\\r\\n', '\r\n').replace('\\n', '\n')
                except Exception as _e:
                    logger.debug(f"Non-critical error suppressed: {_e}")
                question_text = None
                for m in reversed(payload.messages):
                    if m.get("role") == "user":
                        question_text = m.get("content")
                        break

                # adapt DATABASE_URL for psycopg2 if needed
                db_url = os.getenv("DATABASE_URL") or ""
                if db_url.startswith("postgresql+asyncpg://"):
                    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

                # connect and insert
                conn = psycopg2.connect(db_url)
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO chats (video_id, question, answer, id, created_at, updated_at) VALUES (%s, %s, %s, gen_random_uuid(), now(), now())",
                        (video_id, question_text, full_answer),
                    )
                    conn.commit()
                    cur.close()
                finally:
                    conn.close()
            except Exception:
                # non-fatal: swallow errors
                pass

        bg = BackgroundTask(_bg_save_sync)
        return StreamingResponse(event_generator(), media_type="text/event-stream", background=bg)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Streaming failure: {exc}")


@router.get("/history")
async def get_chat_history(
    video_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return chat history for a given video_id.

    Requires authentication. Returns JSON `{"data": [...]}` where each item
    contains `id`, `video_id`, `question`, `answer`, `created_at`, `updated_at`.
    """
    if not video_id:
        raise HTTPException(status_code=400, detail="Missing video_id")

    try:
        sql = text(
            "SELECT id, video_id, question, answer, created_at, updated_at FROM chats WHERE video_id = :video_id ORDER BY created_at ASC"
        )
        res = await db.execute(sql, {"video_id": video_id})
        rows = res.fetchall()

        out = []
        for r in rows:
            try:
                row_id = getattr(r, "id", None) or r[0]
            except Exception:
                row_id = r[0] if len(r) > 0 else None
            try:
                v_id = getattr(r, "video_id", None) or r[1]
            except Exception:
                v_id = r[1] if len(r) > 1 else None
            try:
                question = getattr(r, "question", None) or r[2]
            except Exception:
                question = r[2] if len(r) > 2 else None
            try:
                answer = getattr(r, "answer", None) or r[3]
            except Exception:
                answer = r[3] if len(r) > 3 else None
            try:
                created_at = getattr(r, "created_at", None) or r[4]
            except Exception:
                created_at = r[4] if len(r) > 4 else None
            try:
                updated_at = getattr(r, "updated_at", None) or r[5]
            except Exception:
                updated_at = r[5] if len(r) > 5 else None

            out.append(
                {
                    "id": row_id,
                    "video_id": v_id,
                    "question": question,
                    "answer": answer,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )

        return {"data": out}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat history: {exc}")
