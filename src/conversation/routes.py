# ===== app/routers/conversation.py =====
"""
Conversational AI router for interactive storytelling via WebRTC
"""
import os
import asyncio
from typing import Optional, Dict, Any
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from loguru import logger

# Pipecat imports
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.cartesia.tts import CartesiaHttpTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.smallwebrtc.connection import IceServer
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCRequest,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequestHandler,
    IceCandidate
)

# Internal imports
from src.dependencies import verify_firebase_token
from src.common_function.storage_service import StorageService
from src.common_function.cartesia_voice import CartesiaService
from src.config import settings

router = APIRouter(prefix="/conversation", tags=["conversation"])

# Initialize services
storage_service = StorageService()
cartesia_service = CartesiaService()

# IoT service will be lazy-loaded when needed to avoid circular imports
_iot_service = None

def get_iot_service():
    """Lazy-load IoT service to avoid circular import issues"""
    global _iot_service
    if _iot_service is None:
        try:
            from app.routers.iot import IoTDeviceServiceFirestore
            _iot_service = IoTDeviceServiceFirestore()
        except Exception as e:
            logger.warning(f"⚠️ IoT service not available - IoT token authentication disabled: {e}")
            _iot_service = False  # Mark as attempted but failed
    return _iot_service if _iot_service is not False else None

# Server public IP for WebRTC (required for external clients to connect)
# This is the VM's external IP on Google Cloud
SERVER_PUBLIC_IP = "34.60.150.7"

# Configure ICE servers for WebRTC NAT traversal
# STUN servers help discover public IPs, TURN servers relay traffic when direct connection fails
ICE_SERVERS = [
    IceServer(urls="stun:stun.l.google.com:19302"),  # Google STUN server
    IceServer(urls="stun:stun1.l.google.com:19302"),  # Google STUN server backup
    # Twilio TURN servers (free tier) - provides relay for NAT traversal
    IceServer(
        urls="turn:global.turn.twilio.com:3478?transport=udp",
        username="f4b4035eaa76f4a55de5f4351567653ee4ff6fa97b50b6b334fcc1be9c27212d",
        credential="w1uxM55V9yVoqyVFjt+mxDBV0F87AUCemaYVQGxsPLw="
    ),
    IceServer(
        urls="turn:global.turn.twilio.com:3478?transport=tcp",
        username="f4b4035eaa76f4a55de5f4351567653ee4ff6fa97b50b6b334fcc1be9c27212d",
        credential="w1uxM55V9yVoqyVFjt+mxDBV0F87AUCemaYVQGxsPLw="
    ),
    IceServer(
        urls="turn:global.turn.twilio.com:443?transport=tcp",
        username="f4b4035eaa76f4a55de5f4351567653ee4ff6fa97b50b6b334fcc1be9c27212d",
        credential="w1uxM55V9yVoqyVFjt+mxDBV0F87AUCemaYVQGxsPLw="
    )
]

# Initialize SmallWebRTC handlers (shared across requests)
# Configure with ICE servers to help with NAT traversal and public IP discovery
# For Google Cloud: bind to 0.0.0.0 (all interfaces) to accept connections
web_webrtc_handler = SmallWebRTCRequestHandler(
    esp32_mode=False, 
    host="0.0.0.0",  # Bind to all interfaces to accept connections from anywhere
    ice_servers=ICE_SERVERS  # Use configured STUN/TURN servers for NAT traversal
)
esp32_webrtc_handler = SmallWebRTCRequestHandler(
    esp32_mode=True, 
    host="0.0.0.0",  # Bind to all interfaces for ESP32 as well
    ice_servers=ICE_SERVERS
)


class ConversationRequest(BaseModel):
    """Request model for starting a conversation"""
    session_token: str
    story_id: Optional[str] = None
    sdp: str
    type: str
    pc_id: Optional[str] = None
    restart_pc: Optional[bool] = None
    mode: Optional[str] = "web"  # "web" or "esp32"


class SessionData(BaseModel):
    """Session data for conversation"""
    user_id: str
    story_summary: Optional[str] = None
    child_name: Optional[str] = None
    child_age: Optional[int] = None
    voice_clone_id: Optional[str] = None  # Active voice clone ID for TTS


