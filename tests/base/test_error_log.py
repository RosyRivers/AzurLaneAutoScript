import ast
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from module.base.error_log import prune_error_logs


def make_logs(root, count):
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in reversed(range(count)):
        path = root / str(1700000000000 + index)
        path.mkdir()
        (path / 'log.txt').write_text('error {}'.format(index), encoding='utf-8')
        (path / 'screenshot.png').write_bytes(b'example screenshot')
        paths.append(path)
    return sorted(paths)


def test_keeps_latest_ten_by_timestamp_not_modification_time(tmp_path):
    paths = make_logs(tmp_path / 'error', 13)
    os.utime(str(paths[0]), (2000000000, 2000000000))

    prune_error_logs(paths[0].parent)

    assert sorted(paths[0].parent.iterdir()) == paths[-10:]
    assert all((path / 'screenshot.png').exists() for path in paths[-10:])


@pytest.mark.parametrize('count', [0, 1, 10])
def test_does_not_remove_logs_within_limit(tmp_path, count):
    root = tmp_path / 'error'
    paths = make_logs(root, count)

    prune_error_logs(root)

    assert sorted(root.iterdir()) == paths


def test_ignores_unrelated_folders_and_timestamp_named_files(tmp_path):
    root = tmp_path / 'error'
    paths = make_logs(root, 11)
    for name in ('archive', '123', '1700000000000-backup'):
        (root / name).mkdir()
        (root / name / 'keep.txt').write_text('keep', encoding='utf-8')
    (root / '1600000000000').write_text('keep', encoding='utf-8')

    prune_error_logs(root)

    assert not paths[0].exists()
    assert all(path.exists() for path in paths[1:])
    assert (root / '1600000000000').read_text(encoding='utf-8') == 'keep'
    assert all((root / name / 'keep.txt').exists()
               for name in ('archive', '123', '1700000000000-backup'))


def test_does_not_follow_directory_symlinks(tmp_path):
    root = tmp_path / 'error'
    paths = make_logs(root, 11)
    target = tmp_path / 'outside'
    target.mkdir()
    (target / 'keep.txt').write_text('keep', encoding='utf-8')
    link = root / '1600000000000'
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip('Directory symlinks are unavailable')

    prune_error_logs(root)

    assert link.is_symlink()
    assert (target / 'keep.txt').exists()
    assert not paths[0].exists()
    assert all(path.exists() for path in paths[1:])


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction behavior')
@pytest.mark.parametrize('nested', [False, True])
def test_does_not_follow_windows_junctions(tmp_path, nested):
    root = tmp_path / 'error'
    paths = make_logs(root, 11)
    target = tmp_path / 'outside'
    target.mkdir()
    (target / 'keep.txt').write_text('keep', encoding='utf-8')
    link = paths[0] / 'linked' if nested else root / '1600000000000'
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        pytest.skip('Unable to create a directory junction')
    try:
        prune_error_logs(root)

        assert link.exists()
        assert (target / 'keep.txt').exists()
        assert paths[0].exists() == nested
        assert all(path.exists() for path in paths[1:])
    finally:
        os.rmdir(str(link))


def test_deletion_failure_is_logged_and_other_old_logs_are_removed(tmp_path, monkeypatch, caplog):
    root = tmp_path / 'error'
    paths = make_logs(root, 12)
    remove = shutil.rmtree

    def fail_one(path):
        if Path(path) == paths[0]:
            raise PermissionError('file is locked')
        remove(path)

    monkeypatch.setattr('module.base.error_log.shutil.rmtree', fail_one)
    with caplog.at_level(logging.WARNING, logger='alas'):
        prune_error_logs(root)

    assert paths[0].exists()
    assert not paths[1].exists()
    assert all(path.exists() for path in paths[-10:])
    assert 'file is locked' in caplog.text


def test_missing_directory_does_not_raise(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger='alas'):
        prune_error_logs(tmp_path / 'missing')

    assert caplog.records


@pytest.fixture
def error_saver(tmp_path, monkeypatch):
    # Exercise the real save method without loading emulator and OCR dependencies.
    source = Path(__file__).resolve().parents[2] / 'alas.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == 'AzurLaneAutoScript')
    method = next(node for node in cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == 'save_error_log')
    namespace = dict(os=os, re=__import__('re'), datetime=datetime,
                     prune_error_logs=prune_error_logs,
                     time=SimpleNamespace(time=lambda: 1700000000.999))
    logger = SimpleNamespace(log_file=str(tmp_path / 'log' / 'daily.txt'), warning=Mock())
    namespace['logger'] = logger
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    utils = ModuleType('module.base.utils')
    utils.save_image = lambda image, path: Path(path).write_bytes(b'screenshot')
    sensitive = ModuleType('module.handler.sensitive_info')
    sensitive.handle_sensitive_image = lambda image: image
    sensitive.handle_sensitive_logs = lambda lines: lines
    monkeypatch.setitem(sys.modules, 'module.base.utils', utils)
    monkeypatch.setitem(sys.modules, 'module.handler.sensitive_info', sensitive)
    monkeypatch.chdir(tmp_path)
    paths = make_logs(tmp_path / 'log' / 'error', 10)
    Path(logger.log_file).write_text('previous error\n', encoding='utf-8')
    app = SimpleNamespace(config=SimpleNamespace(Error_SaveError=True),
                          device=SimpleNamespace(screenshot_deque=[
                              dict(time=datetime(2026, 11, 2), image=object())]))
    return SimpleNamespace(save=lambda: namespace['save_error_log'](app),
                           app=app, paths=paths, utils=utils)


def test_successful_save_prunes_to_ten_complete_reports(error_saver):
    error_saver.save()

    folders = sorted(Path('log/error').iterdir())
    assert len(folders) == 10
    assert not error_saver.paths[0].exists()
    assert all((folder / 'log.txt').exists() for folder in folders)
    assert list(folders[-1].glob('*.png'))


def test_failed_save_preserves_existing_reports(error_saver):
    def fail_save(image, path):
        raise OSError('disk is full')

    error_saver.utils.save_image = fail_save
    with pytest.raises(OSError, match='disk is full'):
        error_saver.save()

    assert all((path / 'log.txt').exists() for path in error_saver.paths)


def test_disabled_error_saving_does_not_prune(error_saver):
    error_saver.app.config.Error_SaveError = False

    error_saver.save()

    assert sorted(Path('log/error').resolve().iterdir()) == error_saver.paths
