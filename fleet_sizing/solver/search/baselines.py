"""Baseline methods: constructive rules that dispatch tasks one at a time in release order and only append to the
end of each vehicle's route.

  G-Flex  : greedy_append(mode='flex')   each task takes the single vehicle or minimal team with the smallest
                                         objective increment (flexible coupling)
  R-Jiang : greedy_append(mode='rigid')  couples only when overweight (the rule of Jiang 2021), otherwise as G-Flex
  H-First : heavy_first()                if a single vehicle can carry the task, the idle one with the largest
                                         capacity; if none is idle, the capable vehicle that arrives earliest;
                                         overweight tasks use the minimal team that starts earliest
Task processing order: release time, due time, task index. The objective increment is the same as in the ALNS:
  tardiness + λ·crew·(empty travel + synchronisation wait + team size × (δ·[coupled] + load, travel, unload)).
"Idle" means that the vehicle has finished its previous task by the release time of the task (avail_k ≤ r_i).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'common'))
from core import evaluate, lam_eff, tard_cost   # noqa: E402


def _task_order(inst):
    return sorted(range(inst.n), key=lambda i: (inst.rel[i], inst.due[i], i))


def _append_eval(inst, lam, avail, last, i, S):
    r = inst.rel[i]
    s = r
    arr = []
    emp = 0
    for k in S:
        t = inst.tE0[k][i] if last[k] < 0 else inst.tE[last[k]][i]
        a = avail[k] + t
        emp += t
        arr.append(a)
        if a > s:
            s = a
    sync = sum(s - (a if a > r else r) for a in arr)
    dd = inst.D[i] + (inst.dl[i] if len(S) > 1 else 0)
    c = s + dd
    lam = lam_eff(lam)
    if inst.crew_team is None:
        cost = tard_cost(inst, c - inst.due[i]) + lam * inst.crew * (emp + sync + len(S) * dd)
    else:
        cost = tard_cost(inst, c - inst.due[i]) + lam * (inst.crew * (emp + sync) + inst.crew_team[len(S)] * dd)
    return cost, s, c, arr


def greedy_append(inst, lam, mode='flex'):
    avail = [0] * inst.K
    last = [-1] * inst.K
    order, team = [], {}
    for i in _task_order(inst):
        best = None
        for S in inst.teams(i, mode):
            cost, s, c, _ = _append_eval(inst, lam, avail, last, i, S)
            key = (cost, c, len(S), S)
            if best is None or key < best[0]:
                best = (key, S, c)
        _, S, c = best
        for k in S:
            avail[k] = c
            last[k] = i
        order.append(i)
        team[i] = S
    ev = evaluate(inst, order, team, lam)
    return dict(order=order, team=team, obj=ev['obj'], ev=ev)


def heavy_first(inst, lam):
    avail = [0] * inst.K
    last = [-1] * inst.K
    order, team = [], {}
    for i in _task_order(inst):
        m, r = inst.mass[i], inst.rel[i]
        capable = [k for k in range(inst.K) if inst.cap[k] >= m]
        if capable:
            arr = {k: avail[k] + (inst.tE0[k][i] if last[k] < 0 else inst.tE[last[k]][i]) for k in capable}
            idle = [k for k in capable if avail[k] <= r]
            if idle:
                k = max(idle, key=lambda k: (inst.cap[k], -arr[k], -k))
            else:
                k = min(capable, key=lambda k: (arr[k], -inst.cap[k], k))
            S = (k,)
        else:
            best = None
            for S2 in inst.teams(i, 'rigid'):
                cost, s, c, _ = _append_eval(inst, lam, avail, last, i, S2)
                key = (s, cost, len(S2), S2)
                if best is None or key < best[0]:
                    best = (key, S2)
            S = best[1]
        _, s, c, _ = _append_eval(inst, lam, avail, last, i, S)
        for k in S:
            avail[k] = c
            last[k] = i
        order.append(i)
        team[i] = S
    ev = evaluate(inst, order, team, lam)
    return dict(order=order, team=team, obj=ev['obj'], ev=ev)
