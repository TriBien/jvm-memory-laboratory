#!/usr/bin/env python3
import re
import sys
from collections import defaultdict

PREFIX = re.compile(
    r'^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{4}\]'
    r'\[([0-9.]+)s\]\[(\d+)\]\[(\w+)\s*\]\[([^\]]+)\] (.*)$'
)
SIZE_RE = re.compile(r'^(\d+)([KMG]?)$')
G1_SUMMARY = re.compile(
    r'^GC\((\d+)\) Pause (Young|Mixed|Full|Concurrent) .*? '
    r'(\d+[KMG]?)->(\d+[KMG]?)\((\d+[KMG]?)\) ([0-9.]+)ms$'
)
ZGC_SUMMARY = re.compile(
    r'^GC\((\d+)\) (Minor|Major) Collection \(([^)]+)\) '
    r'(\d+[KMG]?)\((\d+%)\)->(\d+[KMG]?)\((\d+%)\) ([0-9.]+)s$'
)
ZGC_PAUSE = re.compile(
    r'^GC\(\d+\) [Yo]: Pause \w+(?: \(Major\))? ([0-9.]+)ms$'
)
G1_REGION = re.compile(
    r'^GC\(\d+\) (Eden|Survivor|Old|Humongous) regions: (\d+)->(\d+)(?:\((\d+)\))?'
)
ZGC_STALL = re.compile(r'^GC\(\d+\) [Yo]: Allocation Stalls:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$')


def parse_size(s):
    if not s:
        return None
    m = SIZE_RE.match(s)
    if not m:
        return None
    n = int(m.group(1))
    u = m.group(2)
    if u == 'K':
        return n * 1024
    if u == 'M':
        return n * 1024 * 1024
    if u == 'G':
        return n * 1024 ** 3
    return n


def human(n):
    if n is None:
        return '?'
    x = float(n)
    for unit in ('B', 'K', 'M', 'G', 'T'):
        if x < 1024 or unit == 'T':
            if unit == 'B' or abs(x - round(x)) < 0.05:
                return f'{int(round(x))}{unit}'
            return f'{x:.1f}{unit}'
        x /= 1024
    return f'{x:.0f}T'


def quantiles(data, qs=(0.50, 0.95, 0.99)):
    d = sorted(data)
    out = []
    for q in qs:
        if not d:
            out.append(0.0)
            continue
        k = (len(d) - 1) * q
        lo = int(k)
        frac = k - lo
        if frac and lo + 1 < len(d):
            out.append(d[lo] * (1 - frac) + d[lo + 1] * frac)
        else:
            out.append(d[lo])
    return out


