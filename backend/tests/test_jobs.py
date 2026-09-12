from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.jobs import MODEL_ID
from app.main import create_app
from test_api import settings, board, upload

TOKEN = 'phase3-test-credential'
HEADERS = {'Authorization': 'Bearer ' + TOKEN}

@pytest.fixture
def client(settings):
    with TestClient(create_app(replace(settings, worker_token=TOKEN))) as c:
        yield c

def claim(c, kind='cpu_process'):
    return c.post('/internal/jobs/claim', json={'type': kind}, headers=HEADERS)

def complete(c, job, payload):
    return c.post(f"/internal/jobs/{job['id']}/complete", headers=HEADERS,
                  json={'type': job['type'], 'attempt_token': job['attempt_token'], **payload})

def cpu(settings, job):
    path = settings.storage_dir / job['thumbnail_path']
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (32, 24), (90, 120, 50)).save(path)
    return {'thumbnail_path': job['thumbnail_path'],
            'palette': [{'hex': '#5a7832', 'lab': [45, -20, 30], 'weight': 0.2} for _ in range(5)]}

def ai():
    return {'embedding': [1.] + [0.] * 511, 'model_id': MODEL_ID}

def expire(settings, job):
    with psycopg.connect(settings.database_url) as conn:
        conn.execute("UPDATE jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (job['id'],))

def test_upload_creates_independent_jobs_and_credentials(client, settings):
    image = upload(client, board(client)).json()
    assert image['cpu_status'] == image['ai_status'] == 'pending'
    assert image['palette'] is None and image['thumbnail_url'] is None
    assert not image['embedding_ready']
    for headers in ({}, {'Authorization': 'Bearer wrong'}):
        assert client.post('/internal/jobs/claim', json={'type': 'cpu_process'}, headers=headers).status_code == 401
        assert client.post(f'/internal/jobs/{uuid4()}/fail', json={'attempt_token': str(uuid4()), 'error': 'x'}, headers=headers).status_code == 401
        assert client.post(f'/internal/jobs/{uuid4()}/complete', json={'type': 'ai_embed', 'attempt_token': str(uuid4()), **ai()}, headers=headers).status_code == 401
    with TestClient(create_app(settings)) as disabled:
        assert claim(disabled).status_code == 503
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM image_features').fetchone()[0] == 1

def test_parallel_workers_claim_distinct_jobs(client):
    b = board(client)
    for _ in range(8):
        assert upload(client, b).status_code == 201
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: claim(client), range(8)))
    assert all(r.status_code == 200 for r in results)
    assert len({r.json()['id'] for r in results}) == 8
    assert claim(client).status_code == 204
    assert claim(client, 'ai_embed').status_code == 200

@pytest.mark.parametrize('parallel', [False, True])
def test_results_persist_without_overwrite(client, settings, parallel):
    image = upload(client, board(client)).json()
    cj, aj = claim(client).json(), claim(client, 'ai_embed').json()
    cp = cpu(settings, cj)
    tasks = [(cj, cp), (aj, ai())]
    if parallel:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda pair: complete(client, *pair), tasks))
    else:
        responses = [complete(client, *pair) for pair in reversed(tasks)]
    assert [r.status_code for r in responses] == [200, 200]
    with TestClient(create_app(replace(settings, worker_token=TOKEN))) as fresh:
        result = fresh.get(f"/images/{image['id']}").json()
        assert result['cpu_status'] == result['ai_status'] == 'succeeded'
        assert len(result['palette']) == 5 and result['embedding_ready']
        assert fresh.get(f"/media/{image['id']}/thumbnail").status_code == 200
        assert 'thumbnail_path' not in result and 'attempt_token' not in result
    with psycopg.connect(settings.database_url) as conn:
        palette, embedding, model = conn.execute('SELECT palette_json,embedding,model_id FROM image_features').fetchone()
        assert len(palette) == 5 and len(embedding) == 512 and model == MODEL_ID
    assert complete(client, cj, cp).status_code == 409


def test_expired_attempt_rejected_and_retried(client, settings):
    upload(client, board(client))
    old = claim(client).json()
    payload = cpu(settings, old)
    expire(settings, old)
    assert complete(client, old, payload).status_code == 409
    new = claim(client).json()
    assert new['id'] == old['id'] and new['attempt_token'] != old['attempt_token']
    assert new['attempt_count'] == 2 and new['thumbnail_path'] != old['thumbnail_path']
    assert client.post(f"/internal/jobs/{old['id']}/fail", headers=HEADERS,
                       json={'attempt_token': old['attempt_token'], 'error': 'late'}).status_code == 409
    assert complete(client, new, cpu(settings, new)).status_code == 200
    assert complete(client, old, payload).status_code == 409
    assert client.get(f"/images/{old['image_id']}").json()['cpu_status'] == 'succeeded'


