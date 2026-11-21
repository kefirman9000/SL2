"""Standard MIDI file export (format 1): one MIDI track per song track, drums on channel 10."""
import struct

DRUM_ROLES = {'kick', 'snare', 'clap', 'hat', 'ohat', 'ride', 'shaker', 'perc', 'rim', 'cowbell'}
PROGRAM = {'bass': 38, 'riff': 33, 'chords': 4, 'pad': 89, 'lead': 81, 'arp': 84, 'fx': 102}
TPB = 480


def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _chunk(kind, data):
    return kind + struct.pack('>I', len(data)) + data


def write_midi(song, path):
    tracks = []
    tempo = int(60_000_000 / song.bpm)
    meta = b'\x00\xff\x51\x03' + tempo.to_bytes(3, 'big') + b'\x00\xff\x58\x04\x04\x02\x18\x08'
    name = song.title.encode('utf-8', 'replace')[:120]
    meta = b'\x00\xff\x03' + _vlq(len(name)) + name + meta + b'\x00\xff\x2f\x00'
    tracks.append(meta)
    ch_next = 0
    for t in song.tracks:
        if t.role == 'fx':
            continue
        drum = t.role in DRUM_ROLES
        if drum:
            ch = 9
        else:
            ch = ch_next if ch_next != 9 else 10
            ch_next = ch + 1 if ch + 1 != 9 else 10
            ch = min(ch, 15)
        ev = []
        for n in song.notes_of(t.id):
            s = int(round(n.beat * TPB))
            e = max(s + 1, int(round((n.beat + n.length) * TPB)))
            v = max(1, min(127, int(n.velocity * 127)))
            p = max(0, min(127, int(round(n.pitch))))
            ev.append((s, 1, 0x90 | ch, p, v))
            ev.append((e, 0, 0x80 | ch, p, 0))
        ev.sort()
        nm = (t.params.get('label') or t.id).encode()[:60]
        data = b'\x00\xff\x03' + _vlq(len(nm)) + nm
        if not drum:
            data += b'\x00' + bytes([0xC0 | ch, PROGRAM.get(t.role, 0)])
        last = 0
        for tick, _, st, p, v in ev:
            data += _vlq(tick - last) + bytes([st, p, v])
            last = tick
        data += b'\x00\xff\x2f\x00'
        tracks.append(data)
    out = _chunk(b'MThd', struct.pack('>HHH', 1, len(tracks), TPB)) + b''.join(_chunk(b'MTrk', d) for d in tracks)
    with open(path, 'wb') as f:
        f.write(out)
    return path
