"""Exact fast replacement for Sched.candidates (same teams, positions, screen values and sort).
Per call, the S-independent quantities of (vehicle k, position p) -- approach time, arrival, next task,
old/new approach to it, and the position filter -- are computed once and reused across teams.
Every floating-point operation of screen() is performed in the original order on the same values."""
from bisect import bisect_left
from core import tard_cost


def candidates(self, i, mode, cfg):
    teams, veh = self.teams_for(i, mode, cfg['Kc'], cfg.get('parity', False))
    inst = self.inst
    tE0, tE = inst.tE0, inst.tE
    r, due_i = inst.rel[i], inst.due[i]
    win = cfg['win_s']
    lo, hi = r - win, due_i + win
    snap_avail, snap_last = self.snap_avail, self.snap_last
    seqpos, seqs, start = self.seqpos, self.seqs, self.start
    wc = self.lam * inst.crew
    ct = inst.crew_team
    Di, dli = inst.D[i], inst.dl[i]
    cache = {}

    def info(k, p):
        key = k * 100003 + p
        v = cache.get(key)
        if v is None:
            prev = snap_last[p][k]
            t = tE0[k][i] if prev < 0 else tE[prev][i]
            av = snap_avail[p][k]
            sp = seqpos[k]
            q = bisect_left(sp, p)
            j = seqs[k][q] if q < len(sp) else -1
            if j >= 0:
                old_in = tE0[k][j] if prev < 0 else tE[prev][j]
                v = (t, av + t, j, old_in, tE[i][j], not (av > hi) and not (start[j] < lo))
            else:
                v = (t, av + t, -1, 0, 0, not (av > hi))
            cache[key] = v
        return v

    out = []
    team, starts, arrive, comp = self.team, self.start, self.arrive, self.comp
    rel, due = inst.rel, inst.due
    for S in teams:
        P = {0}
        for k in S:
            for x in seqpos[k]:
                P.add(x + 1)
        P = sorted(P)
        keep = []
        for p in P:
            ok = True
            for k in S:
                if not info(k, p)[5]:
                    ok = False
                    break
            if ok:
                keep.append(p)
        pos = keep if keep else P
        nS = len(S)
        dd = Di + (dli if nS > 1 else 0)
        for p in pos:
            # ---- screen(i, S, p), same operations in the same order ----
            s = r
            arr = []
            emp = 0
            infos = []
            for k in S:
                v = info(k, p)
                infos.append(v)
                emp += v[0]
                a = v[1]
                arr.append(a)
                if a > s:
                    s = a
            w = 0
            for a in arr:
                w += s - (a if a > r else r)
            c = s + dd
            if ct is None:
                cost = tard_cost(inst, c - due_i) + wc * (emp + w + nS * dd)
            else:
                cost = (tard_cost(inst, c - due_i) + wc * (emp + w)
                        + self.lam * ct[nS] * dd)
            nexts = {}
            for k, v in zip(S, infos):
                j = v[2]
                if j < 0:
                    continue
                new_in = v[4]
                cost += wc * (new_in - v[3])
                nexts.setdefault(j, []).append((k, c + new_in))
            for j, lst in nexts.items():
                S_j = team[j]
                old_s = starts[j]
                new_a = dict(lst)
                new_s = old_s
                for _, a in lst:
                    if a > new_s:
                        new_s = a
                ds = new_s - old_s
                rj = rel[j]
                dw = 0
                for k, a_old in zip(S_j, arrive[j]):
                    a_new = new_a.get(k, a_old)
                    dw += (new_s - (a_new if a_new > rj else rj)) - (old_s - (a_old if a_old > rj else rj))
                cj = comp[j]
                dj = due[j]
                dt = tard_cost(inst, cj + ds - dj) - tard_cost(inst, cj - dj)
                cost += dt + wc * dw
            out.append((cost, p, S))
    out.sort(key=lambda x: (x[0], x[1], x[2]))
    return out, veh
