from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4
import logging
import os
import warnings

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image, UnidentifiedImageError

from .jobs import IMAGE_SELECT, register_jobs

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class Settings:
    database_url: str
    storage_dir: Path
    max_upload_bytes: int = 20 * 1024 * 1024
    max_pixels: int = 40_000_000

    worker_token: str = ''
    cpu_deadline_seconds: int = 120
    ai_deadline_seconds: int = 300
    max_attempts: int = 3

    def __post_init__(self):
        if min(self.cpu_deadline_seconds, self.ai_deadline_seconds, self.max_attempts) < 1:
            raise ValueError('Worker deadlines and attempt limit must be positive.')

    @classmethod
    def from_env(cls):
        return cls(os.environ.get('DATABASE_URL', 'postgresql://museboard:museboard@127.0.0.1:5433/museboard_dev'),
                   Path(os.environ.get('STORAGE_DIR', './data')).resolve(),
                   worker_token=os.environ.get('WORKER_TOKEN', ''),
                   cpu_deadline_seconds=int(os.environ.get('CPU_DEADLINE_SECONDS', '120')),
                   ai_deadline_seconds=int(os.environ.get('AI_DEADLINE_SECONDS', '300')),
                   max_attempts=int(os.environ.get('MAX_JOB_ATTEMPTS', '3')))

class BoardCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=1000)

class BodyLimit:
    # Middleware to limit the size of request bodies for certain HTTP methods.
    def __init__(self, app, upload_limit):
        self.app, self.upload_limit = app, upload_limit

    # The __call__ method is the entry point for the middleware. Checks the request type and method
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ('POST', 'PUT', 'PATCH'):
            return await self.app(scope, receive, send)
        
        limit = self.upload_limit + 1024 * 1024 if scope['path'].endswith('/images') else 32 * 1024
        data = bytearray()

        # Read the request body in chunks and check the size against the limit
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            data.extend(message.get('body', b''))
            if len(data) > limit:
                return await JSONResponse({'detail': 'Request is too large. Images must be 20 MB or less.'}, status_code=413)(scope, receive, send)
            if not message.get('more_body', False):
                break

        consumed = False
        # Define a replay function to send the request body to the application
        async def replay():
            nonlocal consumed
            if consumed:
                return await receive()
            consumed = True
            return {'type': 'http.request', 'body': bytes(data), 'more_body': False}
        
        await self.app(scope, replay, send)


# Inspect an image file for validity, size, and format. Raises HTTPException on failure.
def inspect_image(path: Path, settings: Settings):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in ('JPEG', 'PNG'):
                    raise HTTPException(415, 'Only JPEG and PNG images are supported.')
                width, height = image.size
                if width * height > settings.max_pixels or max(width, height) > 16384:
                    raise HTTPException(413, 'Image exceeds 40 megapixels or 16,384 pixels on one side.')
                if max(width, height) / min(width, height) > 100:
                    raise HTTPException(422, 'Image aspect ratio exceeds 100:1.')
                if getattr(image, 'n_frames', 1) > 1:
                    raise HTTPException(415, 'Animated images are not supported. Use a still JPEG or PNG.')
                fmt = image.format
                image.verify()

            with Image.open(path) as image:
                image.load()  # Reject truncated files, not just malformed headers.
                if image.getexif().get(274) in (5, 6, 7, 8):
                    width, height = height, width
            return ('image/jpeg', '.jpg', width, height) if fmt == 'JPEG' else ('image/png', '.png', width, height)
    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(413, 'Image dimensions are too large.')
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise HTTPException(422, 'This file is not a valid, complete JPEG or PNG image.')

