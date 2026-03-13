"""
Digital Human (數智人) Livestream API Endpoints

These endpoints provide the AitherHub ↔ Tencent Cloud IVH + ElevenLabs integration:

  === Liveroom Management ===
  POST /api/v1/digital-human/liveroom/create     – Create livestream room (supports hybrid voice mode)
  GET  /api/v1/digital-human/liveroom/{id}        – Query livestream room status
  GET  /api/v1/digital-human/liverooms            – List all active livestream rooms
  POST /api/v1/digital-human/liveroom/{id}/takeover – Send real-time interjection (supports hybrid voice)
  POST /api/v1/digital-human/liveroom/{id}/close  – Close livestream room

  === Script & Audio Generation ===
  POST /api/v1/digital-human/script/generate      – Generate script from analysis (preview)
  POST /api/v1/digital-human/audio/generate       – Pre-generate audio with cloned voice

  === Voice & Health ===
  GET  /api/v1/digital-human/voices               – List available ElevenLabs voices
  GET  /api/v1/digital-human/health               – Health check (both services)

Architecture:
  Hybrid mode combines ElevenLabs TTS (voice cloning, supports Japanese)
  with Tencent Cloud Digital Human (lip-sync, visual rendering).

  ┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
  │  Text Input  │────▶│ ElevenLabs   │────▶│ Tencent Cloud    │
  │  (台本/評論) │     │ TTS API      │     │ Digital Human    │
  │              │     │ (声音克隆)    │     │ (口型同步+直播)   │
  └─────────────┘     │ PCM 16kHz    │     │ Audio Driver     │
                      └──────────────┘     └──────────────────┘
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.digital_human_schema import (
    CreateLiveroomRequest,
    CreateLiveroomResponse,
    GetLiveroomResponse,
    ListLiveroomsResponse,
    TakeoverRequest,
    TakeoverResponse,
    CloseLiveroomResponse,
    GenerateScriptRequest,
    GenerateScriptResponse,
    HybridHealthResponse,
    GenerateAudioRequest,
    GenerateAudioResponse,
    VoiceListResponse,
)
from app.services.tencent_digital_human_service import (
    TencentDigitalHumanService,
    TencentAPIError,
    ScriptReq,
    VideoLayer,
    SpeechParam,
    AnchorParam,
    LIVEROOM_STATUS,
)
from app.services.elevenlabs_tts_service import (
    ElevenLabsTTSService,
    ElevenLabsError,
)
from app.services.hybrid_livestream_service import HybridLivestreamService
from app.services.script_generator_service import (
    generate_liveroom_scripts,
    generate_takeover_script,
    fetch_video_analysis,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/digital-human",
    tags=["Digital Human (數智人)"],
)

# ──────────────────────────────────────────────
# Auth dependency (PoC: admin key only)
# ──────────────────────────────────────────────

ADMIN_KEY = "aither:hub"


async def verify_admin_key(x_admin_key: str = Header(...)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return True


# ──────────────────────────────────────────────
# Service singletons
# ──────────────────────────────────────────────

_tencent_service: Optional[TencentDigitalHumanService] = None
_elevenlabs_service: Optional[ElevenLabsTTSService] = None
_hybrid_service: Optional[HybridLivestreamService] = None


def get_tencent_service() -> TencentDigitalHumanService:
    global _tencent_service
    if _tencent_service is None:
        _tencent_service = TencentDigitalHumanService()
    return _tencent_service


def get_elevenlabs_service() -> ElevenLabsTTSService:
    global _elevenlabs_service
    if _elevenlabs_service is None:
        _elevenlabs_service = ElevenLabsTTSService()
    return _elevenlabs_service


def get_hybrid_service() -> HybridLivestreamService:
    global _hybrid_service
    if _hybrid_service is None:
        _hybrid_service = HybridLivestreamService(
            elevenlabs_service=get_elevenlabs_service(),
            tencent_service=get_tencent_service(),
        )
    return _hybrid_service


# ══════════════════════════════════════════════
# LIVEROOM MANAGEMENT
# ══════════════════════════════════════════════

# ──────────────────────────────────────────────
# 1. Create Liveroom
# ──────────────────────────────────────────────

@router.post(
    "/liveroom/create",
    response_model=CreateLiveroomResponse,
    summary="Create a digital human livestream room",
    description=(
        "Create a new Tencent Cloud IVH livestream room. "
        "If video_id is provided, scripts are auto-generated from AitherHub analysis results. "
        "Set use_hybrid_voice=true to pre-generate audio with ElevenLabs voice cloning."
    ),
)
async def create_liveroom(
    req: CreateLiveroomRequest,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_admin_key),
):
    service = get_tencent_service()

    try:
        # Generate or use provided scripts
        if req.video_id:
            logger.info(f"Generating scripts from video analysis: {req.video_id}")
            script_dicts = await generate_liveroom_scripts(
                db=db,
                video_id=req.video_id,
                product_focus=req.product_focus,
                tone=req.tone,
                language=req.language,
            )
            scripts_text = [sd["Content"] for sd in script_dicts]
        elif req.scripts:
            scripts_text = req.scripts
        else:
            raise HTTPException(
                status_code=400,
                detail="Either video_id or scripts must be provided",
            )

        # Hybrid mode: pre-generate audio with ElevenLabs
        audio_results = None
        mode = "text_only"
        if req.use_hybrid_voice:
            mode = "hybrid"
            hybrid = get_hybrid_service()
            try:
                audio_results = await hybrid.generate_script_audio(
                    scripts=scripts_text,
                    language=req.language,
                    voice_id=req.elevenlabs_voice_id,
                )
                logger.info(
                    f"Hybrid audio generated: {len(audio_results)} scripts"
                )
            except ElevenLabsError as e:
                logger.warning(f"ElevenLabs audio generation failed, continuing with text: {e}")
                audio_results = [{"status": "error", "error": str(e)}]

        # Build script objects for Tencent API
        scripts = []
        for text in scripts_text:
            bgs = []
            if req.backgrounds:
                bgs = [
                    VideoLayer(url=bg.url, x=bg.x, y=bg.y, width=bg.width, height=bg.height)
                    for bg in req.backgrounds
                ]
            scripts.append(ScriptReq(content=text, backgrounds=bgs))

        # Build optional params
        speech_param = None
        if req.speech_param:
            speech_param = SpeechParam(
                speed=req.speech_param.speed,
                timbre_key=req.speech_param.timbre_key,
                volume=req.speech_param.volume,
                pitch=req.speech_param.pitch,
            )

        anchor_param = None
        if req.anchor_param:
            anchor_param = AnchorParam(
                horizontal_position=req.anchor_param.horizontal_position,
                vertical_position=req.anchor_param.vertical_position,
                scale=req.anchor_param.scale,
            )

        # Call Tencent API
        result = await service.open_liveroom(
            scripts=scripts,
            cycle_times=req.cycle_times,
            callback_url=req.callback_url,
            virtualman_project_id=req.virtualman_project_id,
            protocol=req.protocol,
            speech_param=speech_param,
            anchor_param=anchor_param,
        )

        status_code = result.get("Status", 0)
        return CreateLiveroomResponse(
            success=True,
            liveroom_id=result.get("LiveRoomId"),
            status=status_code,
            status_label=LIVEROOM_STATUS.get(status_code, "UNKNOWN"),
            req_id=result.get("ReqId"),
            play_url=result.get("VideoStreamPlayUrl"),
            script_preview=scripts[0].content[:500] if scripts else None,
            mode=mode,
            audio_results=audio_results,
        )

    except TencentAPIError as e:
        logger.error(f"Tencent API error creating liveroom: {e}")
        return CreateLiveroomResponse(success=False, error=str(e))
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return CreateLiveroomResponse(success=False, error=str(e))
    except Exception as e:
        logger.exception(f"Unexpected error creating liveroom: {e}")
        return CreateLiveroomResponse(success=False, error=f"Internal error: {str(e)}")


# ──────────────────────────────────────────────
# 2. Get Liveroom Status
# ──────────────────────────────────────────────

@router.get(
    "/liveroom/{liveroom_id}",
    response_model=GetLiveroomResponse,
    summary="Query livestream room status",
)
async def get_liveroom(
    liveroom_id: str,
    _auth: bool = Depends(verify_admin_key),
):
    service = get_tencent_service()

    try:
        result = await service.get_liveroom(liveroom_id)
        status_code = result.get("Status", 0)
        return GetLiveroomResponse(
            success=True,
            liveroom_id=result.get("LiveRoomId"),
            status=status_code,
            status_label=LIVEROOM_STATUS.get(status_code, "UNKNOWN"),
            play_url=result.get("VideoStreamPlayUrl"),
            details=result,
        )
    except TencentAPIError as e:
        return GetLiveroomResponse(success=False, error=str(e))
    except Exception as e:
        logger.exception(f"Error getting liveroom: {e}")
        return GetLiveroomResponse(success=False, error=f"Internal error: {str(e)}")


# ──────────────────────────────────────────────
# 3. List Liverooms
# ──────────────────────────────────────────────

@router.get(
    "/liverooms",
    response_model=ListLiveroomsResponse,
    summary="List all active livestream rooms",
)
async def list_liverooms(
    page_size: int = 20,
    page_index: int = 1,
    _auth: bool = Depends(verify_admin_key),
):
    service = get_tencent_service()

    try:
        result = await service.list_liverooms(
            page_size=page_size,
            page_index=page_index,
        )
        liverooms = result.get("LiveRoomList", [])
        return ListLiveroomsResponse(success=True, liverooms=liverooms)
    except TencentAPIError as e:
        return ListLiveroomsResponse(success=False, error=str(e))
    except Exception as e:
        logger.exception(f"Error listing liverooms: {e}")
        return ListLiveroomsResponse(success=False, error=f"Internal error: {str(e)}")


# ──────────────────────────────────────────────
# 4. Takeover (Real-time Interjection)
# ──────────────────────────────────────────────

@router.post(
    "/liveroom/{liveroom_id}/takeover",
    response_model=TakeoverResponse,
    summary="Send real-time interjection to livestream",
    description=(
        "Interrupt the current script and have the digital human speak the given text immediately. "
        "If content is not provided, it will be auto-generated from event_context. "
        "Set use_hybrid_voice=true to also generate audio with cloned voice."
    ),
)
async def takeover_liveroom(
    liveroom_id: str,
    req: TakeoverRequest,
    _auth: bool = Depends(verify_admin_key),
):
    service = get_tencent_service()

    try:
        # Determine content
        if req.content:
            content = req.content
        elif req.event_context:
            content = await generate_takeover_script(
                context=req.event_context,
                event_type=req.event_type,
                language=req.language,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Either content or event_context must be provided",
            )

        # Hybrid mode: generate audio with ElevenLabs
        audio_info = None
        mode = "text_only"
        if req.use_hybrid_voice:
            mode = "hybrid"
            hybrid = get_hybrid_service()
            try:
                result = await hybrid.takeover_with_voice(
                    liveroom_id=liveroom_id,
                    text=content,
                    language=req.language,
                    voice_id=req.elevenlabs_voice_id,
                )
                audio_info = result.get("audio_info")
                return TakeoverResponse(
                    success=True,
                    content_sent=content,
                    mode=mode,
                    audio_info=audio_info,
                )
            except Exception as e:
                logger.warning(f"Hybrid takeover failed, falling back to text: {e}")
                audio_info = {"status": "failed", "error": str(e)}

        # Standard text-based takeover
        result = await service.takeover(liveroom_id, content)
        return TakeoverResponse(
            success=True,
            content_sent=content,
            mode=mode,
            audio_info=audio_info,
        )

    except TencentAPIError as e:
        return TakeoverResponse(success=False, error=str(e))
    except Exception as e:
        logger.exception(f"Error in takeover: {e}")
        return TakeoverResponse(success=False, error=f"Internal error: {str(e)}")


# ──────────────────────────────────────────────
# 5. Close Liveroom
# ──────────────────────────────────────────────

@router.post(
    "/liveroom/{liveroom_id}/close",
    response_model=CloseLiveroomResponse,
    summary="Close a livestream room",
)
async def close_liveroom(
    liveroom_id: str,
    _auth: bool = Depends(verify_admin_key),
):
    service = get_tencent_service()

    try:
        result = await service.close_liveroom(liveroom_id)
        return CloseLiveroomResponse(success=True, liveroom_id=liveroom_id)
    except TencentAPIError as e:
        return CloseLiveroomResponse(success=False, error=str(e))
    except Exception as e:
        logger.exception(f"Error closing liveroom: {e}")
        return CloseLiveroomResponse(success=False, error=f"Internal error: {str(e)}")


# ══════════════════════════════════════════════
# SCRIPT & AUDIO GENERATION
# ══════════════════════════════════════════════

# ──────────────────────────────────────────────
# 6. Generate Script (Preview, no liveroom)
# ──────────────────────────────────────────────

@router.post(
    "/script/generate",
    response_model=GenerateScriptResponse,
    summary="Generate livestream script from video analysis",
    description=(
        "Generate a digital human livestream script from AitherHub video analysis results. "
        "This endpoint does NOT create a liveroom — it's for previewing and editing scripts."
    ),
)
async def generate_script(
    req: GenerateScriptRequest,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_admin_key),
):
    try:
        # Fetch analysis data for metadata
        analysis_data = await fetch_video_analysis(db, req.video_id)
        phases_count = len(analysis_data.get("phases", []))

        # Generate scripts
        script_dicts = await generate_liveroom_scripts(
            db=db,
            video_id=req.video_id,
            product_focus=req.product_focus,
            tone=req.tone,
            language=req.language,
        )

        script_text = script_dicts[0]["Content"] if script_dicts else ""

        return GenerateScriptResponse(
            success=True,
            video_id=req.video_id,
            script=script_text,
            script_length=len(script_text),
            phases_used=phases_count,
        )

    except ValueError as e:
        return GenerateScriptResponse(success=False, error=str(e))
    except Exception as e:
        logger.exception(f"Error generating script: {e}")
        return GenerateScriptResponse(success=False, error=f"Internal error: {str(e)}")


# ──────────────────────────────────────────────
# 7. Generate Audio (ElevenLabs voice cloning)
# ──────────────────────────────────────────────

@router.post(
    "/audio/generate",
    response_model=GenerateAudioResponse,
    summary="Pre-generate audio with cloned voice",
    description=(
        "Generate speech audio from text using ElevenLabs voice cloning. "
        "Supports 32+ languages including Japanese. "
        "Audio is generated in PCM 16kHz format compatible with Tencent Cloud audio driver."
    ),
)
async def generate_audio(
    req: GenerateAudioRequest,
    _auth: bool = Depends(verify_admin_key),
):
    try:
        hybrid = get_hybrid_service()
        results = await hybrid.generate_script_audio(
            scripts=req.texts,
            language=req.language,
            voice_id=req.voice_id,
        )

        total_duration = sum(
            r.get("duration_ms", 0) for r in results if r.get("status") == "ok"
        )

        return GenerateAudioResponse(
            success=True,
            results=results,
            total_duration_ms=round(total_duration, 1),
        )

    except ElevenLabsError as e:
        return GenerateAudioResponse(success=False, error=str(e))
    except Exception as e:
        logger.exception(f"Error generating audio: {e}")
        return GenerateAudioResponse(success=False, error=f"Internal error: {str(e)}")


# ══════════════════════════════════════════════
# VOICE & HEALTH
# ══════════════════════════════════════════════

# ──────────────────────────────────────────────
# 8. List Voices
# ──────────────────────────────────────────────

@router.get(
    "/voices",
    response_model=VoiceListResponse,
    summary="List available ElevenLabs voices",
    description="List all voices including cloned voices available for TTS.",
)
async def list_voices(
    _auth: bool = Depends(verify_admin_key),
):
    try:
        el_service = get_elevenlabs_service()
        voices = await el_service.list_voices()

        # Simplify voice data for response
        voice_list = []
        cloned_count = 0
        for v in voices:
            is_cloned = v.get("category") == "cloned"
            if is_cloned:
                cloned_count += 1
            voice_list.append({
                "voice_id": v.get("voice_id"),
                "name": v.get("name"),
                "category": v.get("category"),
                "labels": v.get("labels", {}),
                "is_cloned": is_cloned,
            })

        return VoiceListResponse(
            success=True,
            voices=voice_list,
            cloned_count=cloned_count,
            total_count=len(voice_list),
        )

    except ElevenLabsError as e:
        return VoiceListResponse(success=False, error=str(e))
    except Exception as e:
        logger.exception(f"Error listing voices: {e}")
        return VoiceListResponse(success=False, error=f"Internal error: {str(e)}")


# ──────────────────────────────────────────────
# 9. Health Check
# ──────────────────────────────────────────────

@router.get(
    "/health",
    response_model=HybridHealthResponse,
    summary="Health check for digital human services",
    description="Check connectivity to both Tencent Cloud IVH and ElevenLabs APIs.",
)
async def health_check(
    _auth: bool = Depends(verify_admin_key),
):
    try:
        hybrid = get_hybrid_service()
        result = await hybrid.health_check()

        return HybridHealthResponse(
            success=True,
            overall_status=result.get("status"),
            elevenlabs=result.get("elevenlabs"),
            tencent=result.get("tencent"),
            capabilities=result.get("capabilities"),
        )

    except Exception as e:
        logger.exception(f"Health check error: {e}")
        return HybridHealthResponse(
            success=False,
            error=f"Health check failed: {str(e)}",
        )
