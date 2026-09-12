import io
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.main import Settings, create_app

@pytest.fixture
def settings(tmp_path):
    dsn = os.environ.get('TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('Set TEST_DATABASE_URL to a PostgreSQL database; each test uses an isolated schema.')
    schema = 'test_' + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    scoped = make_conninfo(dsn, options=f'-csearch_path={schema}')
    yield Settings(scoped, tmp_path)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c

def picture(fmt='PNG', size=(32, 24), orientation=None):
    out = io.BytesIO()
    image = Image.new('RGB', size, (90, 120, 50))
    kwargs = {}
    if orientation:
        exif = Image.Exif()
        exif[274] = orientation
        kwargs['exif'] = exif
    image.save(out, format=fmt, **kwargs)
    return out.getvalue()

def board(client, name='Ideas'):
    response = client.post('/boards', json={'name':name, 'description':'A small collection'})
    assert response.status_code == 201, response.text
    return response.json()['id']

def upload(client, board_id, data=None, filename='test.png'):
    return client.post(f'/boards/{board_id}/images', files={'file':(filename, data if data is not None else picture(), 'application/octet-stream')})

def test_persistence_and_original_integrity(settings):
    original = picture('JPEG', orientation=6)
    with TestClient(create_app(settings)) as c:
        b = board(c)
        r = upload(c, b, original, '../portrait.jpg')
        assert r.status_code == 201, r.text
        image = r.json()
        assert (image['width'], image['height']) == (24, 32)
        assert image['original_filename'] == 'portrait.jpg'
        assert 'original_path' not in image
        assert c.get(f"/media/{image['id']}").content == original
    # A fresh app instance, database connection and lifespan still see the same data.
    with TestClient(create_app(settings)) as c:
        assert c.get('/boards').json()[0]['image_count'] == 1
        assert c.get(f'/boards/{b}').json()['name'] == 'Ideas'
        assert c.get(f'/boards/{b}/images').json()[0]['id'] == image['id']
        assert c.get(f"/images/{image['id']}").status_code == 200
        media = c.get(f"/media/{image['id']}")
        assert media.content == original and media.headers['content-type']=='image/jpeg'
        assert media.headers['x-content-type-options']=='nosniff'

def test_board_validation(client):
    for name in ['', '   ', 'a'*101]:
        assert client.post('/boards',json={'name':name}).status_code==422
    b = board(client, '  Mountains  ')
    assert client.get(f'/boards/{b}').json()['name']=='Mountains'
    assert client.get(f'/boards/{uuid4()}').status_code==404
    assert client.get('/boards/not-a-uuid').status_code==422

@pytest.mark.parametrize('data,status', [(b'not an image',422), (picture('GIF'),415), (picture()[:30],422), (b'',422)])
def test_invalid_upload_cleanup(client, settings, data, status):
    b = board(client)
    assert upload(client,b,data).status_code==status
    assert not list((settings.storage_dir/'originals').iterdir())
    assert not list((settings.storage_dir/'incoming').iterdir())
    assert client.get(f'/boards/{b}/images').json()==[]

def test_limits(settings):
    with TestClient(create_app(replace(settings,max_upload_bytes=1024,max_pixels=100))) as c:
        b=board(c)
        assert upload(c,b,b'x'*1025).status_code==413
        assert upload(c,b,picture(size=(11,10))).status_code==413
        assert c.post(f'/boards/{b}/images', content=b'x'*(1024*1024+1025)).status_code==413
    assert not list((settings.storage_dir/'originals').iterdir())

def test_boards_isolated_and_parallel_uploads(client):
    a,b=board(client,'A'),board(client,'B')
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses=list(pool.map(lambda _: upload(client,a),range(6)))
    assert all(r.status_code==201 for r in responses)
    assert len({r.json()['id'] for r in responses})==6
    assert len(client.get(f'/boards/{a}/images').json())==6
    assert client.get(f'/boards/{b}/images').json()==[]
    first=client.get(f'/boards/{a}/images?limit=2').json()
    second=client.get(f'/boards/{a}/images?limit=2&offset=2').json()
    assert not {i['id'] for i in first}&{i['id'] for i in second}
    assert client.get(f'/boards/{a}/images?limit=0').status_code==422

def test_database_failure_removes_saved_original(client, settings):
    b=board(client)
    with psycopg.connect(settings.database_url) as conn:
        conn.execute("""CREATE FUNCTION reject_image() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'test insert failure'; END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER reject_image BEFORE INSERT ON images FOR EACH ROW EXECUTE FUNCTION reject_image();""")
    assert upload(client,b).status_code==503
    assert not list((settings.storage_dir/'originals').iterdir())
    assert not list((settings.storage_dir/'incoming').iterdir())

def test_missing_board_and_media(client,settings):
    assert upload(client,uuid4()).status_code==404
    assert client.get(f'/media/{uuid4()}').status_code==404
    assert client.get('/media/not-a-uuid').status_code==422
    assert not list((settings.storage_dir/'originals').iterdir())
