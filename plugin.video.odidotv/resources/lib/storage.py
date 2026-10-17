"""Small atomic stores; no Kodi imports so provider behavior can be tested."""
import json
import os
import tempfile


def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return default


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SavedLists:
    def __init__(self, profile):
        self.path = os.path.join(profile, 'saved.json')

    def items(self, name):
        return read_json(self.path, {}).get(name, [])

    def update(self, name, item, remove=False):
        if name not in ('favorites', 'later'):
            raise ValueError('Unknown list')
        data = read_json(self.path, {})
        key = (item['kind'], str(item['id']))
        rows = [row for row in data.get(name, [])
                if (row['kind'], str(row['id'])) != key]
        if not remove:
            rows.append(item)
        data[name] = rows
        write_json(self.path, data)