# Create the FastAPI application with database connection and routes.
def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    def connect():
        return psycopg.connect(settings.database_url, row_factory=dict_row, connect_timeout=5)

    # Use an async context manager for the application lifespan to set up storage directories and initialize the database schema.
    @asynccontextmanager
    async def lifespan(app):
        (settings.storage_dir / 'originals').mkdir(parents=True, exist_ok=True)
        (settings.storage_dir / 'thumbnails').mkdir(parents=True, exist_ok=True)
        (settings.storage_dir / 'incoming').mkdir(parents=True, exist_ok=True)
        with connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(71422002)')
            conn.execute(Path(__file__).with_name('schema.sql').read_text())
        yield

    app = FastAPI(title='Museboard API', version='0.3.0', lifespan=lifespan)
    app.add_middleware(BodyLimit, upload_limit=settings.max_upload_bytes)

    @app.exception_handler(psycopg.Error)
    async def database_error(request, exc):
        logger.exception('Database request failed', exc_info=exc)
        return JSONResponse({'detail': 'Storage is temporarily unavailable. Please try again.'}, status_code=503)

    # Helper function to ensure a board exists in the database, raising a 404 error if not found.
    def require_board(conn, board_id):
        row = conn.execute('SELECT * FROM boards WHERE id = %s', (board_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Board not found.')
        return row

    def image_json(row):
        return {k: v for k, v in row.items() if k not in ('original_path', 'thumbnail_path')} | {
            'original_url': f"/api/media/{row['id']}",
            'thumbnail_url': f"/api/media/{row['id']}/thumbnail" if row.get('thumbnail_path') else None}

    @app.get('/health')
    def health():
        with connect() as conn:
            conn.execute('SELECT 1')
        return {'status': 'ok'}

    @app.get('/boards')
    def boards():
        with connect() as conn:
            # Retrieve all boards along the count of images for each board & the ID of the most recently created image (cover image) for each board.
            return conn.execute('''SELECT b.*, count(i.id)::int AS image_count,
                (SELECT id FROM images WHERE board_id=b.id ORDER BY created_at DESC, id DESC LIMIT 1) AS cover_image_id
                FROM boards b LEFT JOIN images i ON i.board_id=b.id
                GROUP BY b.id ORDER BY b.created_at DESC, b.id DESC''').fetchall()

    @app.post('/boards', status_code=201)
    def create_board(body: BoardCreate):
        with connect() as conn:
            row = conn.execute('INSERT INTO boards(id,name,description) VALUES(%s,%s,%s) RETURNING *',
                               (uuid4(), body.name, body.description)).fetchone()
        return row | {'image_count': 0, 'cover_image_id': None}

    @app.get('/boards/{board_id}')
    def board(board_id: UUID):
        with connect() as conn:
            row = require_board(conn, board_id)
            count = conn.execute('SELECT count(*) AS n FROM images WHERE board_id=%s', (board_id,)).fetchone()['n']
        return row | {'image_count': count}

    @app.get('/boards/{board_id}/images')
    def images(board_id: UUID, limit: int = Query(60, ge=1, le=100), offset: int = Query(0, ge=0)):
        with connect() as conn:
            require_board(conn, board_id)
            rows = conn.execute(IMAGE_SELECT + 'WHERE i.board_id=%s ORDER BY i.created_at DESC,i.id DESC LIMIT %s OFFSET %s',
                                (board_id, limit, offset)).fetchall()       # Fetch images for the specified board
        return [image_json(row) for row in rows]

    @app.post('/boards/{board_id}/images', status_code=201)
    def upload(board_id: UUID, file: UploadFile = File(...)):
        # One file per request gives the UI independent progress, failures and retries.
        with connect() as conn:
            require_board(conn, board_id)
        image_id = uuid4()
        temporary = settings.storage_dir / 'incoming' / f'{image_id}.part'
        destination = None
        committed = False

        try:
            size = 0
            with temporary.open('xb') as out:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(413, 'Image must be 20 MB or less.')
                    out.write(chunk)

            mime, suffix, width, height = inspect_image(temporary, settings)
            relative = Path('originals') / f'{image_id}{suffix}'
            destination = settings.storage_dir / relative
            temporary.replace(destination)
            filename = (file.filename or 'image').replace('\\', '/').split('/')[-1]
            filename = ''.join(c for c in filename if c.isprintable())[:255] or 'image'

            # Insert the image metadata into the database and return the image details as JSON.
            with connect() as conn:
                row = conn.execute('''INSERT INTO images(id,board_id,original_path,original_filename,mime_type,byte_size,width,height)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                    (image_id, board_id, str(relative), filename, mime, size, width, height)).fetchone()
                conn.execute('INSERT INTO image_features(image_id) VALUES (%s)', (image_id,))
                conn.execute("INSERT INTO jobs(image_id,type) VALUES (%s,'cpu_process'),(%s,'ai_embed')", (image_id, image_id))
                row = conn.execute(IMAGE_SELECT + 'WHERE i.id=%s', (image_id,)).fetchone()
            committed = True
            return image_json(row)
        
        finally:
            file.file.close()
            temporary.unlink(missing_ok=True)
            if destination is not None and not committed:
                destination.unlink(missing_ok=True)

    @app.get('/images/{image_id}')
    def image_detail(image_id: UUID):
        with connect() as conn:
            row = conn.execute(IMAGE_SELECT + 'WHERE i.id=%s', (image_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Image not found.')
        return image_json(row)

    # Serve the original image file for a given image ID, ensuring it exists and is within the allowed storage directory.
    @app.get('/media/{image_id}')
    def media(image_id: UUID):
        with connect() as conn:
            row = conn.execute('SELECT * FROM images WHERE id=%s', (image_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Image not found.')
        path = (settings.storage_dir / row['original_path']).resolve()
        if not path.is_relative_to((settings.storage_dir / 'originals').resolve()) or not path.is_file():
            raise HTTPException(404, 'Original image is unavailable.')
        return FileResponse(path, media_type=row['mime_type'], headers={
            'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, max-age=3600'})

    # Serve the thumbnail image file for a given image ID, ensuring it exists and is within the allowed storage directory.
    @app.get('/media/{image_id}/thumbnail')
    def thumbnail_media(image_id: UUID):
        with connect() as conn:
            row = conn.execute('SELECT thumbnail_path FROM images WHERE id=%s', (image_id,)).fetchone()
        if not row or not row['thumbnail_path']:
            raise HTTPException(404, 'Thumbnail is not ready.')
        path = (settings.storage_dir / row['thumbnail_path']).resolve()
        if not path.is_relative_to((settings.storage_dir / 'thumbnails').resolve()) or not path.is_file():
            raise HTTPException(404, 'Thumbnail is unavailable.')
        return FileResponse(path, media_type='image/jpeg', headers={
            'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, max-age=3600'})

    register_jobs(app, settings, connect)
    return app

app = create_app()
