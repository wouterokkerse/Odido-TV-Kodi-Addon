"""Resolve live-buffer versus completed-programme playback at tune time."""
from .api import OdidoError


def target(params, default, now):
    kind, identifier = params['kind'], params['id']
    channel = params.get('channel', '')
    if kind == 'program' and ('programme_start' in params or 'programme_end' in params):
        try:
            start, end = int(params['programme_start']), int(params['programme_end'])
        except (KeyError, TypeError, ValueError):
            raise OdidoError('INVALID_PROGRAMME_TIMES') from None
        if start <= 0 or end <= start or not channel:
            raise OdidoError('INVALID_PROGRAMME_TIMES')
        if now < start:
            raise OdidoError('PROGRAMME_NOT_STARTED')
        if now < end:
            # Use the same live-stream contract as normal channel playback.
            # The manifest, not this timestamp, defines the rewindable range.
            return 'channel', channel, '', 'begin'
        if params.get('replay', '1') == '0':
            raise OdidoError('REPLAY_UNAVAILABLE')
    if kind == 'channel':
        mode = params.get('start', default)
        if mode not in ('live', 'begin'):
            raise OdidoError('INVALID_LIVE_START')
        return kind, identifier, channel, mode
    return kind, identifier, channel, None
