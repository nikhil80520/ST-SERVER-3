# Reference Image IDs - Always Send Empty Array

## Problem
Previously, when a user had no reference images or when scenes didn't use any reference images, the `reference_image_ids` field could be:
- Omitted entirely from the response
- Set to `null`
- Inconsistently handled

This caused issues for client applications that expected the field to always exist as an array.

## Solution
Ensured that `reference_image_ids` is **always present as an array**, even when empty (`[]`).

## Changes Made

### 1. **app/models/story.py** - StoryScene dataclass
**Before:**
```python
@dataclass
class StoryScene:
    # ... other fields ...
    reference_image_ids: Optional[List[str]] = None
```

**After:**
```python
@dataclass
class StoryScene:
    # ... other fields ...
    reference_image_ids: List[str] = None
    
    def __post_init__(self):
        # Ensure reference_image_ids is always a list, never None
        if self.reference_image_ids is None:
            self.reference_image_ids = []
```

**Impact:** Every `StoryScene` instance now guarantees `reference_image_ids` is a list (empty if no IDs).

### 2. **app/services/parallel_story_service.py** - Scene serialization
**Before:**
```python
scene_data = {
    "scene_number": scene.scene_number,
    "text": scene.text,
    "visual_prompt": scene.visual_prompt,
    "audio_url": getattr(scene, 'audio_url', None),
    "image_url": getattr(scene, 'image_url', None),
    "start_time": getattr(scene, 'start_time', 0),
    "duration": duration,
    "includes_child": scene.includes_child
    # reference_image_ids was MISSING!
    # ambient_sound_keywords was MISSING!
    # emotion was MISSING!
}
```

**After:**
```python
scene_data = {
    "scene_number": scene.scene_number,
    "text": scene.text,
    "visual_prompt": scene.visual_prompt,
    "audio_url": getattr(scene, 'audio_url', None),
    "image_url": getattr(scene, 'image_url', None),
    "start_time": getattr(scene, 'start_time', 0),
    "duration": duration,
    "includes_child": scene.includes_child,
    "ambient_sound_keywords": scene.ambient_sound_keywords,
    "emotion": scene.emotion,
    "reference_image_ids": scene.reference_image_ids  # Always a list (empty [] if no IDs)
}
```

**Impact:** All scenes stored in Firestore now include all fields consistently, including `reference_image_ids` as an empty array when there are no reference images.

## Expected Behavior

### Scenario 1: User has no reference images
```json
{
  "scene_number": 1,
  "text": "...",
  "reference_image_ids": []  // ✅ Empty array, not null or missing
}
```

### Scenario 2: User has reference images but scene doesn't use them
```json
{
  "scene_number": 2,
  "text": "...",
  "reference_image_ids": []  // ✅ Empty array
}
```

### Scenario 3: Scene uses reference images
```json
{
  "scene_number": 3,
  "text": "...",
  "reference_image_ids": ["child_default", "ref_dad_123"]  // ✅ Array with IDs
}
```

## Client Benefits

1. **No null checks needed**: Clients can always iterate over `reference_image_ids` without checking if it exists or is null
2. **Consistent API contract**: Field is always present in the same format
3. **Simpler code**: `scene.reference_image_ids.length` always works
4. **Type safety**: TypeScript/Swift clients can use non-nullable array types

## Testing

Verified in server logs after change:
```
🖼️ Reference image usage summary (scene -> ids): [{1: []}, {2: []}, {3: []}, {4: []}, {5: []}]
```

All scenes now correctly show `[]` instead of missing or null values.

## Related Files
- `app/models/story.py` - StoryScene dataclass definition
- `app/services/parallel_story_service.py` - Scene data serialization
- `app/services/story_service.py` - Story generation and OpenAI response parsing

## Date
2025-11-11
