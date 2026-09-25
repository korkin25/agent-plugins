#!/usr/bin/env python3
"""Paired synthetic Jev evaluation. --live explicitly sends only frozen fixtures."""
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import random
import statistics
import time
import sys
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('router_eval', str(ROOT / 'bin/subagent-model-router'))
spec = importlib.util.spec_from_loader(loader.name, loader)
router = importlib.util.module_from_spec(spec)
loader.exec_module(router)


def legacy(description, text):
    lines = [line.strip() for line in text.splitlines() if line.lstrip().startswith(('TASK:', 'ROLE:'))]
    return {'description': router.redact(description),
            'task': router.redact('\n'.join(lines)) if lines else router.redact(text)[:1500]}


def metrics(rows, cases, thresholds):
    labels = {c['id']: c['expected'] for c in cases}
    report = {}
    order = {'light': 0, 'standard': 1, 'heavy': 2}
    for variant in ('legacy', 'full_text'):
        subset = [r for r in rows if r['variant'] == variant]
        good = [r for r in subset if 'probs' in r]
        counts = dict(attempts=len(subset), successful=len(good), failures=len(subset)-len(good),
                      tier_correct=0, route_correct=0, risk_false_positive=0, risk_false_negative=0,
                      review_correct=0, under_routed=0, over_routed=0, repeat_disagreements=0)
        for r in good:
            expected = labels[r['case']]
            raw = max(r['probs']['tier'], key=r['probs']['tier'].get)
            want = 'heavy' if expected['risky'] or expected['review'] else expected['tier']
            risk = r['probs']['risky'] >= thresholds['risky_max']
            review = r['probs']['review'] >= thresholds['review_max']
            counts['tier_correct'] += raw == expected['tier']
            counts['route_correct'] += r['tier'] == want
            counts['risk_false_positive'] += risk and not expected['risky']
            counts['risk_false_negative'] += not risk and expected['risky']
            counts['review_correct'] += review == expected['review']
            counts['under_routed'] += order[r['tier']] < order[want]
            counts['over_routed'] += order[r['tier']] > order[want]
        for c in cases:
            runs = [r for r in good if r['case'] == c['id']]
            counts['repeat_disagreements'] += len({(r['tier'], r['reason']) for r in runs}) > 1
        costs = [r['usage']['cost'] for r in good if 'cost' in r.get('usage', {})]
        counts['known_cost_requests'] = len(costs)
        counts['reported_cost_sum'] = sum(costs) if costs else None
        counts['reported_cost_mean'] = statistics.mean(costs) if costs else None
        counts['input_tokens_sum'] = sum(r.get('usage', {}).get('input_tokens', 0) for r in good)
        counts['mean_latency_ms'] = round(statistics.mean(r['latency_ms'] for r in good), 1) if good else None
        counts['mean_state_chars'] = round(statistics.mean(r['state_chars'] for r in subset), 1) if subset else None
        counts['mean_state_utf8_bytes'] = round(statistics.mean(r['state_bytes'] for r in subset), 1) if subset else None
        counts['risk_negative_cases'] = sum(not labels[r['case']]['risky'] for r in good)
        counts['risk_positive_cases'] = sum(labels[r['case']]['risky'] for r in good)
        report[variant] = counts
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live', action='store_true')
    p.add_argument('--output', required=True)
    p.add_argument('--repeats', type=int, default=2, choices=(1, 2))
    p.add_argument('--cases', default=str(Path(__file__).with_name('cases.json')))
    args = p.parse_args()
    raw = Path(args.cases).read_bytes()
    dataset = json.loads(raw)
    cases = dataset['cases'] if isinstance(dataset, dict) else dataset
    cfg = router.load_config() if args.live else router.DEFAULT_RULES
    if cfg is None:
        raise SystemExit('Router config unavailable')
    key = None
    if args.live:
        key, problem = router.read_key(cfg['key_file'])
        if key is None:
            raise SystemExit('Configured key unavailable: ' + str(problem))
    rows = []
    jobs = [(c, repeat) for c in cases for repeat in range(args.repeats)]
    random.Random(20260925).shuffle(jobs)
    meta = {'dataset_sha256': hashlib.sha256(raw).hexdigest(), 'repeats': args.repeats,
            'model': cfg['model'], 'provider': cfg['provider'], 'thresholds': cfg['thresholds'],
            'questions_sha256': hashlib.sha256(json.dumps(router.QUESTIONS, sort_keys=True).encode()).hexdigest(),
            'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'live': args.live, 'timeout_seconds': cfg['timeout_seconds'],
            'note': 'Synthetic expert labels; fixed questions/thresholds, interleaved order. No task execution/quality or monetary savings measured.'}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise SystemExit('Refusing to overwrite evaluation output')
    with target.open('x', encoding='utf-8') as output:
        output.write(json.dumps({'meta': meta}, ensure_ascii=False) + '\n'); output.flush()
        for idx, (case, repeat) in enumerate(jobs):
            variants = ('legacy', 'full_text') if idx % 2 == 0 else ('full_text', 'legacy')
            for variant in variants:
                build = legacy if variant == 'legacy' else router.build_state
                state = build(case['description'], case['task'])
                encoded = json.dumps(state, ensure_ascii=False)
                row = {'case': case['id'], 'repeat': repeat, 'variant': variant,
                       'state_chars': len(encoded), 'state_bytes': len(encoded.encode()),
                       'state_sha256': router.state_digest(state)}
                if args.live:
                    try:
                        if state.get('input_quality', {}).get('oversized'):
                            raise router.JevError('input_size')
                        response = router.ask_jev(cfg, key, state)
                        tier, reason = router.choose_tier(response['probs'], cfg['thresholds'])
                        row.update(probs=response['probs'], tier=tier, reason=reason,
                                   latency_ms=response['latency_ms'], model=response['jev_model'], usage=response.get('usage', {}))
                    except router.JevError as exc:
                        row.update(error=exc.kind, latency_ms=exc.latency_ms)
                else:
                    row['dry_run'] = True
                rows.append(row)
                output.write(json.dumps(row, ensure_ascii=False) + '\n'); output.flush()
            print(f'{idx+1}/{len(jobs)} {case["id"]}', flush=True)
        result = metrics(rows, cases, cfg['thresholds'])
        output.write(json.dumps({'summary': result}) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
