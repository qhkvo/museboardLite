"""Exact collection-wide image discovery; distances are lower-is-closer."""
from math import dist
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Query
from .jobs import IMAGE_SELECT

# Initial cutoff calibrated on the chair collection; cosine similarity is not a probability.
SEMANTIC_MIN_SIMILARITY = 0.75
# Initial LAB distance heuristics; lower means closer, not confidence.
COLOR_MAX_DISTANCE = 15.0
PALETTE_MAX_DISTANCE = 15.0


def palette_distance(left, right):
    # Zero-weight padding colors must not attract real colors.
    left = [c for c in left if c['weight'] > 0]
    right = [c for c in right if c['weight'] > 0]

    def directed(a, b):
        return sum(c['weight'] * min(dist(c['lab'], d['lab']) for d in b) for c in a) / sum(c['weight'] for c in a)

    return (directed(left, right) + directed(right, left)) / 2


def register_discovery(app, connect, image_json):
    @app.get('/images/{image_id}/similar')
    def similar(image_id: UUID, mode: Literal['semantic', 'color', 'subject'] = 'semantic',
                limit: int = Query(24, ge=1, le=100), offset: int = Query(0, ge=0),
                include_weak: bool = False,
                swatch: int | None = Query(None, ge=0, le=4),
                subject: str | None = Query(None, min_length=1, max_length=40)):
        if subject is not None:
            subject = ' '.join(subject.lower().split())
        if (mode == 'subject') != (subject is not None):
            raise HTTPException(422, 'Select a subject only for same-subject search.')
        
        if swatch is not None and mode != 'color':
            raise HTTPException(422, 'Swatch selection requires color mode.')
        
        with connect() as conn:
            source = conn.execute(IMAGE_SELECT + 'WHERE i.id=%s', (image_id,)).fetchone()
            if source is None:
                raise HTTPException(404, 'Image not found.')
            
            if mode == 'subject' and subject not in source['subject_tags']:
                raise HTTPException(422, 'Select a subject assigned to this image.')

            ready = (source['embedding_ready'] and source['ai_status'] == 'succeeded') if mode in ('semantic', 'subject') else (source['palette'] and source['cpu_status'] == 'succeeded')
            
            if not ready:
                raise HTTPException(409, 'Visual features are not ready.' if mode in ('semantic', 'subject') else 'Color palette is not ready.')
            
            if mode in ('semantic', 'subject'):
                query = IMAGE_SELECT.replace('SELECT i.*,', '''SELECT i.*,
                    f.embedding <=> (SELECT embedding FROM image_features WHERE image_id=%s) AS distance,''')
                rows = conn.execute('SELECT * FROM (' + query + '''WHERE i.id != %s AND ai.status='succeeded'
                    AND f.embedding IS NOT NULL AND f.model_id=%s
                    AND (%s::text IS NULL OR i.subject_tags @> ARRAY[%s]::text[])
                    ) AS candidates WHERE (%s OR distance <= %s)
                    ORDER BY distance, id LIMIT %s OFFSET %s''',
                    (image_id, image_id, source['model_id'], subject, subject, include_weak or mode == 'subject',
                     1 - SEMANTIC_MIN_SIMILARITY, limit + 1, offset)).fetchall()
            else:
                selected = None
                if swatch is not None:
                    if swatch >= len(source['palette']) or source['palette'][swatch]['weight'] <= 0:
                        raise HTTPException(422, 'Selected color is unavailable.')
                    selected = source['palette'][swatch]

                rows = conn.execute(IMAGE_SELECT + '''WHERE i.id != %s
                    AND cpu.status='succeeded' AND f.palette_json IS NOT NULL''', (image_id,)).fetchall()
                
                for row in rows:
                    row['distance'] = (
                        min(dist(selected['lab'], color['lab'])
                            for color in row['palette'] if color['weight'] > 0)
                        if selected is not None else palette_distance(source['palette'], row['palette'])
                    )

                cutoff = COLOR_MAX_DISTANCE if selected is not None else PALETTE_MAX_DISTANCE

                if not include_weak:
                    rows = [row for row in rows if row['distance'] <= cutoff]

                rows.sort(key=lambda row: (row['distance'], row['id']))
                rows = rows[offset:offset + limit + 1]

        return {'mode': mode, 'source_id': image_id, 'has_more': len(rows) > limit,
                'results': [image_json(row) for row in rows[:limit]]}
