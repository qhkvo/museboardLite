"""PostgreSQL job coordination. Only the API accesses the database."""
import hmac
import math
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from psycopg.types.json import Jsonb
from PIL import Image

MODEL_ID = 'Xenova/clip-vit-base-patch32@d15189d7028b43f1d3e65039190477f6af591c2a/onnx/vision_model.onnx'

class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Claim(Payload):
    type: Literal['cpu_process', 'ai_embed']

class Color(Payload):
    hex: str = Field(pattern=r'^#[0-9a-fA-F]{6}$')
    lab: tuple[float, float, float]
    weight: float = Field(ge=0, le=1)

    @model_validator(mode='after')
    def valid_lab(self):
        if not (0 <= self.lab[0] <= 100 and all(-128 <= v <= 128 for v in self.lab[1:])):
            raise ValueError('LAB values are outside the supported range.')
        return self

class CpuResult(Payload):
    type: Literal['cpu_process']
    attempt_token: UUID
    thumbnail_path: str = Field(max_length=200)
    palette: list[Color] = Field(min_length=5, max_length=5)

    @model_validator(mode='after')
    def normalized(self):
        if not math.isclose(sum(c.weight for c in self.palette), 1, abs_tol=0.001):
            raise ValueError('Palette weights must sum to one.')
        return self

class AiResult(Payload):
    type: Literal['ai_embed']
    attempt_token: UUID
    model_id: Literal[MODEL_ID]
    embedding: list[float] = Field(min_length=512, max_length=512)

    @model_validator(mode='after')
    def normalized(self):
        if not math.isclose(math.hypot(*self.embedding), 1, abs_tol=0.001):
            raise ValueError('Embedding must have unit L2 norm.')
        return self

class Failure(Payload):
    attempt_token: UUID
    error: str = Field(min_length=1, max_length=2000)
    retryable: bool = True

# Avoid exposing storage paths, attempt credentials, or full vectors in board responses.
IMAGE_SELECT = '''SELECT i.*, f.palette_json AS palette, f.model_id,
    (f.embedding IS NOT NULL) AS embedding_ready,
    cpu.status AS cpu_status, cpu.error AS cpu_error,
    ai.status AS ai_status, ai.error AS ai_error
    FROM images i JOIN image_features f ON f.image_id=i.id
    JOIN jobs cpu ON cpu.image_id=i.id AND cpu.type='cpu_process'
    JOIN jobs ai ON ai.image_id=i.id AND ai.type='ai_embed' '''