class Analysis:
    def __init__(self, path):
        self.path = path
        self.collector = None
        self.version = None
        self.heap_min = self.heap_init = self.heap_max = None
        self.region_size = None
        self.parallel_workers = self.concurrent_workers = None
        self.events = []
        self.stw = []
        self.gc_type_counts = defaultdict(int)
        self.zgc_stalls = 0
        self.young_region_path = defaultdict(list)
        self.first_before = None
        self.exit_used = self.exit_capacity = None
        self.unparsed = 0
        self.total_gc_time_ms = 0.0
        self.gc_time_ms_by_gc = defaultdict(float)
        self.zgc_phase_time_ms = defaultdict(float)

    def record(self, uptime, level, tags, msg):
        tags = tags.strip()
        if tags == 'gc,init':
            if self.version is None:
                m = re.search(r'Version: (.+?)(?: \(release\))?$', msg)
                if m:
                    self.version = m.group(1)
            m = re.search(r'Heap Region Size: (\d+[KMG])', msg)
            if m:
                self.region_size = parse_size(m.group(1))
            m = re.search(r'(?:Heap )?(Min|Initial|Max|Soft Max) Capacity: (\d+[KMG])', msg)
            if m:
                v = parse_size(m.group(2))
                if m.group(1) == 'Min':
                    self.heap_min = v
                elif m.group(1) == 'Initial':
                    self.heap_init = v
                elif m.group(1) == 'Max':
                    self.heap_max = v
            m = re.search(r'(?:Parallel Workers|Concurrent Workers|GC Workers for (?:Young|Old) Generation|GC Workers Max): (\d+)', msg)
            if m:
                p = int(m.group(1))
                if self.parallel_workers is None or p > self.parallel_workers:
                    self.parallel_workers = p
            m = re.search(r'Concurrent Workers: (\d+)', msg)
            if m:
                self.concurrent_workers = int(m.group(1))
            return
        if tags == 'gc' and self.collector is None:
            if 'Using G1' in msg:
                self.collector = 'G1'
            elif 'Z Garbage Collector' in msg:
                self.collector = 'ZGC'
        if tags == 'gc':
            m = G1_SUMMARY.match(msg)
            if m:
                before = parse_size(m.group(3))
                after = parse_size(m.group(4))
                cap = parse_size(m.group(5))
                pause_ms = float(m.group(6))
                self.events.append(dict(t=uptime, gc_type=m.group(2), before=before,
                                        after=after, capacity=cap, pause_ms=pause_ms))
                self.stw.append(pause_ms)
                self.gc_type_counts[m.group(2)] += 1
                return
            m = ZGC_SUMMARY.match(msg)
            if m:
                before = parse_size(m.group(4))
                after = parse_size(m.group(6))
                self.events.append(dict(t=uptime, gc_type=m.group(2), before=before,
                                        after=after, capacity=self.heap_max,
                                        pause_ms=0.0, wall_s=float(m.group(8)), cause=m.group(3)))
                self.gc_type_counts[m.group(2)] += 1
                return
        if tags == 'gc,phases':
            if self.collector == 'ZGC' and ' Pause ' in msg:
                pm = re.search(r' ([0-9.]+)ms$', msg)
                if pm:
                    self.stw.append(float(pm.group(1)))
            return
        if tags == 'gc,heap' and self.collector == 'G1':
            m = G1_REGION.match(msg)
            if m:
                third = int(m.group(4)) if m.group(4) else None
                self.young_region_path[m.group(1)].append((uptime, int(m.group(2)), int(m.group(3)), third))
            return
        if tags == 'gc,alloc' and self.collector == 'ZGC':
            m = ZGC_STALL.match(msg)
            if m:
                self.zgc_stalls += sum(int(v) for v in m.groups())
            return
        if tags == 'gc,exit':
            if 'garbage-first heap' in msg or 'ZHeap' in msg:
                m = re.search(r'used (\d+[KMG])', msg)
                if m:
                    self.exit_used = parse_size(m.group(1))
                m = re.search(r'(?:capacity|committed) (\d+[KMG])', msg)
                if m and self.exit_capacity is None:
                    self.exit_capacity = parse_size(m.group(1))

    def run(self):
        with open(self.path, 'r', errors='replace') as f:
            for line in f:
                line = line.rstrip('\n')
                m = PREFIX.match(line)
                if not m:
                    self.unparsed += 1
                    continue
                try:
                    uptime = float(m.group(1))
                except ValueError:
                    uptime = 0.0
                self.record(uptime, m.group(3), m.group(4), m.group(5))
        self.finish()

    def finish(self):
        self.total_gc_time_ms = sum(self.stw)
        for i, e in enumerate(self.events):
            e['gc_id'] = i
            if self.first_before is None:
                self.first_before = e['before']
        self.collection_wall_ms = sum(e.get('wall_s', 0.0) * 1000.0 for e in self.events)
        self.runtime = (self.events[-1]['t'] - self.events[0]['t']) if len(self.events) > 1 else 0.0
        self.pauses = self.stw
        self.p50, self.p95, self.p99 = quantiles(self.pauses)
        self.gc_overhead_pct = (sum(self.pauses) / 1000.0 / self.runtime * 100.0) if self.runtime > 0 else 0.0
        total_stw_ms = sum(self.pauses)

        self.total_alloc = 0
        self.total_reclaimed = 0
        self.alloc_rates = []
        prev_after = 0
        prev_t = self.events[0]['t'] if self.events else 0.0
        for e in self.events:
            alloc = e['before'] - prev_after
            dt = e['t'] - prev_t
            if alloc > 0:
                self.total_alloc += alloc
                if dt > 0:
                    self.alloc_rates.append(alloc / dt)
            self.total_reclaimed += (e['before'] - e['after'])
            prev_after = e['after']
            prev_t = e['t']
        self.avg_alloc_rate = (sum(self.alloc_rates) / len(self.alloc_rates)) if self.alloc_rates else 0.0
        atop = self.total_alloc / self.runtime if self.runtime > 0 else 0.0
        self.throughput_rate = atop
        self.peak_used = max((e['before'] for e in self.events), default=0)
        self.avg_after = sum(e['after'] for e in self.events) / len(self.events) if self.events else 0

        self.old_regions_before = self.old_regions_after = None
        self.humongous_regions = 0
        for kind, rows in self.young_region_path.items():
            first = rows[0]
            last = rows[-1]
            if kind == 'Old':
                self.old_regions_before = first[1]
                self.old_regions_after = last[2]
            if kind == 'Humongous':
                for r in rows:
                    self.humongous_regions = max(self.humongous_regions, r[2] or 0)
        self.promotion_bytes = 0
        if self.collector == 'G1' and self.old_regions_before is not None and self.region_size:
            self.promotion_bytes = (self.old_regions_after - self.old_regions_before) * self.region_size

        self.risk_flags = []
        if self.gc_overhead_pct > 10:
            self.risk_flags.append(f'GC overhead high ({self.gc_overhead_pct:.1f}% of runtime)')
        m = max(self.pauses) if self.pauses else 0.0
        if m > 100:
            self.risk_flags.append(f'Pause spike >100ms ({m:.1f}ms)')
        if self.gc_type_counts.get('Full', 0):
            self.risk_flags.append('Full GCs present')
        if self.humongous_regions:
            self.risk_flags.append(f'Humongous regions detected ({self.humongous_regions})')
        if self.zgc_stalls:
            self.risk_flags.append(f'ZGC allocation stalls: {self.zgc_stalls}')


