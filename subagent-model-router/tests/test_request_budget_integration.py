"""Jev receives compact task estimates without changing reported API usage."""
import json
from test_router import Sandbox, router, v2_args


class RequestBudgetIntegrationTests(Sandbox):
    def test_hook_sends_size_once_and_preserves_actual_provider_usage(self):
        self.serve()
        self.write_config()
        task = "Проверить CSV: quoted commas, empty fields."
        rc, output, error, _ = self.codex_hook(v2_args(message=task))
        self.assertEqual((rc, error), (0, ""))
        self.assertIn("updatedInput", json.loads(output)["hookSpecificOutput"])
        sent = json.loads(self.fake.requests[0]["body"])
        instructions = sent["questions"]["selection"]["instructions"]
        self.assertEqual(instructions.count("Visible task estimate:"), 1)
        estimate = json.loads(instructions.split("Visible task estimate: ", 1)[1].split("; Shared model context:", 1)[0])
        self.assertEqual(estimate, router.estimated_request(sent["state"]))
        self.assertTrue(estimate["visible_task"]["approximate"])
        row = self.last_row()
        self.assertEqual(row["visible_task_estimate"], estimate)
        self.assertEqual(row["usage"]["input_tokens"], 300)
        self.assertIsNone(row["task_input_cost_estimate"]["uncached_input_usd_estimate"])

    def test_shared_model_costs_are_once_per_model_with_separate_context_bands(self):
        price = {"status": "stale", "input": 2, "long_context": {"input": 4},
                 "retrieved_at": 123, "source_url": "https://official.example/pricing"}
        options = {effort: {"model": "future-model", "effort": effort,
                           "model_description": "Native purpose", "effort_description": effort,
                           "price_reference": price} for effort in ("low", "high")}
        estimate = router.estimated_request({"description": "", "task": "abcd" * 1000})
        question = router.selection_questions(options, "codex", estimate)["selection"]
        shared = json.loads(question["instructions"].split("Shared model context: ", 1)[1])
        self.assertEqual(set(shared), {"future-model"})
        self.assertEqual(shared["future-model"]["estimated_uncached_task_input_usd"],
                         {"standard_context": .002, "long_context": .004})
        self.assertEqual(shared["future-model"]["price_reference"]["status"], "stale")
        self.assertEqual(set(question["criteria"]), {"low", "high"})
        self.assertNotIn("estimated_uncached_task_input_usd", json.dumps(question["criteria"]))
