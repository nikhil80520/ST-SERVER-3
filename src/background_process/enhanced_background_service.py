"""
Enhanced Background Task Service for Asynchronous Story Generation with WebSocket Notifications
Includes robust queue management, worker failover, and graceful error handling
"""
import asyncio
import uuid
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from enum import Enum

class JobStatus(Enum):
    """Job status enumeration"""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RETRYING = "retrying"
    ABANDONED = "abandoned"

@dataclass
class StoryJob:
    """Story generation background job"""
    job_id: str
    story_id: str
    user_id: Optional[str]
    parameters: Dict[str, Any]
    services: Dict[str, Any]
    callbacks: Dict[str, Callable] = field(default_factory=dict)
    # Lifecycle / tracking
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    # Status & retry
    status: str = JobStatus.QUEUED.value
    retry_count: int = 0
    max_retries: int = 2
    timeout_seconds: int = 1200  # default 20 min safety upper bound
    # Result / error
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    # Worker assignment
    worker_id: Optional[str] = None
    
class EnhancedBackgroundTaskService:
    """Enhanced background task service with robust queue management and worker failover"""
    
    def __init__(self, max_workers: int = 5):
        self.max_workers = max_workers
        self.running = False
        self.workers: List[asyncio.Task] = []
        self.monitoring_task: Optional[asyncio.Task] = None
        # Heartbeat removed: stall detection disabled
        self.heartbeat_interval = None
        self.job_timeout_check_interval = 60  # Check for timeouts every 60 seconds
        # Queues and tracking registries
        self.job_queue: Optional["asyncio.PriorityQueue[tuple]"] = None  # Created in start()
        self.active_jobs: Dict[str, StoryJob] = {}
        self.jobs: Dict[str, StoryJob] = {}
        
    async def start(self, num_workers: int = None):
        """Start workers and monitoring loop"""
        if self.running:
            return
        self.running = True
        
        # Create job queue with event loop
        if self.job_queue is None:
            self.job_queue = asyncio.PriorityQueue()
        
        worker_count = num_workers or self.max_workers
        print(f"🚀 Starting enhanced background task service with {worker_count} workers")
        print(f"⚙️  Features: Worker failover, timeout monitoring, auto-retry, graceful degradation")
        # Spawn workers
        for i in range(worker_count):
            task = asyncio.create_task(self._worker(f"worker-{i+1}"))
            self.workers.append(task)
        # Start monitor
        self.monitoring_task = asyncio.create_task(self._monitor_jobs())
        print(f"✅ Background task service started with {len(self.workers)} workers + monitoring")
    
    async def stop(self):
        """Stop the background task service gracefully"""
        if not self.running:
            return
        print("🛑 Stopping background task service...")
        self.running = False
        # Stop monitor
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        # Cancel workers
        for w in self.workers:
            w.cancel()
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)
        # Re-queue any running jobs
        for job_id, job in list(self.active_jobs.items()):
            if job.status == JobStatus.RUNNING.value:
                print(f"⚠️  Re-queuing interrupted job {job_id}")
                job.status = JobStatus.QUEUED.value
                job.worker_id = None
                # Reinsert with neutral priority (0) and timestamp
                await self.job_queue.put((0, time.time(), job))
        self.workers.clear()
        self.active_jobs.clear()
        print("✅ Background task service stopped gracefully")
    
    async def submit_story_job(
        self,
        story_id: str,
        parameters: Dict[str, Any],
        services: Dict[str, Any],
        callbacks: Dict[str, Callable] = None,
        priority: int = 0
    ) -> str:
        """Submit a new story generation job with callback support and priority"""
        
        # CRITICAL FIX: Check if this story is already being processed
        for existing_job_id, existing_job in self.jobs.items():
            if existing_job.story_id == story_id and existing_job.status in [JobStatus.QUEUED.value, JobStatus.RUNNING.value]:
                print(f"⚠️  Story {story_id} is already being processed by job {existing_job_id} (status: {existing_job.status})")
                print(f"   Skipping duplicate submission to prevent multiple workers generating the same story")
                return existing_job_id
        
        job_id = str(uuid.uuid4())
        
        job = StoryJob(
            job_id=job_id,
            story_id=story_id,
            user_id=parameters.get("user_id"),
            parameters=parameters,
            services=services,
            callbacks=callbacks or {},
            timeout_seconds=parameters.get("timeout_seconds", 1200)
        )
        
        self.jobs[job_id] = job
        await self.job_queue.put((priority, time.time(), job))  # Priority queue with timestamp for FIFO within priority
        
        print(f"📝 Queued story job {job_id} for story {story_id} (priority: {priority})")
        print(f"📊 Queue size: {self.job_queue.qsize()}, Active jobs: {len(self.active_jobs)}")
        
        return job_id
    
    async def _monitor_jobs(self):
        """Monitor jobs for timeouts (no heartbeat/stall detection)"""
        print(f"🔍 Job monitoring started (timeout check interval: {self.job_timeout_check_interval}s)")
        
        try:
            while self.running:
                await asyncio.sleep(self.job_timeout_check_interval)
                
                now = datetime.utcnow()
                timed_out_jobs = []
                
                # Check for timed out jobs (heartbeat removed)
                for job_id, job in list(self.active_jobs.items()):
                    if job.status != JobStatus.RUNNING.value:
                        continue
                    # Only total elapsed timeout logic retained
                    if job.started_at:
                        elapsed = (now - job.started_at).total_seconds()
                        if elapsed > job.timeout_seconds:
                            print(f"⏱️  Job {job_id} timed out after {elapsed:.0f}s (limit: {job.timeout_seconds}s)")
                            timed_out_jobs.append(job)
                
                # Handle timed out jobs
                for job in timed_out_jobs:
                    await self._handle_timeout_job(job)
                
                # Log monitoring stats
                if self.active_jobs or self.job_queue.qsize() > 0:
                    print(f"📊 Monitor: {len(self.active_jobs)} active, {self.job_queue.qsize()} queued, {len(self.jobs)} total")
                    
        except asyncio.CancelledError:
            print("🔍 Job monitoring stopped")
        except Exception as e:
            print(f"❌ Job monitoring error: {e}")
    
    async def _handle_timeout_job(self, job: StoryJob):
        """Handle a job that has timed out"""
        try:
            job.status = JobStatus.TIMEOUT.value
            
            # Remove from active jobs
            if job.job_id in self.active_jobs:
                del self.active_jobs[job.job_id]
            
            # Retry if not exceeded max retries
            if job.retry_count < job.max_retries:
                job.retry_count += 1
                job.status = JobStatus.RETRYING.value
                job.started_at = None
                job.worker_id = None
                
                print(f"🔄 Retrying timed out job {job.job_id} (attempt {job.retry_count + 1}/{job.max_retries + 1})")
                
                # Re-queue with lower priority
                await self.job_queue.put((10, time.time(), job))
                
                # Notify via callback
                if job.callbacks.get("on_progress"):
                    try:
                        await job.callbacks["on_progress"]({
                            "status": "retrying",
                            "progress": 0,
                            "message": f"Job timed out. Retrying... (attempt {job.retry_count + 1}/{job.max_retries + 1})"
                        })
                    except Exception as e:
                        print(f"❌ Callback error during retry notification: {e}")
            else:
                # Max retries exceeded - mark as failed
                job.status = JobStatus.FAILED.value
                job.completed_at = datetime.utcnow()
                job.error_message = f"Job timed out after {job.retry_count + 1} attempts"
                
                print(f"❌ Job {job.job_id} abandoned after {job.retry_count + 1} timeout attempts")
                
                # Update story status in storage
                try:
                    storage_service = job.services.get("storage_service")
                    if storage_service:
                        await storage_service.update_story_status(
                            job.story_id,
                            "failed",
                            error_message="Story generation timed out after multiple attempts"
                        )
                except Exception as e:
                    print(f"❌ Failed to update story status: {e}")
                
                # Notify via callback
                if job.callbacks.get("on_completion"):
                    try:
                        await job.callbacks["on_completion"]({
                            "status": "failed",
                            "error": job.error_message,
                            "story_id": job.story_id
                        })
                    except Exception as e:
                        print(f"❌ Callback error during failure notification: {e}")
                        
        except Exception as e:
            print(f"❌ Error handling timeout for job {job.job_id}: {e}")
    
    async def _worker(self, worker_name: str):
        """Background worker that processes jobs from the queue with error handling"""
        print(f"👷 {worker_name} started")
        
        try:
            while self.running:
                job = None
                try:
                    # Get job from priority queue with timeout
                    priority, timestamp, job = await asyncio.wait_for(
                        self.job_queue.get(), 
                        timeout=1.0
                    )
                    
                    # Track active job
                    job.worker_id = worker_name
                    self.active_jobs[job.job_id] = job
                    
                    print(f"🔄 {worker_name} processing job {job.job_id} (retry: {job.retry_count})")
                    await self._process_job(job, worker_name)
                    
                except asyncio.TimeoutError:
                    continue  # No job available, continue loop
                except asyncio.CancelledError:
                    # Worker is being cancelled - re-queue current job if running
                    if job and job.status == JobStatus.RUNNING.value:
                        print(f"⚠️  {worker_name} cancelled while processing {job.job_id}, re-queuing...")
                        job.status = JobStatus.QUEUED.value
                        job.worker_id = None
                        await self.job_queue.put((0, time.time(), job))
                    raise
                except Exception as e:
                    print(f"❌ {worker_name} unexpected error: {e}")
                    if job:
                        # Remove from active jobs
                        if job.job_id in self.active_jobs:
                            del self.active_jobs[job.job_id]
                        
                        # Try to recover by re-queuing
                        if job.retry_count < job.max_retries:
                            job.retry_count += 1
                            job.status = JobStatus.RETRYING.value
                            await self.job_queue.put((10, time.time(), job))
                            print(f"🔄 Re-queued job {job.job_id} after worker error")
                    await asyncio.sleep(1)  # Prevent tight loop on repeated errors
                    
        except asyncio.CancelledError:
            print(f"👷 {worker_name} cancelled")
        except Exception as e:
            print(f"❌ {worker_name} fatal error: {e}")
        finally:
            print(f"👷 {worker_name} stopped")
    
    async def _process_job(self, job: StoryJob, worker_name: str):
        """Process a single story generation job with robust error handling"""
        try:
            # Update job status to running
            job.status = JobStatus.RUNNING.value
            job.started_at = datetime.utcnow()
            
            print(f"🎬 {worker_name} executing story generation for {job.story_id}")
            
            # Call progress callback if available
            if job.callbacks.get("on_progress"):
                try:
                    await job.callbacks["on_progress"]({
                        "status": "starting",
                        "progress": 5,
                        "message": "Starting story generation...",
                        "attempt": job.retry_count + 1
                    })
                except Exception as e:
                    print(f"⚠️  Progress callback error: {e}")
            
            # Execute the actual story generation with timeout
            result = await asyncio.wait_for(
                self._execute_story_job(job),
                timeout=job.timeout_seconds
            )
            
            # Mark job as completed
            job.status = JobStatus.COMPLETED.value
            job.completed_at = datetime.utcnow()
            job.result = result
            
            # Remove from active jobs
            if job.job_id in self.active_jobs:
                del self.active_jobs[job.job_id]
            
            duration = (job.completed_at - job.started_at).total_seconds()
            print(f"✅ {worker_name} completed story {job.story_id} in {duration:.1f}s")
            print(f"🔔 Calling on_completion callback for story {job.story_id}...")
            
            # Call completion callback if available
            if job.callbacks.get("on_completion"):
                try:
                    await job.callbacks["on_completion"](result)
                    print(f"✅ on_completion callback executed successfully for story {job.story_id}")
                except Exception as callback_error:
                    print(f"❌ on_completion callback failed for story {job.story_id}: {callback_error}")
            else:
                print(f"⚠️ No on_completion callback found for story {job.story_id}")
            
        except asyncio.TimeoutError:
            # Job execution timed out
            print(f"⏱️  {worker_name} job {job.job_id} execution timed out")
            
            # Remove from active jobs - will be handled by monitor
            if job.job_id in self.active_jobs:
                del self.active_jobs[job.job_id]
            
            # Retry logic
            if job.retry_count < job.max_retries:
                job.retry_count += 1
                job.status = JobStatus.RETRYING.value
                job.started_at = None
                job.worker_id = None
                
                print(f"🔄 Re-queuing timed out job {job.job_id} (attempt {job.retry_count + 1}/{job.max_retries + 1})")
                await self.job_queue.put((10, time.time(), job))
                
                if job.callbacks.get("on_progress"):
                    try:
                        await job.callbacks["on_progress"]({
                            "status": "retrying",
                            "progress": 0,
                            "message": f"Story generation timed out. Retrying... (attempt {job.retry_count + 1})"
                        })
                    except Exception as e:
                        print(f"⚠️  Retry callback error: {e}")
            else:
                # Max retries exceeded
                await self._handle_job_failure(
                    job, 
                    f"Story generation timed out after {job.retry_count + 1} attempts",
                    worker_name
                )
                
        except Exception as e:
            # Job execution failed with exception
            print(f"❌ {worker_name} failed story {job.story_id}: {e}")
            
            # Remove from active jobs
            if job.job_id in self.active_jobs:
                del self.active_jobs[job.job_id]
            
            # Retry logic for transient errors
            if job.retry_count < job.max_retries and self._is_retryable_error(e):
                job.retry_count += 1
                job.status = JobStatus.RETRYING.value
                job.started_at = None
                job.worker_id = None
                
                print(f"🔄 Re-queuing failed job {job.job_id} due to retryable error (attempt {job.retry_count + 1})")
                await self.job_queue.put((10, time.time(), job))
                
                if job.callbacks.get("on_progress"):
                    try:
                        await job.callbacks["on_progress"]({
                            "status": "retrying",
                            "progress": 0,
                            "message": f"Error occurred. Retrying... (attempt {job.retry_count + 1})"
                        })
                    except Exception as cb_e:
                        print(f"⚠️  Retry callback error: {cb_e}")
            else:
                # Non-retryable error or max retries exceeded
                await self._handle_job_failure(job, str(e), worker_name)
    
    def _is_retryable_error(self, error: Exception) -> bool:
        """Determine if an error is retryable"""
        retryable_errors = [
            "timeout",
            "connection",
            "network",
            "rate limit",
            "503",
            "502",
            "504",
            "temporary",
            "unavailable"
        ]
        error_str = str(error).lower()
        return any(keyword in error_str for keyword in retryable_errors)
    
    async def _handle_job_failure(self, job: StoryJob, error_message: str, worker_name: str):
        """Handle permanent job failure"""
        job.status = JobStatus.FAILED.value
        job.completed_at = datetime.utcnow()
        job.error_message = error_message
        
        print(f"❌ {worker_name} permanently failed job {job.job_id}: {error_message}")
        
        # Update story status in storage
        try:
            storage_service = job.services.get("storage_service")
            if storage_service:
                await storage_service.update_story_status(
                    job.story_id,
                    "failed",
                    error_message=error_message[:500]  # Truncate long error messages
                )
        except Exception as e:
            print(f"❌ Failed to update story status: {e}")
        
        # Call completion callback with error
        if job.callbacks.get("on_completion"):
            try:
                await job.callbacks["on_completion"]({
                    "status": "failed",
                    "error": error_message,
                    "story_id": job.story_id,
                    "attempts": job.retry_count + 1
                })
            except Exception as e:
                print(f"❌ Failure callback error: {e}")
    
    async def _execute_story_job(self, job: StoryJob) -> Dict[str, Any]:
        """Execute a story generation job using the parallel story service"""
        try:
            print(f"🎬 Executing story generation job: {job.story_id}")
            print(f"🎵 Ambient keywords will be generated dynamically by LLM per scene")

            # Emit initial progress update (no extra debug noise)
            if job.callbacks.get("on_progress"):
                await job.callbacks["on_progress"]({
                    "status": "processing",
                    "progress": 10,
                    "message": "Starting story generation..."
                })

            # Get services from job
            story_service = job.services.get("story_service")
            media_service = job.services.get("media_service") 
            storage_service = job.services.get("storage_service")

            print(
                f"🧩 Services: story={bool(story_service)}, media={bool(media_service)}, storage={bool(storage_service)}"
            )
            
            if not all([story_service, media_service, storage_service]):
                raise Exception("Missing required services")
            
            # Create parallel story service
            from src.background_process.parallel_story_service import ParallelStoryService
            parallel_service = ParallelStoryService(story_service, media_service, storage_service)
            
            # Extract generation parameters
            params = job.parameters
            print(
                f"🧾 Params: scenes={params.get('target_scenes', 7)}, lang={params.get('language', 'english')}, refs={len(params.get('reference_image_urls', []) or [])}"
            )

            # Emit progress update
            if job.callbacks.get("on_progress"):
                await job.callbacks["on_progress"]({
                    "status": "processing", 
                    "progress": 20,
                    "message": "Generating story structure..."
                })
            
            # Generate story using parallel processing with overall timeout (safety)
            # 15 minutes max to prevent infinite hangs
            try:
                # CRITICAL FIX: Yield control to event loop before heavy operation
                await asyncio.sleep(0)
                
                manifest = await parallel_service.generate_story_parallel(
                        story_id=job.story_id,
                        user_prompt=params.get("user_prompt"),
                        user_id=params.get("user_id"),
                        target_scenes=params.get("target_scenes", 7),
                        child_id=params.get("child_id"),
                        child_name=params.get("child_name"),
                        child_age=params.get("child_age"),
                        morals=params.get("morals", ["kindness", "friendship"]),
                        story_length=params.get("story_length", "medium"),
                        art_style=params.get("art_style", "magical"),
                        voice_option=params.get("voice_option", "female"),
                        dimensions=params.get("dimensions", "1024x1024"),
                        use_cloned_voice=params.get("use_cloned_voice", True),
                        voice_clone_id=params.get("voice_clone_id"),
                        language=params.get("language", "english"),
                        reference_image_urls=params.get("reference_image_urls", []),
                        reference_images_metadata=params.get("reference_images_metadata", []),  # FIXED: Pass metadata to OpenAI
                        # NOTE: ambient_keywords are generated dynamically by LLM per scene
                        # Legacy parameters
                        genre=params.get("genre", ["Adventure"]),
                        age_group=params.get("age_group", "6-8"),
                        moral_lesson=params.get("moral_lesson", "friendship"),
                        emotion=params.get("emotion", "happiness")
                )
                print(f"✅ Story parallel generation finished for {job.story_id}")
            except asyncio.TimeoutError:
                print(f"⏱️ Story generation timed out after 15 minutes for {job.story_id}")
                # Update story status to failed
                await storage_service.update_story_status(
                    job.story_id, 
                    "failed", 
                    error_message="Story generation timed out after 15 minutes"
                )
                raise Exception("Story generation timed out after 15 minutes")

            
            # Emit progress update during generation
            if job.callbacks.get("on_progress"):
                await job.callbacks["on_progress"]({
                    "status": "processing",
                    "progress": 90,
                    "message": "Finalizing story and saving..."
                })
            
            result = {
                "story_id": job.story_id,
                "title": manifest.get("title", "Generated Story"),
                "status": "completed",
                "manifest": manifest
            }
            
            print(f"✅ Story generation completed: {job.story_id}")
            print(f"📊 Performance metrics: {manifest.get('performance_metrics', {})}")
            return result
            
        except Exception as e:
            print(f"❌ Story generation failed: {job.story_id} - {str(e)}")
            raise e
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the current status of a job"""
        job = self.jobs.get(job_id)
        if not job:
            return None
            
        return {
            'job_id': job.job_id,
            'story_id': job.story_id,
            'user_id': job.user_id,
            'status': job.status,
            'created_at': job.created_at.isoformat(),
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'error_message': job.error_message,
            'has_result': job.result is not None
        }
    
    def get_job_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the result of a completed job"""
        job = self.jobs.get(job_id)
        if not job or job.status != "completed":
            return None
        return job.result
    
    def cleanup_old_jobs(self, max_age_hours: int = 24):
        """Remove jobs older than max_age_hours"""
        cutoff = datetime.utcnow().timestamp() - (max_age_hours * 3600)
        old_jobs = [
            job_id for job_id, job in self.jobs.items()
            if job.created_at.timestamp() < cutoff
        ]
        
        for job_id in old_jobs:
            del self.jobs[job_id]
        
        if old_jobs:
            print(f"🧹 Cleaned up {len(old_jobs)} old jobs")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics including queue management metrics"""
        total_jobs = len(self.jobs)
        completed_jobs = len([j for j in self.jobs.values() if j.status == JobStatus.COMPLETED.value])
        failed_jobs = len([j for j in self.jobs.values() if j.status == JobStatus.FAILED.value])
        running_jobs = len([j for j in self.jobs.values() if j.status == JobStatus.RUNNING.value])
        queued_jobs = self.job_queue.qsize()
        timeout_jobs = len([j for j in self.jobs.values() if j.status == JobStatus.TIMEOUT.value])
        retrying_jobs = len([j for j in self.jobs.values() if j.status == JobStatus.RETRYING.value])
        abandoned_jobs = len([j for j in self.jobs.values() if j.status == JobStatus.ABANDONED.value])
        
        # Calculate retry statistics
        total_retries = sum(j.retry_count for j in self.jobs.values())
        jobs_with_retries = len([j for j in self.jobs.values() if j.retry_count > 0])
        
        return {
            "service_running": self.running,
            "active_workers": len(self.workers),
            "active_jobs_count": len(self.active_jobs),
            "total_jobs": total_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "running_jobs": running_jobs,
            "queued_jobs": queued_jobs,
            "timeout_jobs": timeout_jobs,
            "retrying_jobs": retrying_jobs,
            "abandoned_jobs": abandoned_jobs,
            "jobs_with_retries": jobs_with_retries,
            "total_retries": total_retries,
            "success_rate": round((completed_jobs / total_jobs) * 100, 1) if total_jobs > 0 else 0
        }

# Global instance
enhanced_background_service = EnhancedBackgroundTaskService()