# Avoid exposing storage paths, attempt credentials, or full vectors in board responses.
def register_jobs(app, settings, connect):
    def authorize(authorization: str = Header(default='')):
        if not settings.worker_token:
            raise HTTPException(503, 'Worker credential is not configured.')
        if not hmac.compare_digest(authorization.encode(), ('Bearer ' + settings.worker_token).encode()):
            raise HTTPException(401, 'Invalid worker credential.')

    # Lock the job row and verify that the attempt token matches and the lease is still valid.
    def current_attempt(conn, job_id, token):
        job = conn.execute('SELECT * FROM jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, 'Job not found.')
        live = conn.execute('SELECT clock_timestamp() < %s AS live', (job['lease_expires_at'],)).fetchone()['live']
        if job['status'] != 'running' or job['attempt_token'] != token or not live:
            raise HTTPException(409, 'Attempt is no longer current. Discard this result.')
        return job

    # Workers claim a job, which locks the row and returns an attempt token. The worker must complete or fail the job before the lease expires.
    @app.post('/internal/jobs/claim', dependencies=[Depends(authorize)])
    def claim(body: Claim):
        with connect() as conn:
            # Skip locked rows in both recovery and claiming so workers don't wait behind a different worker's completion or claim transaction.
            conn.execute('''WITH exhausted AS (
                SELECT id FROM jobs WHERE type=%s AND attempt_count >= %s
                AND (status='pending' OR (status='running' AND lease_expires_at <= clock_timestamp()))
                FOR UPDATE SKIP LOCKED)
                UPDATE jobs SET status='failed', error='Processing deadline exceeded.',
                updated_at=clock_timestamp() WHERE id IN (SELECT id FROM exhausted)''',
                (body.type, settings.max_attempts))
            
            job = conn.execute('''SELECT j.*, i.original_path FROM jobs j
                JOIN images i ON i.id=j.image_id
                WHERE j.type=%s AND j.attempt_count < %s AND
                (j.status='pending' OR (j.status='running' AND j.lease_expires_at <= clock_timestamp()))
                ORDER BY j.created_at, j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1''',
                (body.type, settings.max_attempts)).fetchone()
            
            if not job:
                return Response(status_code=204)
            
            token = uuid4()
            seconds = settings.cpu_deadline_seconds if body.type == 'cpu_process' else settings.ai_deadline_seconds
            attempt = conn.execute('''UPDATE jobs SET status='running', attempt_count=attempt_count+1,
                attempt_token=%s, lease_expires_at=clock_timestamp() + %s * interval '1 second',
                error=NULL, updated_at=clock_timestamp() WHERE id=%s
                RETURNING attempt_count, lease_expires_at''', (token, seconds, job['id'])).fetchone()

        return {'id': job['id'], 'image_id': job['image_id'], 'type': body.type,
                'original_path': job['original_path'], 'attempt_token': token,
                'thumbnail_path': f"thumbnails/{job['image_id']}/{token}.jpg", **attempt}

    # Workers complete a job, which updates the image and feature rows and marks the job as succeeded. The attempt token must match and the lease must still be valid.
    @app.post('/internal/jobs/{job_id}/complete', dependencies=[Depends(authorize)])
    def complete(job_id: UUID, body: Annotated[CpuResult | AiResult, Field(discriminator='type')]):
        # Validate the attempt-specific file before locking the row. The lease is
        # checked after validation; an expired worker cannot publish its thumbnail.
        if isinstance(body, CpuResult):
            path = (settings.storage_dir / body.thumbnail_path).resolve()
            root = (settings.storage_dir / 'thumbnails').resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise HTTPException(422, 'Thumbnail is unavailable.')
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError()
                with Image.open(path) as image:
                    if image.format != 'JPEG' or max(image.size) > 512:
                        raise ValueError()
                    image.verify()
                with Image.open(path) as image:
                    image.load()

            except (OSError, ValueError, Image.DecompressionBombError):
                raise HTTPException(422, 'Invalid thumbnail.')
            
        with connect() as conn:
            job = current_attempt(conn, job_id, body.attempt_token)
            if job['type'] != body.type:
                raise HTTPException(422, 'Result type does not match job.')
            
            if isinstance(body, CpuResult):
                expected = f"thumbnails/{job['image_id']}/{body.attempt_token}.jpg"
                if body.thumbnail_path != expected:
                    raise HTTPException(422, 'Thumbnail path does not belong to this attempt.')
                conn.execute('UPDATE images SET thumbnail_path=%s WHERE id=%s', (expected, job['image_id']))
                conn.execute('UPDATE image_features SET palette_json=%s WHERE image_id=%s',
                             (Jsonb([c.model_dump() for c in body.palette]), job['image_id']))
            else:
                conn.execute('UPDATE image_features SET embedding=%s::real[]::public.vector, model_id=%s WHERE image_id=%s',
                             (body.embedding, body.model_id, job['image_id']))
                
            # Feature updates can wait on the other job's row lock. Check the
            # deadline again before committing; HTTPException rolls back results.
            updated = conn.execute('''UPDATE jobs SET status='succeeded', error=NULL,
                updated_at=clock_timestamp() WHERE id=%s AND lease_expires_at > clock_timestamp()
                RETURNING id''', (job_id,)).fetchone()
            
            if not updated:
                raise HTTPException(409, 'Attempt expired while saving results.')
            
        return {'status': 'succeeded'}

    # Workers report a failure, which marks the job as failed or pending for retry. The attempt token must match and the lease must still be valid.
    @app.post('/internal/jobs/{job_id}/fail', dependencies=[Depends(authorize)])
    def fail(job_id: UUID, body: Failure):
        with connect() as conn:
            job = current_attempt(conn, job_id, body.attempt_token)
            status = 'pending' if body.retryable and job['attempt_count'] < settings.max_attempts else 'failed'
            updated = conn.execute('''UPDATE jobs SET status=%s, error=%s, updated_at=clock_timestamp()
                WHERE id=%s AND lease_expires_at > clock_timestamp() RETURNING id''',
                (status, body.error, job_id)).fetchone()
            
            if not updated:
                raise HTTPException(409, 'Attempt expired while reporting failure.')
        return {'status': status}
