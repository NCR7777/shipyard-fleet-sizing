"""Run the study scripts off Windows without editing them.

fleet_scan_studies.run, greedy_level, decision_strength and exact_run call psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS),
a Windows-only constant; exact_run also calls cpu_affinity, which macOS lacks. On Windows this module does nothing.
Elsewhere it maps the constant to POSIX niceness 10 and makes cpu_affinity a no-op where it is missing.
Imported by confirm_run.py; for exact_run.py (whose worker processes import psutil afresh) put supplementary/compat_site on
PYTHONPATH so that every process loads it through sitecustomize.
"""
import psutil

if not hasattr(psutil, 'BELOW_NORMAL_PRIORITY_CLASS'):
    psutil.BELOW_NORMAL_PRIORITY_CLASS = 10
if not hasattr(psutil.Process, 'cpu_affinity'):
    psutil.Process.cpu_affinity = lambda self, cpus=None: list(range(psutil.cpu_count())) if cpus is None else None