def format_section(title, rows):
    width = max(len(k) for k, _ in rows) + 2
    out = [title, '-' * len(title)]
    for k, v in rows:
        out.append(f'  {k:<{width}}{v}')
    return '\n'.join(out)


def print_report(a):
    print(f'GC Log Analysis: {a.path}')
    print('=' * len(a.path) + '==================')
    config = []
    config.append(('JVM version', a.version or '?'))
    config.append(('Collector', a.collector or '?'))
    config.append(('Heap min/init/max', f'{human(a.heap_min)} / {human(a.heap_init)} / {human(a.heap_max)}'))
    if a.region_size:
        config.append(('Region size', human(a.region_size)))
    if a.parallel_workers:
        cw = a.concurrent_workers if a.concurrent_workers is not None else '-'
        config.append(('Workers (parallel/concurrent)', f'{a.parallel_workers} / {cw}'))
    config.append(('Runtime (first..last event)', f'{a.events[0]["t"]:.3f}s -> {a.events[-1]["t"]:.3f}s ({a.runtime:.3f}s)' if len(a.events) > 1 else '?'))
    print(format_section('Configuration', config))

    counts = ' | '.join(f'{k}: {v}' for k, v in sorted(a.gc_type_counts.items())) or 'none'
    gc_rows = [
        ('Total collections', len(a.events)),
        ('By type', counts),
        ('Total GC time (STW)', f'{a.total_gc_time_ms:.1f} ms'),
        ('Collections wall time', f'{a.collection_wall_ms:.1f} ms' if a.collection_wall_ms else '-'),
        ('Pauses (STW)', f'{len(a.pauses)}'),
        ('STW total', f'{sum(a.pauses):.1f} ms'),
        ('STW mean', f'{sum(a.pauses) / len(a.pauses):.2f} ms' if a.pauses else '?'),
        ('STW min / max', f'{min(a.pauses):.2f} / {max(a.pauses):.2f} ms' if a.pauses else '?'),
        ('STW p50 / p95 / p99', f'{a.p50:.2f} / {a.p95:.2f} / {a.p99:.2f} ms'),
        ('GC frequency', f'{a.runtime / len(a.events) * 1000:.0f} ms between collections' if a.events else '?'),
        ('GC overhead', f'{a.gc_overhead_pct:.1f}% of runtime'),
    ]
    print()
    print(format_section('Collections', gc_rows))

    mem = [
        ('Peak used before GC', human(a.peak_used)),
        ('Average used after GC', human(a.avg_after)),
        ('Total reclaimed', human(a.total_reclaimed)),
        ('Total allocated (est.)', human(a.total_alloc)),
        ('Avg allocation rate', f'{a.avg_alloc_rate / 1024 ** 3:.2f} GB/s'),
        ('Allocation throughput over runtime', f'{a.throughput_rate / 1024 ** 3:.2f} GB/s'),
    ]
    if a.collector == 'G1':
        mem.append(('Promotion to old', f'{human(a.promotion_bytes)} (old regions {a.old_regions_before}->{a.old_regions_after})'))
        mem.append(('Humongous regions', f'{a.humongous_regions}'))
    if a.collector == 'ZGC':
        mem.append(('Allocation stalls', f'{a.zgc_stalls}'))
    if a.exit_used is not None:
        mem.append(('Heap used at exit', f'{human(a.exit_used)} / {human(a.exit_capacity or a.heap_max)}'))
    print()
    print(format_section('Memory / allocation', mem))

    worst = sorted(a.events, key=lambda e: e['pause_ms'], reverse=True)[:5]
    if worst and a.collector == 'G1':
        rows = []
        for e in worst:
            rows.append(('GC(%d) %s @%.3fs' % (e['gc_id'], e['gc_type'], e['t']),
                         f'{human(e["before"])}->{human(e["after"])} in {e["pause_ms"]:.2f} ms'))
        print()
        print(format_section('Worst pauses', rows))

    if a.risk_flags:
        print()
        print('Flags')
        print('-----')
        for flag in a.risk_flags:
            print(f'  - {flag}')
        print()
    else:
        print()


