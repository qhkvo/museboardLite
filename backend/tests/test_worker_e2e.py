"""Opt-in test of real C++ processes, real HTTP and PostgreSQL (no inference mocks)."""
import io
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

import httpx
from PIL import Image
import pytest
import uvicorn

from app.main import create_app
from test_api import settings

@pytest.mark.skipif(os.environ.get('RUN_WORKER_E2E') != '1', reason='Set RUN_WORKER_E2E=1 with a built worker and pinned model.')
def test_real_cpu_and_ai_workers(settings):
    root = Path(__file__).resolve().parents[2]
    binary = root / 'build' / 'museboard-worker'
    assert binary.is_file()
    assert (root / 'models' / 'vision_model.onnx').is_file()
    credential = 'isolated-e2e-worker-credential'
    from dataclasses import replace
    app = create_app(replace(settings, worker_token=credential))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    processes, logs = [], []
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, 'API did not start'
            time.sleep(.05)
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=30) as client:
            board = client.post('/boards', json={'name': 'Real worker verification'}).json()['id']
            ids = []
            # Queue enough nontrivial images that both CPU processes receive work.
            for i in range(8):
                data = io.BytesIO()
                Image.effect_noise((768, 512), 60 + i).convert('RGB').save(data, format='PNG')
                r = client.post(f'/boards/{board}/images', files={'file': (f'fixture-{i}.png', data.getvalue())})
                assert r.status_code == 201, r.text
                ids.append(r.json()['id'])
            env = os.environ | {'API_URL': str(client.base_url), 'WORKER_TOKEN': credential,
                                'STORAGE_DIR': str(settings.storage_dir)}
            for index, mode in enumerate(['cpu', 'cpu', 'ai']):
                log = (settings.storage_dir / f'worker-{index}.log').open('w+')
                logs.append(log)
                processes.append(subprocess.Popen([str(binary), '--mode', mode], cwd=root, env=env,
                                                   stdout=log, stderr=subprocess.STDOUT))
            deadline = time.monotonic() + 120
            while True:
                images = client.get(f'/boards/{board}/images').json()
                if all(i['cpu_status'] == i['ai_status'] == 'succeeded' for i in images):
                    break
                assert all(p.poll() is None for p in processes), 'A worker exited unexpectedly'
                assert not any(i['cpu_status'] == 'failed' or i['ai_status'] == 'failed' for i in images), images
                assert time.monotonic() < deadline, images
                time.sleep(.2)
            for image in images:
                assert len(image['palette']) == 5 and image['embedding_ready']
                thumbnail = client.get(f"/media/{image['id']}/thumbnail")
                assert thumbnail.status_code == 200
                with Image.open(io.BytesIO(thumbnail.content)) as decoded:
                    assert decoded.size == (512, 341)
            # A subsequent upload is picked up by already-running workers.
            data.seek(0)
            r = client.post(f'/boards/{board}/images', files={'file': ('later.png', data.getvalue())})
            later = r.json()['id']
            deadline = time.monotonic() + 30
            while True:
                result = client.get(f'/images/{later}').json()
                if result['cpu_status'] == result['ai_status'] == 'succeeded':
                    break
                assert time.monotonic() < deadline, result
                time.sleep(.2)
        for log in logs:
            log.flush()
            log.seek(0)
            assert 'succeeded' in log.read(), 'Each real worker must finish at least one job'
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