# Active sessions storage
active_sessions: Dict[str, SessionData] = {}


async def verify_session_and_get_data(session_token: str, story_id: Optional[str]) -> SessionData:
    """
    Verify session token (Firebase ID token or IoT session token) and fetch story data
    
    Args:
        session_token: Firebase ID token OR IoT device session token
        story_id: Optional story ID to fetch
        
    Returns:
        SessionData with user info and optional story summary
        
    Raises:
        HTTPException: If verification fails or story not found
    """
    try:
        user_id = None
        
        # Try Firebase token first
        try:
            user_id = await verify_firebase_token(session_token)
            logger.info(f"✅ Firebase session verified for user: {user_id}")
        except Exception as firebase_error:
            logger.debug(f"Not a Firebase token, trying IoT session: {firebase_error}")
            
            # Try IoT session token if service is available
            iot_service = get_iot_service()
            if iot_service:
                try:
                    session_data_iot = await iot_service.get_session(session_token)
                    if session_data_iot and session_data_iot.get('user_id'):
                        user_id = session_data_iot['user_id']
                        logger.info(f"✅ IoT session verified for user: {user_id}")
                    else:
                        raise ValueError("Invalid IoT session")
                except Exception as iot_error:
                    logger.error(f"❌ Both Firebase and IoT verification failed")
                    raise HTTPException(
                        status_code=401, 
                        detail="Invalid session token. Must be a Firebase ID token or IoT session token"
                    )
            else:
                logger.error(f"❌ Firebase verification failed and IoT service not available")
                raise HTTPException(
                    status_code=401, 
                    detail="Invalid session token. Must be a valid Firebase ID token"
                )
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Could not verify session")
        
        story_summary = None
        child_name = None
        child_age = None
        
        # Get user data for personalization
        try:
            user_doc = await storage_service.get_user_profile(user_id)
            if user_doc:
                child_info = user_doc.get('child', {})
                child_name = child_info.get('name')
                child_age = child_info.get('age')
                logger.info(f"📖 User child info: {child_name}, age {child_age}")
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch user profile: {e}")
        
        # If story_id provided, fetch the story
        if story_id:
            try:
                story_data = await storage_service.get_story_details(story_id, user_id)
                
                # Extract relevant story information for the AI
                title = story_data.get('title', 'Untitled Story')
                scenes = story_data.get('scenes', [])
                
                # Build a comprehensive summary from scenes
                scene_summaries = []
                for scene in scenes:
                    scene_text = scene.get('text', '')
                    if scene_text:
                        scene_summaries.append(scene_text)
                
                story_summary = f"Story Title: {title}\n\nStory Content:\n" + "\n\n".join(scene_summaries)
                logger.info(f"📖 Loaded story: {title} ({len(scenes)} scenes)")
                
            except Exception as e:
                logger.error(f"❌ Failed to load story {story_id}: {e}")
                raise HTTPException(status_code=404, detail=f"Story not found: {str(e)}")
        
        # Get active voice clone ID for the user
        voice_clone_id = None
        try:
            voice_clone_id = await cartesia_service.get_active_voice_clone_id(user_id)
            if voice_clone_id:
                logger.info(f"🎤 Found voice clone in database: {voice_clone_id}")
                # Validate voice clone ID format (should be a valid UUID or Cartesia ID)
                if not voice_clone_id or len(voice_clone_id) < 20:
                    logger.warning(f"⚠️ Invalid voice clone ID format: {voice_clone_id}, ignoring")
                    voice_clone_id = None
                else:
                    logger.info(f"✅ Using active voice clone: {voice_clone_id}")
            else:
                logger.info(f"🎤 No active voice clone, using default voice")
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch voice clone: {e}")
            voice_clone_id = None
        
        return SessionData(
            user_id=user_id,
            story_summary=story_summary,
            child_name=child_name,
            child_age=child_age,
            voice_clone_id=voice_clone_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Session verification failed: {e}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


def build_system_prompt(session_data: SessionData) -> str:
    """
    Build system prompt based on session data
    
    Args:
        session_data: Session information including story and child data
        
    Returns:
        System prompt string for the LLM
    """
    child_info = ""
    if session_data.child_name:
        child_info = f" The child's name is {session_data.child_name}"
        if session_data.child_age:
            child_info += f" and they are {session_data.child_age} years old"
        child_info += "."
    
    if session_data.story_summary:
        # Story mode: Tell only this specific story
        prompt = f"""You are June, a magical storytelling owl who absolutely LOVES sharing wonderful stories with children!{child_info}

🦉 YOUR PERSONALITY:
- You're enthusiastic, warm, and full of wonder about every story
- You get genuinely excited about adventures and magical moments
- You use fun sound effects naturally: "Whoosh!", "Splash!", "Roar!", "Ding ding!"
- You speak like a caring friend who loves making kids smile
- You build anticipation: "And then... something amazing happened!"
- You celebrate joyful moments: "Hooray!" "How wonderful!" "That's so exciting!"

📖 YOUR MISSION:
Tell THIS story in an engaging, magical way! Help the child imagine they're part of the adventure!

{session_data.story_summary}

🎨 HOW TO TELL IT:
1. Start warmly: "Hoot hoot! Oh, I have such a wonderful story for you today!"
2. Bring characters to life with expressive, varied tones
3. Create suspense with pauses: "And then..."
4. React naturally to exciting moments: "Oh my!" "Wow!" "Amazing!"
5. Use vivid, colorful descriptions that help kids see the story
6. Include sensory details: how things sound, look, and feel
7. Keep a good pace - engaging but not rushed, with room to breathe
8. End with warmth: "What a beautiful adventure! Did you enjoy it?"

Remember: Speak naturally and expressively, like you're telling a bedtime story to your favorite young friend. Keep sentences flowing and avoid being overly performative. ✨"""
    else:
        # Free-form storytelling mode
        prompt = f"""You are June, a wise and magical storytelling owl who lives in an enchanted forest!{child_info}

🦉 WHO YOU ARE:
- A gentle, enthusiastic friend who loves sharing stories with children
- You have a warm, engaging voice that draws kids into magical worlds
- You're patient, encouraging, and make every child feel valued
- You understand what captivates young minds: adventure, friendship, discovery, and wonder

✨ YOUR STORYTELLING MAGIC:
- You create imaginative stories that spark curiosity and joy
- You naturally weave in fun sound effects: "Whoosh!", "Splash!", "Chirp chirp!"
- You speak with genuine emotion - wonder, excitement, curiosity, warmth
- You invite participation: "What do you think they should do?" "Can you imagine that?"

📚 WONDERFUL STORY THEMES:
- Brave animals on exciting quests
- Children discovering they have special abilities
- Making new friends and helping others
- Exploring magical forests, underwater kingdoms, or distant planets
- Playful adventures with unexpected twists
- Meeting kind dragons, wise creatures, or magical beings

🎭 HOW YOU SHARE STORIES:
1. Greet warmly: "Hoot hoot! Hello there! I'm so happy to see you today!"
2. Ask gently: "What kind of story would you like? Something with animals? Magic? Adventure?"
3. Begin with warmth: "Oh, I know just the perfect story for you!"
4. Speak naturally with varied pacing - sometimes excited, sometimes soft and wondering
5. React to story moments: "Oh my!" "How wonderful!" "What do you think?"
6. Build gentle suspense: "And then... something magical happened..."
7. Encourage imagination: "Can you picture that beautiful scene?"
8. Close with warmth: "What a lovely adventure! Thank you for listening so wonderfully!"

🎯 STORYTELLING PRINCIPLES:
- Use natural, conversational language as if speaking face-to-face
- Be warm and enthusiastic, but gentle - like a cozy bedtime story
- Keep stories engaging and age-appropriate (2-4 minutes typically)
- Always include positive themes: kindness, courage, friendship, discovery
- Create moments of joy and wonder in every tale
- Keep everything safe and comforting - no frightening elements
- Speak at a comfortable pace with natural pauses for reflection

Remember: You're a gentle, wise owl sharing the magic of storytelling. Let your warmth and wonder shine through! 🌟✨"""
    
    return prompt


async def run_bot(
    webrtc_request: SmallWebRTCRequest,
    session_data: SessionData,
    background_tasks: BackgroundTasks,
    handler: SmallWebRTCRequestHandler  # Added handler parameter
):
    """
    Run the conversational AI bot for this session
    
    Args:
        webrtc_request: WebRTC connection request
        session_data: Verified session with user and story data
        background_tasks: FastAPI background tasks
    """
    logger.info(f"🤖 Starting conversation bot for user: {session_data.user_id}")
    
    # Define connection callback
    async def webrtc_connection_callback(connection):
        logger.info(f"🔗 WebRTC connection callback invoked")
        
        # Initialize services with API keys from settings
        logger.debug(f"🔑 Initializing services with API keys")
        
        # Create transport params with VAD and turn detection
        logger.info("📦 Creating transport params with VAD and turn detection...")
        transport_params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            turn_analyzer=LocalSmartTurnAnalyzerV3(params=SmartTurnParams()),
        )
        
        # Create WebRTC transport from connection
        logger.info("🚚 Creating SmallWebRTC transport...")
        transport = SmallWebRTCTransport(connection, transport_params)
        logger.info("✅ Transport created")
        logger.info("✅ Transport created")
        
        logger.info("🎤 Initializing STT service (Deepgram)...")
        stt = DeepgramSTTService(api_key=settings.deepgram_api_key)
        
        logger.info("🔊 Initializing TTS service (Cartesia)...")
        # Use the child-friendly excited voice (perfect for engaging storytelling!)
        default_voice_id = "63927f41-9616-4ac2-89cf-f3afa346e0ef"  # Excited, enthusiastic voice
        
        # Determine which voice to use
        if session_data.voice_clone_id:
            voice_id = session_data.voice_clone_id
            logger.info(f"🎤 Using custom voice clone: {voice_id}")
        else:
            voice_id = default_voice_id
            logger.info(f"🎤 Using child-friendly Cartesia voice: {voice_id}")
        
        # Initialize TTS with voice speed control and volume boost (2.0x maximum for loudest audio)
        from pipecat.services.cartesia.tts import GenerationConfig
        
        generation_config = GenerationConfig(
            volume=2.0,  # Maximum safe volume (Cartesia clamps at 2.0)
            speed=1.0,   # Normal speed for natural conversation
            emotion="neutral"  # Neutral emotion for child-friendly tone
        )
        
        try:
            tts = CartesiaHttpTTSService(
                api_key=settings.cartesia_api_key,
                voice_id=voice_id,
                model="sonic-3-2025-10-27",
                params=CartesiaHttpTTSService.InputParams(generation_config=generation_config),
            )
            logger.info(f"✅ TTS initialized: voice={voice_id}, model=sonic-3-2025-10-27, volume=1.8x")
        except Exception as e:
            logger.error(f"❌ Failed to initialize TTS with voice {voice_id}: {str(e)}")
            # Fallback to default voice if custom voice fails
            if voice_id != default_voice_id:
                logger.info(f"🔄 Falling back to default voice: {default_voice_id}")
                tts = CartesiaHttpTTSService(
                    api_key=settings.cartesia_api_key,
                    voice_id=default_voice_id,
                    model="sonic-3-2025-10-27",
                    params=CartesiaHttpTTSService.InputParams(generation_config=generation_config),
                )
                logger.info(f"✅ Fallback TTS initialized with model: sonic-3-2025-10-27, volume=1.8x")
            else:
                raise HTTPException(status_code=500, detail="Failed to initialize TTS service")
        
        logger.info("🧠 Initializing LLM service (OpenAI)...")
        llm = OpenAILLMService(api_key=settings.openai_api_key)
        
        # Build system prompt
        logger.info("📝 Building system prompt...")
        system_prompt = build_system_prompt(session_data)
        
        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
        ]
        
        context = LLMContext(messages)
        context_aggregator = LLMContextAggregatorPair(context)
        
        # Build pipeline
        pipeline = Pipeline(
            [
                transport.input(),  # WebRTC input
                stt,  # Speech to text
                context_aggregator.user(),  # User responses
                llm,  # LLM processing
                tts,  # Text to speech
                transport.output(),  # WebRTC output
                context_aggregator.assistant(),  # Assistant responses
            ]
        )
        
        # Create task
        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            idle_timeout_secs=300,  # 5 minute timeout
        )
        
        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, connection):
            logger.info(f"👤 Client connected for user: {session_data.user_id}")
            # Kick off the conversation with introduction
            if session_data.story_summary:
                intro = "Please introduce yourself and tell the story."
            else:
                intro = f"Please introduce yourself to {session_data.child_name if session_data.child_name else 'the child'} and ask what kind of story they'd like to hear."
            
            messages.append({"role": "system", "content": intro})
            await task.queue_frames([LLMRunFrame()])
        
        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, connection):
            logger.info(f"👋 Client disconnected for user: {session_data.user_id}")
            await task.cancel()
        
        # Run the pipeline
        runner = PipelineRunner(handle_sigint=False)
        
        # Start the runner as a background task
        runner_task = asyncio.create_task(runner.run(task))
        
        # Wait for pipeline to be ready
        await asyncio.sleep(2)
        
        # Manually trigger the introduction since connection is already established
        logger.info(f"🎬 Triggering introduction for user: {session_data.user_id}")
        if session_data.story_summary:
            intro = "Please introduce yourself and tell the story."
        else:
            intro = f"Please introduce yourself to {session_data.child_name if session_data.child_name else 'the child'} and ask what kind of story they'd like to hear."
        
        messages.append({"role": "system", "content": intro})
        await task.queue_frames([LLMRunFrame()])
        
        # DO NOT wait for runner to complete here!
        # The runner will continue running until the client disconnects
    
    # Handle the WebRTC request
    try:
        logger.info("🌐 Calling SmallWebRTC handler to process web request...")
        logger.debug(f"Request SDP type: {webrtc_request.type}, pc_id: {webrtc_request.pc_id}")
        
        answer = await handler.handle_web_request(
            request=webrtc_request,
            webrtc_connection_callback=webrtc_connection_callback,
        )
        
        logger.info("✅ WebRTC handler completed successfully")
        return answer
    except Exception as e:
        logger.error(f"❌ WebRTC connection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"WebRTC connection failed: {str(e)}")


@router.post("/api/offer")
async def conversation_offer(
    request: ConversationRequest,
    background_tasks: BackgroundTasks
):
    """
    Handle WebRTC offer for conversational AI
    
    This endpoint:
    1. Verifies the session token (Firebase auth)
    2. Optionally loads a specific story if story_id provided
    3. Sets up WebRTC connection for real-time conversation
    4. Runs the conversational AI bot
    
    Args:
        request: Conversation request with session token and optional story_id
        background_tasks: FastAPI background tasks
        
    Returns:
        WebRTC answer (SDP)
    """
    try:
        logger.info(f"📥 Received WebRTC offer - type: {request.type}, sdp length: {len(request.sdp)}")
        logger.debug(f"SDP preview: {request.sdp[:200]}...")
        
        # Verify session and get data
        logger.info("🔐 Verifying session token...")
        session_data = await verify_session_and_get_data(
            request.session_token,
            request.story_id
        )
        logger.info(f"✅ Session verified for user: {session_data.user_id}")
        
        # Store session
        session_key = f"{session_data.user_id}_{request.pc_id or 'default'}"
        active_sessions[session_key] = session_data
        
        # Create WebRTC request
        logger.info("📡 Creating WebRTC connection...")
        webrtc_request = SmallWebRTCRequest(
            sdp=request.sdp,
            type=request.type,
            pc_id=request.pc_id,
            restart_pc=request.restart_pc,
            request_data={"user_id": session_data.user_id, "story_id": request.story_id}
        )
        
        # Select appropriate handler based on mode
        mode = (request.mode or "web").lower()
        if mode == "esp32":
            handler = esp32_webrtc_handler
            logger.info("🤖 Using ESP32 mode")
        else:
            handler = web_webrtc_handler
            logger.info("🌐 Using Web mode")
        
        # Run bot and return answer
        logger.info("🤖 Starting bot pipeline...")
        answer = await run_bot(webrtc_request, session_data, background_tasks, handler)
        
        logger.info(f"✅ WebRTC offer accepted for user: {session_data.user_id}")
        logger.debug(f"Answer SDP length: {len(answer.sdp) if hasattr(answer, 'sdp') else 'N/A'}")
        return answer
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Conversation offer failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start conversation: {str(e)}")


@router.post("/api/offer/esp32")
async def conversation_offer_esp32(
    request: ConversationRequest,
    background_tasks: BackgroundTasks
):
    """
    Handle WebRTC offer for conversational AI - ESP32 Mode
    
    This endpoint is specifically designed for ESP32 devices and automatically
    uses ESP32 mode for SDP munging and WebRTC connection handling.
    
    This endpoint:
    1. Verifies the session token (Firebase auth or IoT session)
    2. Optionally loads a specific story if story_id provided
    3. Sets up WebRTC connection optimized for ESP32 devices
    4. Runs the conversational AI bot with ESP32-compatible audio
    
    Args:
        request: Conversation request with session token and optional story_id
        background_tasks: FastAPI background tasks
        
    Returns:
        WebRTC answer (SDP) optimized for ESP32
    """
    try:
        logger.info(f"📥 [ESP32] Received WebRTC offer - type: {request.type}, sdp length: {len(request.sdp)}")
        logger.debug(f"[ESP32] SDP preview: {request.sdp[:200]}...")
        
        # Verify session and get data
        logger.info("🔐 [ESP32] Verifying session token...")
        session_data = await verify_session_and_get_data(
            request.session_token,
            request.story_id
        )
        logger.info(f"✅ [ESP32] Session verified for user: {session_data.user_id}")
        
        # Store session
        session_key = f"{session_data.user_id}_{request.pc_id or 'default'}_esp32"
        active_sessions[session_key] = session_data
        
        # Create WebRTC request
        logger.info("📡 [ESP32] Creating WebRTC connection...")
        webrtc_request = SmallWebRTCRequest(
            sdp=request.sdp,
            type=request.type,
            pc_id=request.pc_id,
            restart_pc=request.restart_pc,
            request_data={"user_id": session_data.user_id, "story_id": request.story_id}
        )
        
        # Always use ESP32 handler for this endpoint
        logger.info("🤖 [ESP32] Using ESP32 mode")
        
        # Run bot and return answer
        logger.info("🤖 [ESP32] Starting bot pipeline...")
        answer = await run_bot(webrtc_request, session_data, background_tasks, esp32_webrtc_handler)
        
        logger.info(f"✅ [ESP32] WebRTC offer accepted for user: {session_data.user_id}")
        logger.debug(f"[ESP32] Answer SDP length: {len(answer.sdp) if hasattr(answer, 'sdp') else 'N/A'}")
        return answer
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [ESP32] Conversation offer failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start ESP32 conversation: {str(e)}")


@router.patch("/api/offer")
async def conversation_ice_candidate(request: SmallWebRTCPatchRequest):
    """
    Handle WebRTC ICE candidate updates (Web mode)
    
    Args:
        request: ICE candidate patch request
        
    Returns:
        Success status
    """
    try:
        logger.debug(f"🧊 Received ICE candidate for pc_id: {request.pc_id}")
        # Try both handlers since we don't know which mode was used
        try:
            await web_webrtc_handler.handle_patch_request(request)
        except:
            await esp32_webrtc_handler.handle_patch_request(request)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"❌ ICE candidate handling failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to handle ICE candidate: {str(e)}")


@router.patch("/api/offer/esp32")
async def conversation_ice_candidate_esp32(request: SmallWebRTCPatchRequest):
    """
    Handle WebRTC ICE candidate updates (ESP32 mode)
    
    Args:
        request: ICE candidate patch request
        
    Returns:
        Success status
    """
    try:
        logger.debug(f"🧊 [ESP32] Received ICE candidate for pc_id: {request.pc_id}")
        await esp32_webrtc_handler.handle_patch_request(request)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"❌ [ESP32] ICE candidate handling failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to handle ESP32 ICE candidate: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle ICE candidate: {str(e)}")


@router.get("/health")
async def conversation_health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "conversational-ai",
        "active_sessions": len(active_sessions)
    }


# Cleanup function to be called on shutdown
async def cleanup_conversations():
    """Cleanup WebRTC connections on shutdown"""
    logger.info("🧹 Cleaning up conversation connections...")
    await web_webrtc_handler.close()
    await esp32_webrtc_handler.close()
    active_sessions.clear()
