import logging
import os
import re
import shutil
import stat
from pathlib import Path


logger = logging.getLogger('alas')
REPARSE_POINT = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


def _is_link(path):
    metadata = path.lstat()
    return (stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, 'st_file_attributes', 0) & REPARSE_POINT)


def prune_error_logs(folder, keep=10):
    """Keep the newest timestamp-named error directories; log cleanup failures."""
    if keep < 1:
        raise ValueError('At least one error log must be retained')
    try:
        root = Path(folder).resolve(strict=True)
        folders = [path for path in root.iterdir()
                   if re.fullmatch(r'[0-9]{13}', path.name)
                   and not _is_link(path) and path.is_dir()]
        folders.sort(key=lambda path: int(path.name), reverse=True)
    except OSError as exc:
        logger.warning('Unable to list error logs for cleanup: %s', exc)
        return

    for path in folders[keep:]:
        try:
            # Resolve and check the deletion target before removing it.
            if _is_link(path) or path.resolve(strict=True).parent != root:
                raise OSError('Error log directory is outside the error folder')
            # Python 3.7 rmtree may follow Windows junctions inside a directory.
            for parent, directories, _ in os.walk(str(path), followlinks=False):
                if any(_is_link(Path(parent) / name) for name in directories):
                    raise OSError('Error log directory contains a directory link')
            shutil.rmtree(str(path))
        except OSError as exc:
            logger.warning('Unable to remove old error log %s: %s', path, exc)
