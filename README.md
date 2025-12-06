# ESP32 Storytelling Server

> **AI-powered personalized storytelling platform with voice synthesis, conversational AI, and IoT device support**

## 📚 Documentation

All comprehensive documentation has been organized in the **[docs/](./docs/)** directory.

### Quick Start

- **New to the project?** → Start with [docs/DEVELOPER_GUIDE.md](./docs/DEVELOPER_GUIDE.md)
- **Building a frontend?** → Check [docs/FRONTEND_API_GUIDE.md](./docs/FRONTEND_API_GUIDE.md)
- **High-level overview?** → Read [docs/PROJECT_OVERVIEW.md](./docs/PROJECT_OVERVIEW.md)
- **Technical deep-dive?** → Explore [docs/IMPLEMENTATION_DETAILS.md](./docs/IMPLEMENTATION_DETAILS.md)

### Documentation Hub

**➡️ [docs/README.md](./docs/README.md)** - Complete documentation index with quick navigation

## 🚀 Quick Setup

```bash
# 1. Clone repository
git clone <repository-url>
cd STServer

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 5. Run server
uvicorn app.main:app --reload

# 6. Access API docs
open http://localhost:8000/docs
```

**Detailed setup instructions**: [docs/DEVELOPER_GUIDE.md#setup](./docs/DEVELOPER_GUIDE.md#setup)

## 🎯 Key Features

- 🎨 **AI Story Generation** - GPT-4 powered personalized children's stories
- 🎵 **Voice Synthesis** - Natural voice narration with cloning support
- 🌿 **Ambient Audio Mixing & Caching** - Optional subtle ambient backgrounds with disk persistence & reuse
- 🖼️ **Image Generation** - Scene-specific AI artwork
- 🤖 **Conversational AI** - Real-time voice conversations via WebRTC
- 📱 **Mobile Support** - iOS/Android apps with offline sync
- 🔌 **IoT Integration** - ESP32 device support for dedicated hardware

**Learn more**: [docs/PROJECT_OVERVIEW.md#core-features](./docs/PROJECT_OVERVIEW.md#core-features)

## 🏗️ Architecture

```
Mobile App / Web ←→ FastAPI Server ←→ AI Services (OpenAI, Cartesia, SeeDream)
                           ↓
                   Firebase (Firestore + Storage + Auth)
                           ↓
                    IoT Devices (ESP32)
```

**Detailed architecture**: [docs/PROJECT_OVERVIEW.md#system-architecture](./docs/PROJECT_OVERVIEW.md#system-architecture)

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python 3.11+), AsyncIO
- **Database**: Firebase Firestore
- **Storage**: Firebase Storage
- **Authentication**: Firebase Auth (JWT)
- **AI Services**: OpenAI GPT-4, Cartesia Sonic, SeeDream, Deepgram
- **Real-Time**: WebSocket, WebRTC (Pipecat framework)

**Full stack details**: [docs/DEVELOPER_GUIDE.md#key-technologies](./docs/DEVELOPER_GUIDE.md#key-technologies)

### 🔊 Ambient Audio & Performance Flags

You can tune ambient audio behavior via `app/config.py`:

| Setting | Purpose |
|---------|---------|
| `enable_ambient_persistence` | Persist downloaded ambient sounds to disk for cross-story reuse |
| `ambient_cache_dir` | Directory for storing cached ambient audio previews |
| `ambient_cache_max_entries` | Max number of ambient cache files retained on disk |
| `reuse_single_ambient_bed` | Reuse the first ambient sound across all scenes of a story |
| `enable_audio_enhancement` | Toggle post‑processing (reverb + compression + normalization) |
| `background_workers` | Number of async background workers for story generation |

To quickly disable enhancement for performance testing:
```python
settings.enable_audio_enhancement = False
```

To enable disk persistence (make sure directory exists or let service create it):
```python
settings.enable_ambient_persistence = True
settings.reuse_single_ambient_bed = True  # Optional speed-up
```

Responsiveness probe script:
```bash
export FIREBASE_TOKEN="<token>"
python scripts/responsiveness_probe.py --host http://localhost:8000 --duration 45
```
Outputs latency stats for `/health` and `/stories/{id}` while generation runs.

## 📖 API Documentation

### Interactive Docs
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### API Guide
Complete REST API reference with examples: [docs/FRONTEND_API_GUIDE.md](./docs/FRONTEND_API_GUIDE.md)

**Sample Request**:
```bash
# Generate a story
curl -X POST "http://localhost:8000/stories/generate" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_prompt": "A magical adventure in space",
    "child_name": "Emma",
    "child_age": 7,
    "story_length": "medium"
  }'
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_stories.py
```

**Testing guide**: [docs/DEVELOPER_GUIDE.md#testing](./docs/DEVELOPER_GUIDE.md#testing)

## 🚢 Deployment

### Option 1: Google Cloud Run (Recommended)
```bash
gcloud run deploy storytelling-server \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

### Option 2: Docker
```bash
docker build -t storytelling-server .
docker run -p 8000:8000 storytelling-server
```

**Deployment guide**: [docs/DEVELOPER_GUIDE.md#deployment](./docs/DEVELOPER_GUIDE.md#deployment)

## 📁 Project Structure

```
STServer/
├── app/
│   ├── routers/          # API endpoints
│   ├── services/         # Business logic
│   ├── models/           # Data models
│   └── utils/            # Utilities
├── tests/                # Test files
├── docs/                 # 📚 Comprehensive documentation
└── requirements.txt      # Python dependencies
```

**Detailed structure**: [docs/DEVELOPER_GUIDE.md#project-structure](./docs/DEVELOPER_GUIDE.md#project-structure)

## 🤝 Contributing

1. Read [docs/DEVELOPER_GUIDE.md](./docs/DEVELOPER_GUIDE.md)
2. Create feature branch: `git checkout -b feature/your-feature`
3. Make changes and test thoroughly
4. Update relevant documentation in `docs/`
5. Submit pull request

## 📞 Support

- **Documentation Issues**: File GitHub issue with `documentation` label
- **Technical Support**: Post in #engineering channel
- **Feature Requests**: Create GitHub issue with `enhancement` label

## 📄 License

Copyright (c) 2025 Sukhman Singh Narula and Neil Arora
All rights reserved.

This software and its source code (the "Software") are the exclusive property of Sukhman Singh Narula and Neil Arora.

Permission is NOT granted to use, copy, modify, merge, publish, distribute, sublicense, or sell copies of the Software, in whole or in part, without the express prior written consent of the author.

No organization, entity, or individual is authorized to use or distribute this Software unless explicit written permission has been provided by the copyright holder.

Unauthorized use, reproduction, or distribution of this Software is strictly prohibited and may result in civil and/or criminal liability.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Author: Sukhman Singh Narula and Neil Arora
Contact: sukhmannarula84@gmail.com and neilarora2008@gmail.com
##
**For complete documentation, visit [docs/README.md](./docs/README.md)**
