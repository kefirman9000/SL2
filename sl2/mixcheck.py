"""The mix check: after every render, the numbers a mastering engineer looks at first, each with a verdict.

    true peak        inter-sample peak after the limiter (should be at or under -1 dBTP)
    loudness         integrated LUFS against the genre's target
    dynamics         PLR (true peak minus loudness): below ~6 dB a master sounds squashed
    clipping         samples at full scale
    DC offset        a constant shift that wastes headroom
    mono             left/right correlation overall and below 120 Hz (the low end should be close to mono)
    lead             is the lead buried under the chords? (the lead against the music where the lead plays)
"""
import numpy as np
from scipy import signal

from .analyze import lufs

SR = 44100


def check(master, rep, mix_info=None, stems=None):
    """-> list of dicts(name, value, ok, note)"""
    out = []
    x = master.astype(np.float64)
    tp = rep.get('true_peak_db')
    L = rep.get('lufs')
    target = rep.get('target_lufs')
    out.append(dict(name='True peak', value=f'{tp} dBTP', ok=tp is not None and tp <= -0.9,
                    note='safe for MP3 / streaming' if tp is not None and tp <= -0.9 else 'over -1 dBTP: may distort when encoded'))
    if L is not None and target is not None:
        out.append(dict(name='Loudness', value=f'{L} LUFS (target {target})', ok=abs(L - target) <= 1.0,
                        note='on target' if abs(L - target) <= 1.0 else 'off target'))
    if tp is not None and L is not None:
        plr = round(tp - L, 1)
        out.append(dict(name='Dynamics (PLR)', value=f'{plr} dB', ok=plr >= 6.0,
                        note='punchy' if plr >= 9 else 'dense but fine' if plr >= 6 else 'squashed - try loudness "streaming"'))
    clips = int((np.abs(x) >= 0.999).sum())
    out.append(dict(name='Clipping', value=f'{clips} samples', ok=clips == 0, note='clean' if clips == 0 else 'clipped samples'))
    dc = float(np.abs(x.mean(1)).max())
    out.append(dict(name='DC offset', value=f'{20 * np.log10(dc + 1e-12):.0f} dB', ok=dc < 1e-3, note='none' if dc < 1e-3 else 'present'))
    if x.shape[1] > SR:
        c = float(np.corrcoef(x[0], x[1])[0, 1])
        lo = signal.sosfilt(signal.butter(4, 120 / (SR / 2), 'low', output='sos'), x, axis=1)
        cl = float(np.corrcoef(lo[0], lo[1])[0, 1]) if lo.std() > 1e-6 else 1.0
        out.append(dict(name='Mono compatibility', value=f'{c:.2f} (low end {cl:.2f})', ok=c > 0.2 and cl > 0.9,
                        note='folds to mono cleanly' if c > 0.2 and cl > 0.9 else 'parts may cancel in mono'))
    if stems and 'lead' in stems and 'music' in stems:
        lead, music = stems['lead'].mean(0), stems['music'].mean(0)
        n = min(len(lead), len(music))
        env = np.sqrt(np.convolve(lead[:n] ** 2, np.ones(2205) / 2205, 'same'))
        on = env > np.percentile(env, 70)
        if on.sum() > SR:
            band = signal.butter(4, [800 / (SR / 2), 5000 / (SR / 2)], 'band', output='sos')
            a = signal.sosfilt(band, lead[:n])[on]
            b = signal.sosfilt(band, music[:n])[on]
            d = 10 * np.log10((a ** 2).mean() / max((b ** 2).mean(), 1e-12))
            out.append(dict(name='Lead', value=f'{d:+.1f} dB over the music (0.8-5 kHz)', ok=d > -3.0,
                            note='sits on top' if d > 0 else 'in the mix' if d > -3 else 'buried - raise it or lower the chords'))
    for k, v in (mix_info or {}).items():
        out.append(dict(name=k.replace('_', ' ').capitalize(), value=v, ok=True, note=''))
    for i in out:
        i['ok'] = bool(i['ok'])
    return out


def summary(items):
    bad = [i for i in items if not i['ok']]
    return 'Mix check: all clear.' if not bad else 'Mix check: ' + '; '.join(f"{i['name'].lower()} {i['value']} ({i['note']})" for i in bad) + '.'
