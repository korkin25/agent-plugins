"""Grafana panels for models by project and the factor policy follow the metric contract."""
import json
from pathlib import Path
import re
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
DASHBOARD = PLUGIN / "grafana" / "subagent-model-router.json"

BASE = {"instance", "agent", "project", "user"}
# Label contract per metric (lib/router_telemetry.py::_points and _version_gauge).
LABELS = {
    "smr_calls_total": BASE | {
        "provider", "reason", "model", "plugin_version", "agent_version", "host", "model_source",
        "recommended_model", "mode", "tier", "effort", "recommended_effort", "effort_source",
        "applied", "record_schema"},
    "smr_hook_version_last_seen_timestamp_seconds": {
        "instance", "host", "user", "project", "agent", "plugin_version", "agent_version"},
    "smr_policy_decisions_total": BASE | {
        "provider", "policy", "policy_mode", "outcome", "level", "model", "effort", "rank_status",
        "agreement", "applied"},
    "smr_policy_factor_levels_total": BASE | {"factor", "level"},
    "smr_policy_factor_confidence_bucket": BASE | {"factor", "le"},
    "smr_policy_factor_confidence_sum": BASE | {"factor"},
    "smr_policy_factor_confidence_count": BASE | {"factor"},
    "smr_policy_adjustments_total": BASE | {"adjustment"},
    "smr_selection_price_ratio_bucket": BASE | {"source", "le"},
    "smr_selection_price_ratio_sum": BASE | {"source"},
    "smr_selection_price_ratio_count": BASE | {"source"},
    "smr_selection_output_rate_usd_per_mtok_total": BASE | {"source", "model"},
    "smr_selection_priced_total": BASE | {"source", "model"},
}
VALUES = {
    "outcome": {"success", "answers", "range", "options", "sum", "unknown"},
    "agreement": {"identical", "same_model", "other_model", "policy_higher", "policy_lower", "unknown"},
    "source": {"choice", "policy", "selected"},
    "factor": {"reasoning", "spec", "verification", "scope", "impact", "review_depth"},
    "adjustment": {"impact_floor", "frontier_scope", "review_floor", "verified_discount", "prior_failure_raise",
                   "confidence_raise_reasoning", "confidence_raise_impact", "confidence_raise_scope",
                   "confidence_raise_review_depth"},
    "policy_mode": {"shadow", "active", "unknown"},
    "record_schema": {"direct", "legacy"},
    "reason": {"choice", "policy", "explicit"},
}
VARIABLES = {"instance": "$instance", "agent": "$agent", "project": "$project", "user": "$user"}
SELECTOR = re.compile(r"(smr_[a-z0-9_]+)\{([^}]*)\}")
MATCHER = re.compile(r'([a-z_]+)(=~|!~|!=|=)"([^"]*)"')
GROUPING = re.compile(r"\b(?:by|on)\s*\(([^)]*)\)")
NEW_ROWS = ["Models by project", "Factor policy (shadow)"]


def load():
    return json.loads(DASHBOARD.read_text())


def new_panels(doc):
    first = next(p for p in doc["panels"] if p["type"] == "row" and p["title"] == NEW_ROWS[0])
    return [p for p in doc["panels"] if p["id"] >= first["id"]]


