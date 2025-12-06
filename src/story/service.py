# ===== app/services/story_service.py =====
import json
import uuid
import re
from typing import List, Tuple, Dict, Any, Optional
from fastapi import HTTPException
from openai import OpenAI
from src.story.schema import StoryScene
from src.core.config import settings

class StoryService:
    def __init__(self, openai_client: OpenAI, user_service, db_session=None):
        self.openai_client = openai_client
        self.user_service = user_service
        self.db_session = db_session  # Database session for user profile queries
    
    def _should_include_child_in_story(self, user_prompt: str, child_name: str) -> bool:
        """Determine if the child should be included as a character in the story"""
        # Keywords that suggest the child should be included
        include_keywords = [
            child_name.lower(),
            "me", "my", "myself", "i want", "i am",
            "protagonist", "main character", "hero", "adventure",
            "journey", "quest", "explore", "discover",
            "learn", "experience", "meet", "find"
        ]
        
        # Keywords that suggest the child should NOT be included
        exclude_keywords = [
            "about", "story about", "tell me about",
            "what is", "how does", "why do", "where is",
            "fairy tale", "classic story", "bedtime story",
            "animal story", "animals only", "no people"
        ]
        
        prompt_lower = user_prompt.lower()
        
        # Check for exclude keywords first
        for keyword in exclude_keywords:
            if keyword in prompt_lower:
                return False
        
        # Check for include keywords
        for keyword in include_keywords:
            if keyword in prompt_lower:
                return True
        
        # Default: include child if prompt suggests adventure/interactive story
        interactive_indicators = [
            "adventure", "journey", "quest", "explore", "discover",
            "interactive", "choose", "decide", "help", "save",
            "rescue", "find", "meet", "make friends"
        ]
        
        for indicator in interactive_indicators:
            if indicator in prompt_lower:
                return True
        
        # Default to not including child for general stories
        return False
    
    async def generate_story_scenes(self, user_prompt: str, user_id: str, 
                                   target_scenes: int = 7,
                                   child_id: str = None,  # NEW: Child ID for parent-centric model
                                   child_name: str = None,  # Legacy: backward compatibility
                                   child_age: int = None,  # Legacy: backward compatibility
                                   morals: List[str] = None,
                                   story_length: str = "medium",
                                   art_style: str = "magical",
                                   language: str = "english",
                                   # NEW: Reference images metadata with AI descriptions
                                   reference_images_metadata: List[Dict[str, Any]] = None,
                                   # Legacy parameters for backward compatibility
                                   genre: str = "Adventure", 
                                   age_group: str = "6-8", 
                                   moral_lesson: str = "friendship", 
                                   emotion: str = "happiness",
                                   # Ambient sound parameters (used later in audio processing)
                                   ambient_keywords: List[str] = None) -> Tuple[List[StoryScene], str, str, str]:
        """
        Generate story scenes using OpenAI GPT (PARENT-CENTRIC MODEL)
        Now returns: (scenes, title, art_style, child_id)
        
        NOTE: This service uses OpenAI for story generation. Database operations
        are handled separately in story_service_pg.py
        """
        try:
            # Get user-specific system prompt from database (via user_service)
            # user_id here is firebase_user_id (string)
            
            # Lambda mode: Skip user profile fetch if db_session not available
            # and child_name is provided (from SQS message snapshot)
            if not self.db_session and child_name:
                print(f"⚡ Lambda mode: Using provided child data (no DB lookup)")
                user_profile = {'system_prompt': None}  # Default empty profile
                child_info = {'name': child_name, 'age': child_age} if child_name else None
                actual_child_id = child_id
            elif not self.db_session:
                raise HTTPException(status_code=500, detail="Database session not available for user profile fetch")
            else:
                # Normal mode: Fetch user profile from database
                user_profile = await self.user_service.get_user_profile(self.db_session, user_id)
                if not user_profile:
                    raise HTTPException(status_code=404, detail="User profile not found")
                
                # NEW: Parent-centric model - fetch child data
                child_info = None
                actual_child_id = None
                
                if child_id:
                    # Explicit child_id provided - fetch from children sub-collection
                    from src.children.service import child_service
                    child = await child_service.get_child(user_id, child_id)
                    if not child:
                        raise HTTPException(status_code=404, detail=f"Child profile not found: {child_id}")
                    child_info = child.dict()
                    actual_child_id = child_id
                    print(f"✅ Using specified child: {child_info.get('name')} (ID: {child_id})")
                else:
                    # No child_id - use default child or fall back to legacy
                    default_child_id = user_profile.get('default_child_id')
                    if default_child_id:
                        # Use default child from parent-centric model
                        from src.children.service import child_service
                        child = await child_service.get_child(user_id, default_child_id)
                        if child:
                            child_info = child.dict()
                            actual_child_id = default_child_id
                            print(f"✅ Using default child: {child_info.get('name')} (ID: {default_child_id})")
                    else:
                        # BACKWARD COMPATIBILITY: Fall back to old single-child model
                        child_info = user_profile.get('child', {})
                        if child_info:
                            print(f"⚠️ Using legacy single-child model for user {user_id}")
            
            # If still no child info, create minimal default
            if not child_info:
                child_info = {
                    'name': 'the child',
                    'age': 6,
                    'interests': []
                }
                print(f"⚠️ No child profile found, using defaults")
            
            # Extract child details
            child_interests = child_info.get('interests', [])
            child_image_url = child_info.get('image_url')
            
            # Use provided child info (legacy params) or get from child profile
            actual_child_name = child_name if child_name else child_info.get('name', 'the child')
            actual_child_age = child_age if child_age else child_info.get('age', 6)
            
            # Get personalized system prompt from user profile (safe for Lambda mode)
            if user_profile:
                # Use child-specific system prompt if available, fallback to user's system prompt
                system_prompt = child_info.get('child_prompt') or user_profile.get('system_prompt') or settings.default_system_prompt
            else:
                # Lambda mode: no user profile, use child-specific or default
                child_prompt_value = child_info.get('child_prompt')
                system_prompt = child_prompt_value if child_prompt_value else settings.default_system_prompt
                print(f"🔍 Lambda mode system prompt: child_prompt={child_prompt_value}, using={'child_prompt' if child_prompt_value else 'default'}")
            
            # Handle morals format (new List[str] format or legacy string format)
            if morals is None:
                morals_text = "sharing, kindness, friendship"
            elif isinstance(morals, list):
                morals_text = ", ".join(morals)
            else:
                morals_text = str(morals)
            
            # Determine if child should be included in the story
            should_include_child = self._should_include_child_in_story(user_prompt, actual_child_name)
            
            # Parse @mentions from user_prompt and auto-include referenced characters
            reference_images_metadata = reference_images_metadata or []
            
            # AUTO-ADD CHILD'S IMAGE TO REFERENCE METADATA if child should be included
            child_reference_id = None  # Track the child's reference ID for OpenAI
            if should_include_child and child_image_url:
                # Check if child already exists in reference_images_metadata
                child_in_metadata = any(
                    ref.get('person_name', '').lower() == actual_child_name.lower() or
                    ref.get('relation', '').lower() in ['child', 'self']
                    for ref in reference_images_metadata
                )
                
                if not child_in_metadata:
                    # Generate a reference ID for the child
                    child_reference_id = f"child_{actual_child_id or 'default'}"
                    
                    # Get child's AI description if available
                    child_ai_description = child_info.get('ai_description')
                    if not child_ai_description:
                        # Generate basic description from child profile
                        child_ai_description = f"{actual_child_name}, age {actual_child_age}"
                        if child_interests:
                            child_ai_description += f", interests: {', '.join(child_interests[:3])}"
                    
                    # Create reference image metadata entry for the child
                    child_ref_metadata = {
                        'reference_image_id': child_reference_id,
                        'person_name': actual_child_name,
                        'relation': 'child',
                        'image_url': child_image_url,
                        'ai_description': child_ai_description
                    }
                    
                    # Add child to the beginning of reference list (most important character)
                    reference_images_metadata.insert(0, child_ref_metadata)
                    print(f"✅ Auto-added child's reference image: {actual_child_name} (ID: {child_reference_id})")
                else:
                    # Child already in metadata, find their ID
                    for ref in reference_images_metadata:
                        if (ref.get('person_name', '').lower() == actual_child_name.lower() or
                            ref.get('relation', '').lower() in ['child', 'self']):
                            child_reference_id = ref.get('reference_image_id')
                            print(f"✅ Child already in reference metadata: {actual_child_name} (ID: {child_reference_id})")
                            break
            mentioned_character_ids = self._parse_mentions_from_prompt(user_prompt, user_profile, reference_images_metadata)
            if mentioned_character_ids:
                print(f"📌 Detected @mentions in prompt: {mentioned_character_ids}")
                # Ensure mentioned character IDs are in the reference list
                existing_ids = {ref['reference_image_id'] for ref in reference_images_metadata}
                for char_id in mentioned_character_ids:
                    if char_id not in existing_ids:
                        # Character was mentioned but not in the provided list - add it if found
                        all_user_refs = user_profile.get('reference_images', [])
                        matching_ref = next((r for r in all_user_refs if r.get('reference_image_id') == char_id), None)
                        if matching_ref:
                            reference_images_metadata.append(matching_ref)
                            print(f"✅ Auto-added mentioned character: {matching_ref.get('person_name')}")
            
            # Build CHARACTER CONSISTENCY block for OpenAI prompt
            character_consistency_block = ""
            if reference_images_metadata:
                character_consistency_block = "\n\n" + "="*80 + "\n"
                character_consistency_block += "CHARACTER CONSISTENCY REQUIREMENTS - REFERENCE IMAGES PROVIDED\n"
                character_consistency_block += "="*80 + "\n\n"
                character_consistency_block += f"The user has provided {len(reference_images_metadata)} reference image(s) for character consistency.\n"
                character_consistency_block += "These characters MUST appear visually identical across all scenes where they are depicted.\n\n"
                character_consistency_block += "REFERENCE CHARACTERS:\n"
                for idx, ref in enumerate(reference_images_metadata, 1):
                    ref_id = ref.get('reference_image_id', f'ref_{idx}')
                    person_name = ref.get('person_name', 'Unknown')
                    relation = ref.get('relation', 'character')
                    ai_desc = ref.get('ai_description', 'No description available')
                    image_url = ref.get('image_url', '')
                    
                    character_consistency_block += f"\n{idx}. Reference ID: {ref_id}\n"
                    character_consistency_block += f"   Name: {person_name}\n"
                    character_consistency_block += f"   Relation: {relation}\n"
                    character_consistency_block += f"   AI-Generated Visual Description:\n"
                    character_consistency_block += f"   {ai_desc}\n"
                    character_consistency_block += f"   Image URL (for SeeDream image generation): {image_url}\n"
                
                character_consistency_block += "\n" + "="*80 + "\n"
                character_consistency_block += "CRITICAL INSTRUCTIONS FOR VISUAL PROMPTS:\n"
                character_consistency_block += "="*80 + "\n"
                character_consistency_block += "1. For EVERY scene's visual_prompt, you MUST explicitly describe COMPLETE physical appearance:\n"
                character_consistency_block += "   ⚠️ AGE: State exact age in years (e.g., '5 year old girl', '7 year old boy')\n"
                character_consistency_block += "   ⚠️ HAIR: Color, texture, style, and length (e.g., 'dark brown wavy shoulder-length hair')\n"
                character_consistency_block += "   ⚠️ SKIN TONE: Specific shade (e.g., 'warm brown skin', 'fair complexion', 'olive skin')\n"
                character_consistency_block += "   ⚠️ FACE: Eye color, nose shape, facial structure (e.g., 'bright brown eyes, button nose')\n"
                character_consistency_block += "   ⚠️ CLOTHING: Exact colors and patterns (e.g., 'red striped t-shirt, blue jeans')\n"
                character_consistency_block += "   ⚠️ BUILD: Body type for age (e.g., 'slender 5 year old build')\n"
                character_consistency_block += "   ⚠️ HEIGHT: Relative height for age (e.g., 'average height for 7 years old')\n"
                character_consistency_block += "   ⚠️ ACCESSORIES: Any glasses, jewelry, hats (keep identical across scenes)\n\n"
                character_consistency_block += "2. MANDATORY FORMAT FOR EACH CHARACTER IN VISUAL PROMPT:\n"
                character_consistency_block += "   '[Character Name], a [exact age] year old [gender] with [skin tone], [hair description],\n"
                character_consistency_block += "   [eye color] eyes, wearing [complete clothing description], [build/height]'\n\n"
                character_consistency_block += "3. **YOU MUST INCLUDE REFERENCE CHARACTERS IN THE STORY**: Use the AI-generated visual descriptions\n"
                character_consistency_block += "   above to incorporate these characters naturally into your story. For each reference character:\n"
                character_consistency_block += "   - Extract physical details from their ai_description (age, hair, skin tone, eyes, clothing)\n"
                character_consistency_block += "   - Use the EXACT SAME physical description in EVERY scene where they appear\n"
                character_consistency_block += "   - Copy key descriptors verbatim from the ai_description to ensure consistency\n"
                character_consistency_block += "   - Example: If ai_description says '5 year old girl with warm brown skin, long black wavy hair',\n"
                character_consistency_block += "     use EXACTLY 'warm brown skin, long black wavy hair' in all visual prompts\n\n"
                character_consistency_block += "4. For EACH scene, you MUST include a 'reference_image_ids' array listing ONLY the reference IDs\n"
                character_consistency_block += "   of characters that are visually depicted in that specific scene.\n"
                character_consistency_block += "   - If a character is mentioned but not visually shown, DO NOT include their ID.\n"
                character_consistency_block += "   - If no reference characters appear in a scene, use an empty array [].\n\n"
                character_consistency_block += "5. Example scene output:\n"
                character_consistency_block += "   {\n"
                character_consistency_block += f"     \"scene_number\": 1,\n"
                character_consistency_block += f"     \"text\": \"Story text in {language.upper()}...\",\n"
                character_consistency_block += f"     \"visual_prompt\": \"A 5 year old girl named {person_name} with warm brown skin, long black wavy hair, dark brown eyes, wearing a bright yellow sundress with white flowers, average height for her age, standing in a magical forest...\",\n"
                character_consistency_block += f"     \"reference_image_ids\": [\"{ref.get('reference_image_id', 'ref_xyz')}\"],\n"
                character_consistency_block += f"     \"includes_child\": true,\n"
                character_consistency_block += f"     \"emotion\": \"happy\"\n"
                character_consistency_block += "   }\n"
                character_consistency_block += f"   NOTE: The visual_prompt above uses descriptors from the AI description. Copy them EXACTLY.\n\n"
                character_consistency_block += "6. The image generation system will ONLY receive reference images for characters listed in 'reference_image_ids'.\n"
                character_consistency_block += "   This ensures visual consistency by passing the correct face references to the AI image generator.\n"
                character_consistency_block += "="*80 + "\n"
            
            # Determine script requirements for non-Latin languages
            script_instructions = ""
            language_name = language.lower()
            
            # Map languages to their native scripts
            non_latin_scripts = {
                "hindi": "Devanagari script (देवनागरी)",
                "arabic": "Arabic script (العربية)",
                "chinese": "Chinese characters (汉字/漢字)",
                "japanese": "Japanese characters (Hiragana, Katakana, Kanji)",
                "korean": "Korean Hangul (한글)",
                "thai": "Thai script (อักษรไทย)",
                "bengali": "Bengali script (বাংলা)",
                "tamil": "Tamil script (தமிழ்)",
                "telugu": "Telugu script (తెలుగు)",
                "gujarati": "Gujarati script (ગુજરાતી)",
                "punjabi": "Gurmukhi script (ਪੰਜਾਬੀ)",
                "urdu": "Urdu script (اردو)",
                "marathi": "Devanagari script (देवनागरी)",
                "russian": "Cyrillic script (Кириллица)",
                "greek": "Greek alphabet (Ελληνικά)"
            }
            
            if language_name in non_latin_scripts:
                script_instructions = f"""
{'='*80}
CRITICAL LANGUAGE REQUIREMENT - {language_name.upper()}
{'='*80}

YOU MUST GENERATE THE ENTIRE STORY IN {language_name.upper()} LANGUAGE.

MANDATORY REQUIREMENTS:
1. Story title: MUST be in {non_latin_scripts[language_name]} ONLY
2. ALL scene texts: MUST be in {non_latin_scripts[language_name]} ONLY
3. Script requirement: Use ONLY native script - ABSOLUTELY NO romanized/transliterated text
4. Visual prompts: Should remain in English for image generation compatibility

CRITICAL: This is for text-to-speech pronunciation. Using English or romanized text will cause incorrect pronunciation.

Example for Hindi:
✅ CORRECT: "नमस्ते, मेरा नाम राज है। एक बार की बात है..."
❌ WRONG: "Namaste, mera naam Raj hai. Ek baar ki baat hai..."
❌ WRONG: "Once upon a time in a colorful forest..."

IF YOU GENERATE TEXT IN ENGLISH OR ROMANIZED SCRIPT, THE AUDIO WILL BE COMPLETELY WRONG.

YOU MUST WRITE EVERY SINGLE WORD OF THE STORY IN {non_latin_scripts[language_name]}.
{'='*80}"""
            elif language_name != "english":
                script_instructions = f"""
LANGUAGE REQUIREMENT - {language_name.upper()}:
Generate the ENTIRE story in {language_name.upper()} language.
- Story title in {language_name.upper()}
- ALL scene texts in {language_name.upper()}
- Write naturally in {language_name} for proper text-to-speech pronunciation
- Visual prompts should remain in English for image generation compatibility"""
            else:
                script_instructions = ""
            
            # Build enhanced system prompt with language instructions
            # CRITICAL: Language instructions must come FIRST to override any user-specific prompts
            # that might conflict with the language requirement
            enhanced_system_prompt = system_prompt
            if script_instructions:
                # Put language instructions FIRST so they take priority
                enhanced_system_prompt = f"{script_instructions}\n\n{system_prompt}"
            
            # DEBUG: Log the enhanced system prompt to verify language instructions
            # Minimal language info
            print(f"🌍 Generating story in: {language.upper()}")
            if script_instructions:
                print(f"📝 Using native script instructions")
            else:
                print(f"ℹ️ No special script instructions")
            
            # Create user prompt with story requirements
            # Character reference injection (names, relations, ai_descriptions) and mention mapping will be appended here dynamically.
            story_generation_prompt = f"""Create a personalized story based on this request: "{user_prompt}"

{character_consistency_block}

{'='*80 if language_name != 'english' else ''}
{f'⚠️  WRITE THE ENTIRE STORY IN {language.upper()} LANGUAGE ⚠️' if language_name != 'english' else ''}
{'='*80 if language_name != 'english' else ''}

STORY PARAMETERS:
- Child: {actual_child_name} (age {actual_child_age})
- Interests: {', '.join(child_interests) if child_interests else 'General age-appropriate content'}
- Story Length: {story_length} ({target_scenes} scenes)
- **LANGUAGE: {language.upper()} - ALL TEXT MUST BE IN {language.upper()}**
- Morals: {morals_text}
- Art Style: {art_style}
- Genre: {genre}
- Age Group: {age_group}
- Core Moral: {moral_lesson}
- Target Emotion: {emotion}

CHILD INCLUSION: {"Include " + actual_child_name + " as a character where it naturally fits the story." if should_include_child else "Create characters appropriate for the story theme."}

INTERESTS GUIDANCE: {f"Incorporate {actual_child_name}'s interests ({', '.join(child_interests)}) ONLY if they naturally enhance the story. Prioritize narrative coherence over forcing interests." if child_interests else "Focus on creating an engaging narrative based on the request."}

VISUAL PROMPT REQUIREMENTS:
- **CRITICAL CONSISTENCY**: EVERY scene must maintain the EXACT SAME art style "{art_style}" and character age {actual_child_age}
- **USE REFERENCE CHARACTER AI DESCRIPTIONS**: If reference characters are provided above, you MUST:
  * Copy their physical descriptions EXACTLY from the ai_description field
  * Use the SAME descriptors verbatim in EVERY scene where they appear
  * Include them naturally in the story based on their relation and name
  * Never change or paraphrase their appearance details
- **CHARACTER APPEARANCE (MANDATORY FOR EVERY SCENE)**: You MUST describe EACH character with:
  * EXACT AGE in years (e.g., "5 year old", "7 year old") 
  * COMPLETE hair description (color, texture, style, length - e.g., "dark brown wavy shoulder-length hair")
  * SPECIFIC skin tone (e.g., "warm brown skin", "fair complexion", "olive skin tone")
  * DETAILED facial features (eye color, nose shape, face structure - e.g., "bright brown eyes, button nose, round face")
  * EXACT clothing with colors and patterns (e.g., "red striped t-shirt, blue denim jeans")
  * BUILD and HEIGHT for age (e.g., "slender 5 year old build, average height")
  * Any accessories (glasses, jewelry, hats - MUST be identical across scenes)
- **FORMAT**: "[Name], a [exact age] year old [gender] with [skin tone], [complete hair], [eye color] eyes, wearing [exact clothing], [build]"
- Art Style "{art_style}": MUST appear in EVERY visual_prompt. Explicitly mention "{art_style}" style in each scene description.
- Physical Traits: Use the SAME detailed physical description in EVERY scene where a character appears
- Clothing: State EXACT colors/patterns (e.g., "bright yellow sundress with white flowers") to maintain consistency
- Color Palette: Include specific color palette adjectives matching the art style (e.g., "warm golden light" for magical, "deep sapphire cloak" for mystical)
- Environment: Describe the environment, lighting, and mood with concrete details
- Language: Keep visual prompts in English for image generation compatibility
- Safety: All content must be child-safe and age-appropriate for {actual_child_age} year olds

EMOTION DETECTION FOR NARRATION:
- CRITICAL: For EACH scene, detect the primary emotion that should be conveyed during narration
- Analyze the scene's mood, characters' feelings, and narrative tone
- Choose ONE emotion from: "neutral", "happy", "excited", "sad", "curious", "surprised", "calm", "mysterious", "playful", "gentle"
- This emotion will be used to modulate the voice during text-to-speech narration
- Example: A scene about discovering treasure → "excited", A bedtime ending → "calm", A sad goodbye → "sad"

RESPONSE FORMAT (valid JSON):
{{
    "title": "Story Title - MUST BE IN {language.upper()} LANGUAGE{' USING ' + non_latin_scripts.get(language_name, '') if language_name in non_latin_scripts else ''}",
    "genre": "{genre}",
    "story_length": "{story_length}",
    "morals": "{morals_text}",
    "art_style": "{art_style}",
    "child_name": "{actual_child_name}",
    "child_age": {actual_child_age},
    "target_scenes": {target_scenes},
    "age_group": "{age_group}",
    "moral_lesson": "{moral_lesson}",
    "target_emotion": "{emotion}",
    "thumbnail_prompt": "16:9 landscape thumbnail. Style: {art_style}. Colorful, engaging cover for {actual_child_age} year olds. Show main character: [exact age] year old with [complete physical description including skin tone, hair, eyes, clothing]. Include story theme. (English)",
    "ambient_sound": "forest birds (ONE ambient sound term for the ENTIRE story - should be subtle and non-distracting)",
    "scenes": [
        {{
            "scene_number": 1,
            "text": "Scene text - MUST BE IN {language.upper()} LANGUAGE{' USING ' + non_latin_scripts.get(language_name, '') if language_name in non_latin_scripts else ''} (child-safe, promoting {morals_text})",
            "visual_prompt": "Detailed visual description in English. CRITICAL: Use {art_style} art style. MANDATORY CHARACTER FORMAT: '[Name], a [exact age] year old [gender] with [specific skin tone], [complete hair color/texture/style/length], [eye color] eyes, wearing [exact clothing colors/patterns], [build/height for age]'. Include environment, lighting, mood. Child-safe.",
            "includes_child": true,
            "emotion": "neutral (REQUIRED: Choose emotion for narration from: neutral, happy, excited, sad, curious, surprised, calm, mysterious, playful, gentle)",
            "reference_image_ids": [] (REQUIRED: Array of reference_image_ids for characters VISUALLY DEPICTED in this scene. Empty array if no reference characters appear.{' Example: ["' + reference_images_metadata[0].get('reference_image_id', 'ref_abc123') + '"] if first reference character is shown' if reference_images_metadata else ' Leave empty [] if no reference images provided'})
        }}
    ]
}}"""
            
            # DEBUG: Log the actual prompts being sent to OpenAI
            print(f"\n{'='*80}")
            print(f"🤖 OPENAI API CALL - STORY GENERATION")
            print(f"{'='*80}")
            print(f"📋 System Prompt (first 500 chars):")
            print(f"{enhanced_system_prompt[:500]}...")
            print(f"\n📋 User Prompt (first 800 chars):")
            print(f"{story_generation_prompt[:800]}...")
            print(f"{'='*80}\n")
            print(f"🤖 Calling OpenAI to generate story...")
            
            # Generate story using OpenAI
            response = self.openai_client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": enhanced_system_prompt},
                    {"role": "user", "content": story_generation_prompt}
                ],
                temperature=0.7,
                max_tokens=2000
            )
            
            # Parse the response
            story_content = response.choices[0].message.content
            
            # Log the OpenAI response
            print(f"\n{'='*80}")
            print(f"📥 OPENAI RESPONSE")
            print(f"{'='*80}")
            print(f"Response length: {len(story_content)} chars")
            print(f"First 1000 chars of response:")
            print(f"{story_content[:1000]}...")
            print(f"{'='*80}\n")
            
            try:
                story_data = json.loads(story_content)
            except json.JSONDecodeError:
                # Try to extract JSON from the response if it's wrapped in markdown
                if "```json" in story_content:
                    json_start = story_content.find("```json") + 7
                    json_end = story_content.find("```", json_start)
                    story_content = story_content[json_start:json_end].strip()
                    story_data = json.loads(story_content)
                else:
                    raise HTTPException(status_code=500, detail="Failed to parse story response as JSON")
            
            # Extract the single ambient sound for the entire story
            story_ambient_sound = story_data.get("ambient_sound", "").strip()
            if story_ambient_sound:
                print(f"🎵 Ambient sound: '{story_ambient_sound}'")
            
            # Convert to StoryScene objects
            scenes = []

            # Fallback reference mapping for per-scene IDs (infer if missing)
            provided_reference_ids = []
            if 'scenes' in story_data:
                # Collect all declared IDs for validation statistics
                for s in story_data['scenes']:
                    if isinstance(s, dict) and 'reference_image_ids' in s:
                        provided_reference_ids.extend(s['reference_image_ids'] or [])
            
            for scene_data in story_data["scenes"]:
                # Apply the same ambient sound to ALL scenes
                # Extract emotion for narration (default to "neutral" if not provided)
                scene_emotion = scene_data.get("emotion", "neutral").lower().strip()
                per_scene_refs = scene_data.get("reference_image_ids") or []
                
                # Log the visual prompt for this scene
                print(f"\n{'='*80}")
                print(f"📝 SCENE {scene_data['scene_number']} VISUAL PROMPT (from OpenAI)")
                print(f"{'='*80}")
                print(f"{scene_data['visual_prompt']}")
                print(f"{'='*80}\n")
                
                scene = StoryScene(
                    scene_number=scene_data["scene_number"],
                    text=scene_data["text"],
                    visual_prompt=scene_data["visual_prompt"],
                    includes_child=scene_data.get("includes_child", False),
                    ambient_sound_keywords=story_ambient_sound,  # Same for all scenes
                    emotion=scene_emotion,  # Emotion for TTS narration
                    reference_image_ids=per_scene_refs
                )
                scenes.append(scene)
            
            title = story_data.get("title", f"A Story for {child_name}")
            thumbnail_prompt = story_data.get("thumbnail_prompt", "")
            
            print(f"📚 Story generated: {len(scenes)} scenes")
            
            return scenes, title, thumbnail_prompt
            
        except HTTPException:
            raise
        except Exception as e:
            import traceback
            print(f"❌ Story generation error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Story generation failed: {str(e)}")
    
    def generate_story_id(self) -> str:
        """Generate unique story ID"""
        return f"story_{uuid.uuid4().hex[:8]}"
    
    def _parse_mentions_from_prompt(self, user_prompt: str, user_profile: Dict[str, Any], 
                                    existing_refs: List[Dict[str, Any]]) -> List[str]:
        """
        Parse @mentions from user prompt and return list of reference_image_ids.
        Matches @name or @relation (e.g., @sukhman, @dad, @mom).
        """
        if not user_prompt:
            return []
        
        # Extract all @mentions using regex (alphanumeric + underscore after @)
        mentions = re.findall(r'@(\w+)', user_prompt)
        if not mentions:
            return []
        
        print(f"🔍 Found @mentions in prompt: {mentions}")
        
        # Get all available reference images from user profile
        all_refs = user_profile.get('reference_images', [])
        if not all_refs:
            print(f"⚠️ No reference images available in user profile")
            return []
        
        matched_ids = []
        for mention in mentions:
            mention_lower = mention.lower()
            # Try to match by person_name or relation
            for ref in all_refs:
                person_name = ref.get('person_name', '').lower()
                relation = ref.get('relation', '').lower()
                ref_id = ref.get('reference_image_id')
                
                if ref_id and (person_name == mention_lower or relation == mention_lower):
                    if ref_id not in matched_ids:
                        matched_ids.append(ref_id)
                        print(f"✅ Matched @{mention} → {ref.get('person_name')} ({ref.get('relation')})")
                        break
            else:
                print(f"⚠️ Could not match @{mention} to any reference image")
        
        return matched_ids