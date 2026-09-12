from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.types.json import Jsonb
import pytest
from app.discovery import palette_distance
from test_api import settings, client, board, upload


def palette(lab):
    return [{'hex': '#888888', 'lab': lab, 'weight': 1},
            *[{'hex': '#000000', 'lab': [0, 0, 0], 'weight': 0} for _ in range(4)]]


def test_palette_metric():
    a, b = palette([50, 0, 0]), palette([60, 0, 0])
    assert palette_distance(a, a) == 0
    assert palette_distance(a, b) == palette_distance(b, a) == 10
    assert palette_distance(palette([0, 0, 0]), a) == 50
    mixed = [{'lab': [50, 0, 0], 'weight': .75}, {'lab': [90, 0, 0], 'weight': .25}]
    assert palette_distance(a, mixed) == 5


def features(settings, image, vector, colors, model='test-model', status='succeeded'):
    with psycopg.connect(settings.database_url) as conn:
        conn.execute('UPDATE image_features SET embedding=%s::real[]::public.vector, model_id=%s, palette_json=%s WHERE image_id=%s',
                     (vector, model, Jsonb(colors), image))
        conn.execute('UPDATE jobs SET status=%s WHERE image_id=%s', (status, image))


def test_ranked_search(client, settings):
    a, b = board(client), board(client, 'Other board')
    ids = [upload(client, a if n == 0 else b).json()['id'] for n in range(5)]
    vectors = [[1., 0.], [.8, .6], [0., 1.], [1., 0.], [1., 0.]]
    for n, image in enumerate(ids):
        features(settings, image, vectors[n] + [0.] * 510, palette([50 + n * 10, 0, 0]),
                 model='different' if n == 3 else 'test-model', status='pending' if n == 4 else 'succeeded')
    response = client.get(f'/images/{ids[0]}/similar?include_weak=true&limit=1')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['has_more'] and data['results'][0]['id'] == ids[1]
    assert data['results'][0]['distance'] == pytest.approx(.2)
    assert 'embedding' not in data['results'][0] and 'original_path' not in data['results'][0]
    page = client.get(f'/images/{ids[0]}/similar?include_weak=true&limit=1&offset=1').json()
    assert not page['has_more'] and page['results'][0]['id'] == ids[2]
    colors = client.get(f'/images/{ids[0]}/similar?mode=color&include_weak=true').json()['results']
    assert [r['id'] for r in colors] == ids[1:4]
    assert [r['distance'] for r in colors] == [10, 20, 30]


def test_unready_empty_and_invalid(client, settings):
    image = upload(client, board(client)).json()['id']
    for mode in ['semantic', 'color']:
        assert client.get(f'/images/{image}/similar?mode={mode}').status_code == 409
    for query in ['mode=wrong', 'limit=0', 'limit=101', 'offset=-1']:
        assert client.get(f'/images/{image}/similar?{query}').status_code == 422
    assert client.get(f'/images/{uuid4()}/similar').status_code == 404
    features(settings, image, [1.] + [0.] * 511, palette([50, 0, 0]))
    for mode in ['semantic', 'color']:
        assert client.get(f'/images/{image}/similar?mode={mode}').json()['results'] == []


def test_phase3_migration_preserves_vectors(settings):
    schema = (Path(__file__).parents[1] / 'app/schema.sql').read_text()
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(schema.split('-- Migration 3:')[0])
        b, i = uuid4(), uuid4()
        conn.execute("INSERT INTO boards(id,name) VALUES(%s,'Existing')", (b,))
        conn.execute("INSERT INTO images(id,board_id,original_path,original_filename,mime_type,byte_size,width,height) VALUES(%s,%s,'originals/a.png','a.png','image/png',10,1,1)", (i,b))
        conn.execute('INSERT INTO image_features(image_id,embedding,model_id) VALUES(%s,%s,%s)', (i,[1.] + [0.] * 511,'old-model'))
        conn.execute(schema)
        conn.execute(schema)
        assert conn.execute('SELECT embedding::real[],model_id FROM image_features').fetchone() == ([1.] + [0.] * 511, 'old-model')
        assert conn.execute("SELECT format_type(atttypid,atttypmod) FROM pg_attribute WHERE attrelid='image_features'::regclass AND attname='embedding'").fetchone()[0] == 'vector(512)'