class GrafanaPolicyPanelTests(unittest.TestCase):
    def test_rows_and_required_panels_exist(self):
        doc = load()
        rows = [p["title"] for p in doc["panels"] if p["type"] == "row"]
        self.assertEqual(rows, NEW_ROWS)
        titles = {p["title"]: p for p in new_panels(doc)}
        for title, kind in [
                ("Launched models by project", "table"), ("Jev recommended models by project", "table"),
                ("Launched models over time", "timeseries"), ("Policy agreement with Jev Choice", "stat"),
                ("Policy agreement with Jev Choice · breakdown", "bargauge"),
                ("Required level by project", "bargauge"), ("Policy model by project", "bargauge"),
                ("Policy lower share · potential savings", "stat"),
                ("Policy higher share · possible under-routing", "stat"),
                ("Policy lower / higher share over time", "timeseries"),
                ("Average output price per call by source", "bargauge"),
                ("Average output price per call by project", "bargauge"),
                ("Price ratio to cheapest offered model · p50 / p90", "bargauge"),
                ("Policy adjustments", "bargauge"), ("Policy outcome errors", "bargauge"),
                ("Policy outcome error share", "stat")] + [
                ("Factor level distribution · " + f, "timeseries") for f in sorted(VALUES["factor"])]:
            with self.subTest(title=title):
                self.assertIn(title, titles)
                self.assertEqual(titles[title]["type"], kind)

    def test_every_new_panel_is_described_and_filtered(self):
        for panel in new_panels(load()):
            with self.subTest(panel=panel["title"]):
                self.assertIn("standard-API references, not invoices", panel.get("description", ""))
                if panel["type"] == "row":
                    self.assertFalse(panel["collapsed"])
                    self.assertFalse(panel.get("targets"))
                    continue
                self.assertEqual(panel["datasource"]["uid"], "${DS_PROMETHEUS}")
                self.assertTrue(panel["targets"])
                for target in panel["targets"]:
                    selectors = SELECTOR.findall(target["expr"])
                    self.assertTrue(selectors)
                    for _, body in selectors:
                        for label, variable in VARIABLES.items():
                            self.assertIn(f'{label}=~"{variable}"', body)
                    time_series = panel["type"] == "timeseries"
                    self.assertEqual(target["range"], time_series)
                    self.assertEqual(target["instant"], not time_series)
                    self.assertIn("$__rate_interval" if time_series else "$__range", target["expr"])

    def test_expressions_use_only_contract_metrics_labels_and_values(self):
        doc = load()
        hook = next(p for p in doc["panels"] if p["title"] == "Observed hook versions · last hook age")
        for panel in new_panels(doc) + [hook]:
            for target in panel.get("targets", []):
                expr = target["expr"]
                with self.subTest(panel=panel["title"], ref=target["refId"]):
                    metrics = set()
                    for metric, body in SELECTOR.findall(expr):
                        self.assertIn(metric, LABELS)
                        metrics.add(metric)
                        for label, op, value in MATCHER.findall(body):
                            self.assertIn(label, LABELS[metric])
                            if label in VALUES and not value.startswith("$"):
                                for option in value.split("|") if op in ("=~", "!~") else [value]:
                                    self.assertIn(option, VALUES[label])
                    allowed = set().union(*(LABELS[m] for m in metrics))
                    for group in GROUPING.findall(expr):
                        for label in filter(None, (s.strip() for s in group.split(","))):
                            self.assertIn(label, allowed)
                    for metric, _ in SELECTOR.findall(expr):
                        if metric == "smr_calls_total":
                            self.assertIn('record_schema="direct"', expr)

    def test_policy_formulas(self):
        titles = {p["title"]: p for p in new_panels(load())}
        agreement = titles["Policy agreement with Jev Choice"]["targets"][0]["expr"]
        self.assertIn('outcome="success",agreement=~"identical|same_model"', agreement)
        self.assertEqual(agreement.count('outcome="success"'), 3)
        for title, value in [("Policy lower share · potential savings", "policy_lower"),
                             ("Policy higher share · possible under-routing", "policy_higher")]:
            self.assertIn(f'agreement="{value}"', titles[title]["targets"][0]["expr"])
        for title, grouping in [("Average output price per call by source", "source"),
                                ("Average output price per call by project", "project,source")]:
            expr = titles[title]["targets"][0]["expr"]
            numerator, denominator = expr.split(" / ")
            self.assertIn(f"sum by({grouping}) (increase(smr_selection_output_rate_usd_per_mtok_total{{", numerator)
            self.assertIn(f"sum by({grouping}) (increase(smr_selection_priced_total{{", denominator)
        quantiles = [t["expr"] for t in titles["Price ratio to cheapest offered model · p50 / p90"]["targets"]]
        self.assertEqual([q.split(",")[0] for q in quantiles],
                         ["histogram_quantile(0.5", "histogram_quantile(0.9"])
        for q in quantiles:
            self.assertIn("sum by(source,le) (increase(smr_selection_price_ratio_bucket{", q)

    def test_models_by_project_matrices(self):
        titles = {p["title"]: p for p in new_panels(load())}
        for title, column, excluded in [("Launched models by project", "model", 'model!="unknown"'),
                                        ("Jev recommended models by project", "recommended_model",
                                         'recommended_model!="unknown"')]:
            with self.subTest(title=title):
                panel = titles[title]
                target = panel["targets"][0]
                self.assertEqual(target["format"], "table")
                self.assertIn(f"sum by(project,{column}) (increase(smr_calls_total{{", target["expr"])
                self.assertIn(excluded, target["expr"])
                self.assertEqual(panel["transformations"], [{"id": "groupingToMatrix", "options": {
                    "columnField": column, "rowField": "project", "valueField": "Value"}}])
        self.assertIn('reason=~"choice|policy"', titles["Jev recommended models by project"]["targets"][0]["expr"])
        series = titles["Launched models over time"]
        self.assertEqual(series["fieldConfig"]["defaults"]["custom"]["stacking"]["mode"], "normal")
        self.assertIn('sum by(model) (rate(smr_calls_total{', series["targets"][0]["expr"])

    def test_hook_version_table_groups_by_project(self):
        doc = load()
        hook = next(p for p in doc["panels"] if p["title"] == "Observed hook versions · last hook age")
        expr = hook["targets"][0]["expr"]
        self.assertIn("max by(instance,host,user,project,agent,plugin_version,agent_version)", expr)
        self.assertIn('project=~"$project"', expr)
        self.assertIn('"project", "unknown", "project", "^$"', expr)
        index = hook["transformations"][0]["options"]["indexByName"]
        self.assertIn("project", index)
        self.assertEqual(sorted(index.values()), list(range(len(index))))
        self.assertNotIn("independent of project", hook["description"])

    def test_ids_unique_and_grid_does_not_overlap(self):
        panels = load()["panels"]
        ids = [p["id"] for p in panels]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(any(39 <= i <= 43 for i in ids))
        boxes = []
        for panel in panels:
            g = panel["gridPos"]
            self.assertGreaterEqual(g["x"], 0)
            self.assertLessEqual(g["x"] + g["w"], 24)
            self.assertGreater(g["w"], 0)
            self.assertGreater(g["h"], 0)
            boxes.append((panel["title"], g))
        for i, (a_title, a) in enumerate(boxes):
            for b_title, b in boxes[i + 1:]:
                overlap = (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
                           and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])
                self.assertFalse(overlap, f"{a_title} overlaps {b_title}")


if __name__ == "__main__":
    unittest.main()
