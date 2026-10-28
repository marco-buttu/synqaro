from dataclasses import FrozenInstanceError
from concurrent.futures import ThreadPoolExecutor
import json
import unittest

from simquaro.faults import FaultContext, FaultController, FaultEffect, FaultRule, Scenario


class FaultTests(unittest.TestCase):
    def test_immediate_activation_and_clear_are_persistent(self):
        faults = FaultController()
        faults.activate("clock_untrusted")
        self.assertTrue(faults.is_active("clock_untrusted"))
        self.assertEqual(faults.emit(FaultContext("response_ready")), ())
        faults.clear("clock_untrusted")
        self.assertFalse(faults.is_active("clock_untrusted"))
        faults.clear("clock_untrusted")

    def test_one_shot_delivery_only_consumed_by_matching_event(self):
        faults = FaultController()
        rule_id = faults.schedule("drop_response", when="frequency_set_verified")
        self.assertEqual(rule_id, "rule-1")
        self.assertEqual(faults.emit(FaultContext("response_ready")), ())
        effects = faults.emit(FaultContext("frequency_set_verified", "a", 1, "set", "frequency"))
        self.assertEqual([(effect.name, effect.rule_id) for effect in effects],
                         [("drop_response", "rule-1")])
        self.assertEqual(faults.emit(FaultContext("frequency_set_verified")), ())

    def test_occurrences_are_instance_wide_and_cancellation_removes_remaining(self):
        faults = FaultController()
        rule_id = faults.schedule("delay_response", when="response_ready", times=2,
                                  parameters={"delay_ms": 50})
        for session in ("client-a", "client-b"):
            self.assertEqual(faults.emit(FaultContext("response_ready", session, 1))[0].name,
                             "delay_response")
        self.assertEqual(faults.emit(FaultContext("response_ready", "client-c", 1)), ())
        self.assertEqual(faults.snapshot()["rules"], [])
        second = faults.schedule("drop_response", when="response_ready", times=2)
        faults.emit(FaultContext("response_ready", "client-a", 2))
        self.assertEqual(faults.snapshot()["rules"][0]["remaining"], 1)
        faults.cancel(second)
        self.assertEqual(faults.emit(FaultContext("response_ready")), ())
        self.assertNotEqual(second, rule_id)
        with self.assertRaises(ValueError):
            faults.cancel(second)

    def test_phase_activation_survives_rule_consumption_and_cancel(self):
        faults = FaultController()
        rule_id = faults.schedule("calibration_reference_unavailable",
                                  when="calibrate_reference_measurement", times=2)
        self.assertFalse(faults.is_active("calibration_reference_unavailable"))
        self.assertEqual(faults.emit(FaultContext("calibrate_reference_measurement")), ())
        self.assertTrue(faults.is_active("calibration_reference_unavailable"))
        faults.cancel(rule_id)
        self.assertTrue(faults.is_active("calibration_reference_unavailable"))

    def test_compatible_effects_preserve_creation_order(self):
        faults = FaultController()
        faults.schedule("malformed_response", when="response_ready")
        faults.schedule("clock_untrusted", when="response_ready")
        faults.schedule("delay_response", when="response_ready", parameters={"delay_ms": 1})
        faults.schedule("omit_lf", when="response_ready")
        effects = faults.emit(FaultContext("response_ready"))
        self.assertEqual([effect.name for effect in effects],
                         ["malformed_response", "delay_response", "omit_lf"])
        self.assertTrue(faults.is_active("clock_untrusted"))

    def test_accumulated_delivery_effects_are_checked_before_transport_mutation(self):
        faults = FaultController()
        faults.schedule("drop_response", when="frequency_set_verified")
        earlier = faults.emit(FaultContext("frequency_set_verified"))
        # The first rule has gone; control may schedule a new rule before the
        # ordinary response hook. The transport must validate the combination.
        faults.schedule("disconnect", when="response_ready")
        later = faults.emit(FaultContext("response_ready"))
        with self.assertRaises(ValueError):
            faults.validate_delivery_effects(earlier + later)
        faults.validate_delivery_effects((FaultEffect("delay_response", {"delay_ms": 1}),
                                         FaultEffect("malformed_response"), FaultEffect("omit_lf")))
        with self.assertRaises(ValueError):
            faults.validate_delivery_effects((FaultEffect("clock_untrusted"),))

    def test_concurrent_sessions_atomically_consume_occurrences(self):
        faults = FaultController()
        faults.schedule("drop_response", when="response_ready", times=2)
        with ThreadPoolExecutor(max_workers=8) as clients:
            results = list(clients.map(lambda index: faults.emit(
                FaultContext("response_ready", f"client-{index}", 1)), range(32)))
        self.assertEqual(sum(len(effects) for effects in results), 2)
        self.assertEqual(faults.snapshot()["rules"], [])

    def test_incompatible_wire_rules_rejected_without_partial_mutation(self):
        for first, second in (("drop_response", "delay_response"),
                              ("disconnect", "omit_lf"),
                              ("reorder_responses", "delay_response"),
                              ("omit_lf", "omit_lf")):
            for trigger in ("response_ready", "frequency_set_verified"):
                with self.subTest(first=first, second=second, trigger=trigger):
                    faults = FaultController()
                    parameters = {"delay_ms": 1} if first == "delay_response" else None
                    faults.schedule(first, when="frequency_set_verified", parameters=parameters)
                    before = faults.snapshot()
                    parameters = {"delay_ms": 1} if second == "delay_response" else None
                    with self.assertRaises(ValueError):
                        faults.schedule(second, when=trigger, parameters=parameters)
                    self.assertEqual(faults.snapshot(), before)
                    faults.cancel("rule-1")
                    self.assertEqual(faults.schedule(second, when=trigger, parameters=parameters),
                                     "rule-2")

    def test_invalid_inputs_leave_existing_rules_and_faults_unchanged(self):
        faults = FaultController()
        faults.activate("clock_untrusted")
        before = faults.snapshot()
        for changes in (
            {"name": "unknown"}, {"when": "arbitrary.method"},
            {"when": "calibrate_reference_measurement"},
            {"times": 0}, {"times": -1}, {"times": True}, {"times": 1.5},
            {"times": 2**32}, {"parameters": {"unexpected": 1}},
            {"parameters": []}, {"parameters": {"delay_ms": 1}},
        ):
            arguments = {"name": "drop_response", "when": "response_ready"} | changes
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                faults.schedule(**arguments)
            self.assertEqual(faults.snapshot(), before)
        for parameters in (None, {}, {"delay_ms": 0}, {"delay_ms": 60001},
                           {"delay_ms": True}, {"delay_ms": 1.5},
                           {"delay_ms": 1, "other": 2}):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                faults.schedule("delay_response", when="response_ready", parameters=parameters)
        for operation in (lambda: faults.activate("drop_response"),
                          lambda: faults.activate("clock_untrusted", {"x": 1}),
                          lambda: faults.clear("unknown"),
                          lambda: faults.is_active("unknown")):
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(faults.snapshot(), before)

    def test_delay_boundaries_are_valid_and_parameters_are_detached(self):
        for delay in (1, 60000):
            parameters = {"delay_ms": delay}
            faults = FaultController()
            faults.schedule("delay_response", when="response_ready", parameters=parameters)
            parameters["delay_ms"] = 0
            effect = faults.emit(FaultContext("response_ready"))[0]
            self.assertEqual(effect.parameters["delay_ms"], delay)
            with self.assertRaises(TypeError):
                effect.parameters["delay_ms"] = 100

    def test_capacity_is_64_and_consumption_or_cancel_releases_capacity(self):
        faults = FaultController()
        for _ in range(64):
            faults.schedule("clock_untrusted", when="response_ready")
        before = faults.snapshot()
        with self.assertRaises(ValueError):
            faults.schedule("clock_untrusted", when="response_ready")
        self.assertEqual(faults.snapshot(), before)
        faults.cancel("rule-1")
        self.assertEqual(faults.schedule("clock_untrusted", when="response_ready"), "rule-65")
        faults.emit(FaultContext("response_ready"))
        self.assertEqual(faults.snapshot()["rules"], [])
        self.assertEqual(faults.schedule("clock_untrusted", when="response_ready"), "rule-66")

    def test_immutable_scenario_replays_into_independent_controllers(self):
        initial = [FaultEffect("clock_untrusted", {})]
        rules = [FaultRule("delay_response", "response_ready", times=2,
                           parameters={"delay_ms": 25})]
        scenario = Scenario(initial_faults=initial, rules=rules)
        initial.clear()
        rules.clear()
        with self.assertRaises(FrozenInstanceError):
            scenario.rules = ()
        first, second = FaultController(scenario), FaultController(scenario)
        first.clear("clock_untrusted")
        first.emit(FaultContext("response_ready", "a", 1))
        self.assertTrue(second.is_active("clock_untrusted"))
        self.assertEqual(second.snapshot()["rules"][0]["remaining"], 2)
        self.assertEqual(first.snapshot()["rules"][0]["remaining"], 1)
        first.cancel("rule-1")
        self.assertEqual(len(FaultController(scenario).snapshot()["rules"]), 1)

    def test_scenario_rejects_invalid_initial_faults_and_conflicting_rules(self):
        with self.assertRaises(ValueError):
            Scenario(initial_faults=(FaultEffect("drop_response", {}),))
        with self.assertRaises(ValueError):
            Scenario(initial_faults=("clock_untrusted",))
        with self.assertRaises(ValueError):
            Scenario(rules=(FaultRule("drop_response", "response_ready"),
                            FaultRule("disconnect", "frequency_set_verified")))
        with self.assertRaises(ValueError):
            Scenario(rules=(FaultRule("clock_untrusted", "response_ready"),) * 65)

    def test_context_validation_prevents_invalid_or_unbounded_diagnostics(self):
        for changes in ({"event": "unknown"}, {"session_id": "x" * 65},
                        {"session_id": "bad\n"}, {"request_id": True},
                        {"request_id": 0}, {"request_id": 2**32},
                        {"command": "x" * 65}, {"target": "bad\n"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                FaultContext(**({"event": "response_ready"} | changes))

    def test_catalog_and_snapshots_are_detached_bounded_json(self):
        faults = FaultController()
        catalog = faults.catalog()
        self.assertEqual({entry["name"] for entry in catalog}, {
            "calibration_reference_unavailable", "frequency_lock_failure",
            "synthesizer_failure", "frequency_read_failure", "clock_untrusted",
            "procedure_stall", "stop_unconfirmed", "drop_response", "delay_response",
            "omit_lf", "malformed_response", "reorder_responses", "disconnect"})
        definitions = {entry["name"]: entry for entry in catalog}
        self.assertEqual(definitions["reorder_responses"]["limits"],
                         {"held_replies_per_rule_session": 1, "release_timeout_ms": 2000})
        self.assertIn("retain", definitions["malformed_response"]["effect"])
        self.assertEqual(definitions["delay_response"]["parameters"]["delay_ms"],
                         {"type": "integer", "min": 1, "max": 60000})
        catalog[0]["name"] = "mutated"
        self.assertNotIn("mutated", [entry["name"] for entry in faults.catalog()])
        faults.activate("clock_untrusted")
        for _ in range(64):
            faults.schedule("clock_untrusted", when="response_ready", times=4294967295)
        snapshot = faults.snapshot()
        self.assertLess(len(json.dumps(snapshot).encode()), 65536)
        self.assertLess(len(json.dumps(faults.catalog()).encode()), 65536)
        snapshot["active"].clear()
        snapshot["rules"][0]["remaining"] = 0
        self.assertTrue(faults.is_active("clock_untrusted"))
        self.assertEqual(faults.snapshot()["rules"][0]["remaining"], 4294967295)


if __name__ == "__main__":
    unittest.main()
