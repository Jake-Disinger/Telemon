"""CPC-style rotated PCA must recover NAO and PNA from a realistic mix of modes."""
import datetime as dt, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tele import indices as ix
from tele.grid import LAT, LON
import build_climatology as bc

L2, N2 = np.meshgrid(LAT, LON, indexing="ij")
g = lambda la, lo, rla=10, rlo=25: np.exp(-((L2 - la) / rla) ** 2 - ((((N2 - lo + 180) % 360) - 180) / rlo) ** 2)


def synthetic(nyears=30, seed=3):
    rng = np.random.default_rng(seed)
    months, years, fields, amps = [], [], [], {"nao": [], "pna": []}
    for y in range(1991, 1991 + nyears):
        for m in range(1, 13):
            shift = 6 * np.sin(2 * np.pi * (m - 7) / 12) * -1        # NAO centers shift north in summer
            nao = -70 * g(65 + shift * 0.5, 335) + 55 * g(40 + shift, 330)
            pna = 45 * g(20, 200, 8, 20) - 80 * g(45, 195) + 60 * g(55, 245) - 50 * g(32, 275, 8, 20)
            ao = np.where(L2 > 65, -60.0, 0) + 25 * np.exp(-((L2 - 45) / 8) ** 2)
            enso = 40 * np.exp(-((L2 - 22) / 7) ** 2)
            a_nao, a_pna, a_ao, a_en = rng.normal(size=4)
            trend = (y - 2005) * 0.9
            f = a_nao * nao + a_pna * pna + a_ao * ao * 0.8 + a_en * enso + trend + rng.normal(0, 18, L2.shape)
            f[LAT < 0] = 0
            fields.append(f); months.append(m); years.append(y)
            amps["nao"].append(a_nao); amps["pna"].append(a_pna)
    return dict(mon_a500=np.array(fields), mon_month=np.array(months), mon_year=np.array(years)), amps


def test_rpca_recovers_nao_and_pna():
    h, amps = synthetic()
    rp = bc.rpca_climo(h)
    nao_idx, pna_idx = [], []
    for i in range(len(h["mon_month"])):
        k = h["mon_month"][i] - 1
        nao_idx.append(ix.rpca_project(h["mon_a500"][i], rp["sigma"][k], rp["nao"][k], rp["nao_sd"][k]))
        pna_idx.append(ix.rpca_project(h["mon_a500"][i], rp["sigma"][k], rp["pna"][k], rp["pna_sd"][k]))
    r_nao = np.corrcoef(nao_idx, amps["nao"])[0, 1]
    r_pna = np.corrcoef(pna_idx, amps["pna"])[0, 1]
    assert r_nao > 0.8, r_nao          # sign: positive amplitude = low over Iceland = +NAO
    assert r_pna > 0.9, r_pna
    assert 0.8 < np.std(nao_idx) < 1.25 and abs(np.mean(nao_idx)) < 0.2
    # the old Atlantic-sector EOF (the method that failed on the real data) does much worse here
    old_p, _ = ix.eof_pattern(h["mon_a500"], ix.NAO_DOMAIN)
    r_old = abs(np.corrcoef(ix.project(h["mon_a500"], old_p), amps["nao"])[0, 1])
    assert r_nao > r_old


def test_month_blending_is_continuous():
    from tele.climo import Climatology
    c = Climatology.__new__(Climatology)
    w_end = dict(c.month_weights(dt.datetime(2026, 1, 31)))
    w_start = dict(c.month_weights(dt.datetime(2026, 2, 1)))
    assert abs(w_end[0] - w_start[0]) < 0.06 and abs(w_end[1] - w_start[1]) < 0.06
    assert dict(c.month_weights(dt.datetime(2026, 1, 16)))[0] > 0.95