def test_failures_and_exhausted_leases_preserve_cpu(client, settings):
    image = upload(client, board(client)).json()
    cj = claim(client).json()
    assert complete(client, cj, cpu(settings, cj)).status_code == 200
    for attempt in range(1, 4):
        aj = claim(client, 'ai_embed').json()
        assert aj['attempt_count'] == attempt
        if attempt == 3:
            expire(settings, aj)
        else:
            r = client.post(f"/internal/jobs/{aj['id']}/fail", headers=HEADERS,
                            json={'attempt_token': aj['attempt_token'], 'error': 'temporary'})
            assert r.json()['status'] == 'pending'
    assert claim(client, 'ai_embed').status_code == 204
    result = client.get(f"/images/{image['id']}").json()
    assert result['ai_status'] == 'failed' and result['ai_error']
    assert result['cpu_status'] == 'succeeded' and result['palette']
    assert client.get(f"/media/{image['id']}/thumbnail").status_code == 200


def test_terminal_failure_and_result_validation(client, settings):
    upload(client, board(client))
    cj, aj = claim(client).json(), claim(client, 'ai_embed').json()
    assert complete(client, aj, {**ai(), 'embedding': [0.] * 512}).status_code == 422
    assert complete(client, aj, {**ai(), 'embedding': [1.]}).status_code == 422
    assert complete(client, aj, {**ai(), 'model_id': 'wrong'}).status_code == 422
    payload = cpu(settings, cj)
    assert complete(client, cj, {**payload, 'thumbnail_path': '../outside.jpg'}).status_code == 422
    assert complete(client, cj, {**payload, 'palette': payload['palette'][:4]}).status_code == 422
    other = {**cj, 'attempt_token': str(uuid4())}
    assert complete(client, other, cpu(settings, other)).status_code == 409
    assert complete(client, {**cj, 'type': 'ai_embed'}, ai()).status_code == 422
    assert client.get(f"/images/{cj['image_id']}").json()['palette'] is None
    r = client.post(f"/internal/jobs/{aj['id']}/fail", headers=HEADERS,
                    json={'attempt_token': aj['attempt_token'], 'error': 'invalid model input', 'retryable': False})
    assert r.json()['status'] == 'failed'
    assert claim(client, 'ai_embed').status_code == 204


def test_queue_transaction_rollback(client, settings):
    b = board(client)
    with psycopg.connect(settings.database_url) as conn:
        conn.execute("""CREATE FUNCTION reject_job() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'test queue failure'; END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER reject_job BEFORE INSERT ON jobs FOR EACH ROW EXECUTE FUNCTION reject_job();""")
    assert upload(client, b).status_code == 503
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute('SELECT count(*) FROM images').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM image_features').fetchone()[0] == 0
    assert not list((settings.storage_dir / 'originals').iterdir())


def test_migration_backfills_phase2_images_once(settings):
    from pathlib import Path
    schema = Path(__file__).parents[1] / 'app' / 'schema.sql'
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(schema.read_text().split('-- Migration 2:')[0])
        b, i = uuid4(), uuid4()
        conn.execute("INSERT INTO boards(id,name) VALUES(%s,'Old board')", (b,))
        conn.execute("""INSERT INTO images(id,board_id,original_path,original_filename,mime_type,byte_size,width,height)
                     VALUES(%s,%s,'originals/old.png','old.png','image/png',100,32,24)""", (i, b))
    for _ in range(2):
        with TestClient(create_app(settings)) as c:
            result = c.get(f'/images/{i}').json()
            assert result['cpu_status'] == result['ai_status'] == 'pending'
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 2


def test_completion_is_atomic_on_database_failure(client, settings):
    image = upload(client, board(client)).json()
    job = claim(client).json()
    payload = cpu(settings, job)
    with psycopg.connect(settings.database_url) as conn:
        conn.execute("""CREATE FUNCTION reject_completion() RETURNS trigger AS $$
        BEGIN IF NEW.status='succeeded' THEN RAISE EXCEPTION 'test completion failure'; END IF;
        RETURN NEW; END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER reject_completion BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION reject_completion();""")
    assert complete(client, job, payload).status_code == 503
    result = client.get(f"/images/{image['id']}").json()
    assert result['palette'] is None and result['thumbnail_url'] is None
    assert result['cpu_status'] == 'running'
    assert client.get(f"/media/{image['id']}/thumbnail").status_code == 404
