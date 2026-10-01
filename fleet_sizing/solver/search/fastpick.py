"""Exact fast replacement for alns._pick_team (a speed-up; results identical by construction).

_pick_team returns the team S minimising the key (cost, c, len(S), S) over every admissible team
inst.teams(i, mode). For a team S:  a'_k = max(avail_k + t_k, r_i),  s = max_k a'_k,  c = s + dd,
cost = tard_cost(c - d_i) + lam*crew*(sum_k (t_k - a'_k) + |S|*s + |S|*dd)   [integers inside].
Admissibility depends only on the multiset of member capacities (its "type"). Within a type and for a
fixed start value v = max a', the lexicographically smallest optimal team lies in
    R_v = U_class [ n_q smallest (h,k) with a' <= v ]  U  [ n_q smallest (h,k) with a' == v ],
h_k = t_k - a'_k (exchange argument: swapping a member outside R_v for a smaller (h,k) member of the
same class never raises cost or c and makes the sorted tuple smaller). We enumerate these few
candidates for every v and every type, score each with the ORIGINAL _append_eval, and take the minimum
of the ORIGINAL key. Hence the returned team is exactly the one the brute force returns.

Floating-point guard: the argument needs cost to separate teams whose X = emp + sync + |S|dd
differs by one second. In floating point, cost = T + (lam*crew)*X with T the tardiness score; when
T carries the cap penalty (about 1e9) and lam_team = 0 (lam_eff = 1e-8), a one-second step (4e-8) is
below the spacing of doubles near T (1.2e-7), so teams with slightly different X can tie and the
original key then picks the smallest tuple, which may lie outside the reduced set. The original
loop is therefore used whenever 4 * ulp(best candidate cost) exceeds the per-second step: the original
winner's cost never exceeds the best candidate's, so below that magnitude no absorption tie can involve
it. (Testing every candidate instead gives the same results but is about 5x slower on the hardest instance.)"""
import itertools
import math
from baselines import _append_eval
from core import lam_eff

BRUTE_MAX = 48          # small team lists: use the original loop unchanged


def _types(inst, i, mode):
    cache = inst.__dict__.setdefault('_fastpick_types', {})   # per instance object (never shared)
    key = (i, mode)
    tp = cache.get(key)
    if tp is None:
        types = {}
        for S in inst.teams(i, mode):
            t = tuple(sorted(inst.cap[k] for k in S))
            types[t] = True
        out = []
        for t in types:
            cnt = {}
            for q in t:
                cnt[q] = cnt.get(q, 0) + 1
            out.append(cnt)
        members = {}
        for k in range(inst.K):
            members.setdefault(inst.cap[k], []).append(k)
        tp = (out, members)
        cache[key] = tp
    return tp


def _brute(inst, i, mode_eff, lam_team, avail, last):
    best = None
    for S in inst.teams(i, mode_eff):
        cost, s, c, _ = _append_eval(inst, lam_team, avail, last, i, S)
        key = (cost, c, len(S), S)
        if best is None or key < best[0]:
            best = (key, S, c)
    return best[1], best[2]


def pick_team(inst, i, mode_eff, lam_team, avail, last):
    teams = inst.teams(i, mode_eff)
    if len(teams) <= BRUTE_MAX:
        return _brute(inst, i, mode_eff, lam_team, avail, last)
    types, members = _types(inst, i, mode_eff)
    r = inst.rel[i]
    tE0, tE = inst.tE0, inst.tE
    ap, h = {}, {}
    for q in {q for cnt in types for q in cnt}:
        for k in members[q]:
            t = tE0[k][i] if last[k] < 0 else tE[last[k]][i]
            a = avail[k] + t
            a2 = a if a > r else r
            ap[k] = a2
            h[k] = t - a2
    cands = set()
    for cnt in types:
        cls = sorted(cnt)
        veh = sorted((k for q in cls for k in members[q]), key=lambda k: ap[k])
        top = {q: [] for q in cls}            # n_q smallest (h,k) with a' <= v, per class
        p = 0
        while p < len(veh):
            v = ap[veh[p]]
            E = {q: [] for q in cls}
            while p < len(veh) and ap[veh[p]] == v:
                k = veh[p]
                q = inst.cap[k]
                E[q].append((h[k], k))
                top[q].append((h[k], k))
                p += 1
            pools = []
            for q in cls:
                top[q].sort()
                del top[q][cnt[q]:]
                E[q].sort()
                pool = sorted({k for _, k in top[q]} | {k for _, k in E[q][:cnt[q]]})
                if len(pool) < cnt[q]:
                    pools = None
                    break
                pools.append(list(itertools.combinations(pool, cnt[q])))
            if pools is None:
                continue
            for parts in itertools.product(*pools):
                S = tuple(sorted(k for part in parts for k in part))
                if any(ap[k] == v for k in S):
                    cands.add(S)
    best = None
    for S in cands:
        cost, s, c, _ = _append_eval(inst, lam_team, avail, last, i, S)
        key = (cost, c, len(S), S)
        if best is None or key < best[0]:
            best = (key, S, c)
    # The original winner W has cost(W) <= best cost. If one second of X is resolvable at that magnitude,
    # no team can tie with W by absorption, so W is the (sum h, tuple)-minimum of its (type, v) group and
    # lies in the candidate set; otherwise fall back to the original loop.
    if 4 * math.ulp(best[0][0]) > lam_eff(lam_team) * inst.crew:
        return _brute(inst, i, mode_eff, lam_team, avail, last)
    return best[1], best[2]