def compare(reports):
    header = ['Collector', 'Runtime(s)', 'GCs', 'STW(ms)', 'mean(ms)', 'max(ms)', 'p95(ms)', 'GC %', 'alloc GB/s', 'hit%']
    widths = [len(h) for h in header]
    rows = []
    for a in reports:
        stw = sum(a.pauses)
        r = [
            a.collector or '?',
            f'{a.runtime:.2f}',
            str(len(a.events)),
            f'{stw:.0f}',
            f'{stw / len(a.pauses):.2f}' if a.pauses else '?',
            f'{max(a.pauses):.2f}' if a.pauses else '?',
            f'{a.p95:.2f}',
            f'{a.gc_overhead_pct:.1f}',
            f'{a.avg_alloc_rate / 1024 ** 3:.1f}',
            f'{100 - a.gc_overhead_pct:.1f}',
        ]
        rows.append(r)
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    print('Comparison')
    print('-' * (sum(widths) + len(header) * 3))
    print('  '.join(h.ljust(widths[i]) for i, h in enumerate(header)))
    for r in rows:
        print('  '.join(c.ljust(widths[i]) for i, c in enumerate(r)))
    print('  hit% = mutator time share = 100 - GC %')
    print()


def main(argv):
    if not argv:
        print('usage: gc_analyze.py <gc-log> [gc-log ...]', file=sys.stderr)
        return 1
    reports = []
    for path in argv:
        a = Analysis(path)
        a.run()
        reports.append(a)
    if len(reports) > 1:
        compare(reports)
    for a in reports:
        print_report(a)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))