def test_semantic_cutoff_and_weak_opt_in(client, settings):
    ids = [upload(client, board(client)).json()['id'] for _ in range(4)]
    # Measured chair-like match, cutoff boundary, and unrelated shape-like match.
    from math import sqrt
    for image, score in zip(ids, [1., .85, .75, .70]):
        features(settings, image, [score, sqrt(1-score*score)] + [0.] * 510, palette([50, 0, 0]))
    path = f'/images/{ids[0]}/similar'
    close = client.get(path + '?limit=1').json()
    assert close['has_more'] and close['results'][0]['id'] == ids[1]
    page = client.get(path + '?limit=1&offset=1').json()
    assert not page['has_more'] and page['results'][0]['id'] == ids[2]
    assert client.get(path + '?offset=2').json()['results'] == []
    weak = client.get(path + '?include_weak=true').json()
    assert [r['id'] for r in weak['results']] == ids[1:]
    # Remove all close candidates: do not fill the page with unrelated images.
    for image in ids[1:3]:
        features(settings, image, [0., 1.] + [0.] * 510, palette([50, 0, 0]))
    assert client.get(path).json()['results'] == []
    assert len(client.get(path + '?include_weak=true').json()['results']) == 3
    assert len(client.get(path + '?mode=color').json()['results']) == 3
    assert client.get(path + '?include_weak=invalid').status_code == 422


def test_selected_color_ignores_source_background(client, settings):
    ids = [upload(client, board(client)).json()['id'] for _ in range(4)]
    red = [40, 60, 40]
    source = [{'hex': '#ffffff', 'lab': [100, 0, 0], 'weight': .9},
              {'hex': '#aa1122', 'lab': red, 'weight': .1}]
    features(settings, ids[0], [1.] + [0.] * 511, source)
    for image, lab in zip(ids[1:], [red, [40, 75, 40], [40, -40, -40]]):
        features(settings, image, [1.] + [0.] * 511, palette(lab))
    path = f'/images/{ids[0]}/similar?mode=color'
    # Whole-image palette remains dominated by white; red swatch finds red.
    assert client.get(path).json()['results'] == []
    page = client.get(path + '&swatch=1&limit=1').json()
    assert page['results'][0]['id'] == ids[1] and page['has_more']
    page = client.get(path + '&swatch=1&limit=1&offset=1').json()
    assert page['results'][0]['id'] == ids[2] and not page['has_more']
    assert len(client.get(path + '&swatch=1&include_weak=true').json()['results']) == 3
    for suffix in ['&swatch=4', '&swatch=-1', '&swatch=5']:
        assert client.get(path + suffix).status_code == 422
    assert client.get(f'/images/{ids[0]}/similar?swatch=1').status_code == 422
    assert client.get(f'/images/{ids[1]}/similar?mode=color&swatch=1').status_code == 422


def test_manual_subjects_persist_and_filter_without_cutoff(client, settings):
    ids = [upload(client, board(client)).json()['id'] for _ in range(4)]
    for image, vector in zip(ids, [[1., 0.], [.6, .8], [0., 1.], [1., 0.]]):
        features(settings, image, vector + [0.] * 510, palette([50, 0, 0]))
    for image, tags in zip(ids, [[' Dog ', 'DOG', 'animal'], ['dog'], ['dog'], ['cat']]):
        r = client.patch(f'/images/{image}/subjects', json={'subject_tags': tags})
        assert r.status_code == 200, r.text
    assert client.get(f'/images/{ids[0]}').json()['subject_tags'] == ['animal', 'dog']
    path = f'/images/{ids[0]}/similar?mode=subject&subject=Dog&limit=1'
    first = client.get(path).json()
    assert first['results'][0]['id'] == ids[1] and first['has_more']
    second = client.get(path + '&offset=1').json()
    assert second['results'][0]['id'] == ids[2] and not second['has_more']
    # Include-weak never admits a different subject, even an identical vector.
    assert client.get(path + '&include_weak=true').json() == first
    assert client.get(f'/images/{ids[0]}/similar?mode=subject&subject=cat').status_code == 422
    assert client.get(f'/images/{ids[0]}/similar?mode=subject').status_code == 422
    assert client.get(f'/images/{ids[0]}/similar?subject=dog').status_code == 422
    for tags in [[''], ['a'*41], ['dog/cat'], ['x']*11]:
        assert client.patch(f'/images/{ids[0]}/subjects', json={'subject_tags': tags}).status_code == 422
    assert client.patch(f'/images/{uuid4()}/subjects', json={'subject_tags': []}).status_code == 404
    assert client.patch(f'/images/{ids[1]}/subjects', json={'subject_tags': []}).status_code == 200
    assert client.get(path).json()['results'][0]['id'] == ids[2]
    from app.main import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app(settings)) as fresh:
        assert fresh.get(f'/images/{ids[0]}').json()['subject_tags'] == ['animal', 'dog']
